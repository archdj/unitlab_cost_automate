from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "unitlab-cost-analysis"
DB = REPO / "db" / "cost_analysis.db"
DEFAULT_REQUEST = ROOT / "cost-analysis-program-plan" / "harness" / "examples" / "evidence_estimate_request.json"
REPORT_DIR = ROOT / "cost-analysis-program-plan" / "harness" / "reports"

ESSENTIAL_WORK_CODES = [
    "STR-ST",
    "FIN-PANEL",
    "FIN-LGS",
    "EXT-WIN",
    "MEP-ELEC",
    "SITE-MOD-002",
]


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def load_request(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_module(con: sqlite3.Connection, module_code: str) -> dict | None:
    row = con.execute(
        """
        SELECT module_type_id, module_code, module_name, floor_area_m2, pyeong,
               structure_type, finish_grade
        FROM module_types
        WHERE module_code = ?
        """,
        (module_code,),
    ).fetchone()
    if row:
        return dict(row)

    row = con.execute(
        """
        SELECT id AS module_type_id, module_name AS module_code, module_name,
               floor_area_m2, pyeong, NULL AS structure_type, NULL AS finish_grade
        FROM quote_module_catalog
        WHERE module_name = ?
        """,
        (module_code,),
    ).fetchone()
    return dict(row) if row else None


def selected_modules(con: sqlite3.Connection, request: dict) -> list[dict]:
    out = []
    for item in request.get("modules", []):
        mod = get_module(con, item["module_code"])
        if not mod:
            out.append({
                "module_code": item["module_code"],
                "quantity": item.get("quantity", 1),
                "error": "unknown_module",
            })
            continue
        qty = int(item.get("quantity", 1) or 1)
        mod["quantity"] = qty
        mod["extended_area_m2"] = (mod.get("floor_area_m2") or 0) * qty
        out.append(mod)
    return out


def find_source_cases(con: sqlite3.Connection, modules: list[dict]) -> list[dict]:
    target_pyeong = [
        float(m["pyeong"]) for m in modules
        if not m.get("error") and m.get("pyeong") is not None
    ]
    target_area = sum(float(m.get("extended_area_m2") or 0) for m in modules)
    module_type_ids = [m["module_type_id"] for m in modules if not m.get("error") and m.get("module_type_id")]

    params: list = []
    where = ["ac.total_amount > 0"]
    if module_type_ids:
        where.append("pm.module_type_id IN ({})".format(",".join("?" for _ in module_type_ids)))
        params.extend(module_type_ids)
    elif target_pyeong:
        lo = min(target_pyeong) - 1.5
        hi = max(target_pyeong) + 1.5
        where.append("mt.pyeong BETWEEN ? AND ?")
        params.extend([lo, hi])
    elif target_area:
        where.append("mt.floor_area_m2 BETWEEN ? AND ?")
        params.extend([target_area * 0.75, target_area * 1.25])

    sql = f"""
        SELECT p.project_id, p.project_code, p.project_name,
               mt.module_code, mt.floor_area_m2, mt.pyeong,
               COUNT(ac.actual_cost_id) AS actual_rows,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt ON pm.module_type_id = mt.module_type_id
        WHERE {' AND '.join(where)}
        GROUP BY p.project_id
        HAVING mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        ORDER BY ABS(mt.floor_area_m2 - ?) ASC, actual_rows DESC
        LIMIT 12
    """
    params.append(target_area if target_area else 0)
    return [dict(r) for r in con.execute(sql, tuple(params)).fetchall()]


def component_estimates(con: sqlite3.Connection, source_cases: list[dict], requested_area: float) -> list[dict]:
    if not source_cases or requested_area <= 0:
        return []

    project_ids = [c["project_id"] for c in source_cases]
    placeholders = ",".join("?" for _ in project_ids)
    rows = con.execute(
        f"""
        SELECT p.project_code, mt.floor_area_m2,
               wc.category, wc.work_code, wc.work_name_ko,
               ac.source_ref AS cost_type,
               SUM(ac.total_amount) AS amount
        FROM actual_costs ac
        JOIN projects p ON ac.project_id = p.project_id
        JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt ON pm.module_type_id = mt.module_type_id
        WHERE ac.project_id IN ({placeholders})
          AND ac.total_amount > 0
          AND mt.floor_area_m2 IS NOT NULL
          AND mt.floor_area_m2 > 0
        GROUP BY p.project_id, wc.work_code_id, ac.source_ref
        """,
        tuple(project_ids),
    ).fetchall()

    grouped: dict[tuple, list[dict]] = {}
    for r in rows:
        rate = float(r["amount"]) / float(r["floor_area_m2"])
        key = (r["category"], r["work_code"], r["work_name_ko"], r["cost_type"] or "unknown")
        grouped.setdefault(key, []).append({
            "project_code": r["project_code"],
            "amount": float(r["amount"]),
            "area": float(r["floor_area_m2"]),
            "rate_per_m2": rate,
        })

    components = []
    for (category, work_code, work_name, cost_type), samples in grouped.items():
        if len(samples) < 1:
            continue
        rates = [s["rate_per_m2"] for s in samples]
        med_rate = median(rates)
        amount = round(med_rate * requested_area)
        evidence_level = "actual_same_module" if len(source_cases) > 0 else "missing"
        confidence = min(0.85, 0.35 + 0.08 * len(samples))
        components.append({
            "component_type": "work_code_cost_type",
            "category": category,
            "work_code": work_code,
            "work_name": work_name,
            "cost_type": cost_type,
            "amount": amount,
            "quantity": None,
            "unit": None,
            "unit_price": None,
            "basis": "similar_case_median_per_m2",
            "formula": "median(actual_amount / floor_area_m2) * requested_area_m2",
            "median_rate_per_m2": round(med_rate),
            "sample_count": len(samples),
            "source_cases": [s["project_code"] for s in samples],
            "source_tables": ["actual_costs", "project_modules", "module_types", "work_codes"],
            "evidence_level": evidence_level,
            "confidence": round(confidence, 2),
            "status": "estimated",
        })

    return sorted(components, key=lambda x: x["amount"], reverse=True)


def detect_missing(components: list[dict]) -> list[dict]:
    present = {c["work_code"] for c in components if c["amount"] > 0}
    missing = []
    for code in ESSENTIAL_WORK_CODES:
        if code not in present:
            missing.append({
                "work_code": code,
                "reason": "essential work code has no evidence component in selected source cases",
                "status": "missing",
                "action": "review_required",
            })
    return missing


def summarize_cost_types(components: list[dict]) -> dict:
    out: dict[str, int] = {}
    for c in components:
        out[c["cost_type"]] = out.get(c["cost_type"], 0) + int(c["amount"])
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def build_estimate(request: dict) -> dict:
    con = db()
    modules = selected_modules(con, request)
    requested_area = sum(float(m.get("extended_area_m2") or 0) for m in modules if not m.get("error"))
    source_cases = find_source_cases(con, modules)
    components = component_estimates(con, source_cases, requested_area)
    missing = detect_missing(components)
    total = sum(int(c["amount"]) for c in components if c["status"] in {"confirmed", "estimated"})

    return {
        "request": request,
        "selected_modules": modules,
        "total": {
            "confirmed_amount": 0,
            "estimated_amount": total,
            "missing_amount": None,
            "display_total": total,
            "currency": "KRW",
        },
        "coverage": {
            "actual_case_count": len(source_cases),
            "component_count": len(components),
            "missing_required_count": len(missing),
            "material_price_coverage": 0.0,
            "note": "material-level prices are unavailable until actual_costs are linked to material_id/quantity/unit_price.",
        },
        "source_cases": source_cases,
        "cost_type_summary": summarize_cost_types(components),
        "components": components,
        "missing": missing,
        "warnings": [
            "This prototype uses actual similar-case median KRW/m2 by work code and cost type.",
            "It does not insert missing work codes automatically.",
            "PROCURE CSV has material quantities but no amount column.",
            "actual_costs currently has no material_id, quantity, or unit_price links.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate evidence-backed modular cost estimate from current DB.")
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--out", type=Path, default=REPORT_DIR / "evidence_estimate_sample.json")
    args = parser.parse_args()

    estimate = build_estimate(load_request(args.request))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(estimate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
