from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
DEFAULT_REQUEST = ROOT / "cost-analysis-program-plan" / "harness" / "examples" / "evidence_estimate_request.json"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "verified_evidence_estimate_sample.json"

ESSENTIAL_WORK_CODES = [
    "STR-ST",
    "FIN-PANEL",
    "FIN-LGS",
    "EXT-WIN",
    "MEP-ELEC",
    "SITE-MOD-002",
]


def connect() -> sqlite3.Connection:
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
    modules = []
    for item in request.get("modules", []):
        module_code = item["module_code"]
        qty = int(item.get("quantity", 1) or 1)
        module = get_module(con, module_code)
        if not module:
            modules.append({
                "module_code": module_code,
                "quantity": qty,
                "status": "missing_module",
            })
            continue
        module["quantity"] = qty
        module["extended_area_m2"] = float(module["floor_area_m2"] or 0) * qty
        module["status"] = "selected"
        modules.append(module)
    return modules


def approved_cases(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """
        SELECT f.ifc_file_id, p.project_id, p.project_code, p.project_name,
               mt.module_type_id, mt.module_code, mt.module_name, mt.floor_area_m2, mt.pyeong,
               COUNT(DISTINCT ac.actual_cost_id) AS actual_rows,
               SUM(DISTINCT ac.total_amount) AS actual_total,
               COUNT(DISTINCT bq.bim_qty_id) AS bim_rows
        FROM ifc_project_link_reviews r
        JOIN ifc_files f ON r.ifc_file_id = f.ifc_file_id
        JOIN projects p ON f.project_id = p.project_id
        JOIN module_types mt ON f.module_type_id = mt.module_type_id
        JOIN project_modules pm ON p.project_id = pm.project_id
           AND pm.module_type_id = f.module_type_id
        JOIN actual_costs ac ON p.project_id = ac.project_id
        JOIN bim_quantities bq ON f.ifc_file_id = bq.ifc_file_id
        WHERE r.approval_status = 'approved'
        GROUP BY f.ifc_file_id
        ORDER BY p.project_code
        """
    ).fetchall()
    return [dict(r) for r in rows]


def choose_cases(cases: list[dict], modules: list[dict], max_cases: int = 8) -> list[dict]:
    selected = [m for m in modules if m.get("status") == "selected"]
    target_area = sum(float(m.get("extended_area_m2") or 0) for m in selected)
    target_module_ids = {m["module_type_id"] for m in selected if m.get("module_type_id")}
    target_pyeongs = [float(m["pyeong"]) for m in selected if m.get("pyeong")]

    def score(case: dict) -> tuple[int, float, int]:
        same_module = 0 if case["module_type_id"] in target_module_ids else 1
        area_gap = abs(float(case["floor_area_m2"] or 0) - target_area) if target_area else 0
        if target_pyeongs and case.get("pyeong") is not None:
            pyeong_gap = min(abs(float(case["pyeong"]) - p) for p in target_pyeongs)
        else:
            pyeong_gap = 99
        return (same_module, area_gap + pyeong_gap * 3.3058, -int(case["actual_rows"] or 0))

    return sorted(cases, key=score)[:max_cases]


def component_rows(con: sqlite3.Connection, source_cases: list[dict]) -> list[dict]:
    if not source_cases:
        return []
    project_ids = [c["project_id"] for c in source_cases]
    placeholders = ",".join("?" for _ in project_ids)
    rows = con.execute(
        f"""
        SELECT p.project_code, p.project_name, mt.module_code, mt.floor_area_m2, mt.pyeong,
               wc.category, wc.work_code, wc.work_name_ko,
               ac.source_ref AS cost_type,
               SUM(ac.total_amount) AS actual_amount,
               COUNT(ac.actual_cost_id) AS actual_rows
        FROM actual_costs ac
        JOIN projects p ON ac.project_id = p.project_id
        JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
        JOIN project_modules pm ON p.project_id = pm.project_id
        JOIN module_types mt ON pm.module_type_id = mt.module_type_id
        WHERE ac.project_id IN ({placeholders})
          AND ac.total_amount > 0
        GROUP BY p.project_id, wc.work_code_id, ac.source_ref
        """,
        tuple(project_ids),
    ).fetchall()
    return [dict(r) for r in rows]


def estimate_components(rows: list[dict], requested_area: float) -> list[dict]:
    grouped: dict[tuple, list[dict]] = {}
    for row in rows:
        area = float(row["floor_area_m2"] or 0)
        if area <= 0:
            continue
        key = (
            row["category"],
            row["work_code"],
            row["work_name_ko"],
            row["cost_type"] or "unknown",
        )
        grouped.setdefault(key, []).append({
            "project_code": row["project_code"],
            "module_code": row["module_code"],
            "actual_amount": int(row["actual_amount"] or 0),
            "area_m2": area,
            "rate_per_m2": float(row["actual_amount"] or 0) / area,
        })

    components = []
    for (category, work_code, work_name, cost_type), samples in grouped.items():
        rates = [s["rate_per_m2"] for s in samples]
        med_rate = median(rates)
        amount = round(med_rate * requested_area)
        source_cases = sorted({s["project_code"] for s in samples})
        components.append({
            "component_type": "work_code_cost_type",
            "category": category,
            "work_code": work_code,
            "work_name": work_name,
            "cost_type": cost_type,
            "amount": amount,
            "basis": "verified_approved_ifc_case_median_per_m2",
            "formula": "median(approved_actual_amount / module_area_m2) * requested_area_m2",
            "requested_area_m2": requested_area,
            "median_rate_per_m2": round(med_rate),
            "sample_count": len(samples),
            "source_cases": source_cases,
            "source_tables": [
                "ifc_project_link_reviews",
                "ifc_files",
                "actual_costs",
                "project_modules",
                "module_types",
                "work_codes",
            ],
            "evidence_level": "approved_ifc_notion_actual",
            "confidence": round(min(0.9, 0.45 + len(source_cases) * 0.08), 2),
            "status": "estimated",
        })
    return sorted(components, key=lambda x: x["amount"], reverse=True)


def cost_type_summary(components: list[dict]) -> dict:
    summary: dict[str, int] = {}
    for comp in components:
        summary[comp["cost_type"]] = summary.get(comp["cost_type"], 0) + int(comp["amount"])
    return dict(sorted(summary.items(), key=lambda x: -x[1]))


def missing_required(components: list[dict]) -> list[dict]:
    present = {c["work_code"] for c in components if c["amount"] > 0}
    missing = []
    for code in ESSENTIAL_WORK_CODES:
        if code not in present:
            missing.append({
                "work_code": code,
                "status": "missing",
                "reason": "required work code was not found in approved evidence components",
            })
    return missing


def build_estimate(request: dict) -> dict:
    con = connect()
    modules = selected_modules(con, request)
    requested_area = sum(float(m.get("extended_area_m2") or 0) for m in modules if m.get("status") == "selected")
    cases = approved_cases(con)
    chosen = choose_cases(cases, modules)
    components = estimate_components(component_rows(con, chosen), requested_area)
    missing = missing_required(components)
    total = sum(int(c["amount"]) for c in components if c["status"] == "estimated")

    same_module_cases = [
        c for c in chosen
        if any(c["module_type_id"] == m.get("module_type_id") for m in modules)
    ]

    return {
        "request": request,
        "selected_modules": modules,
        "approved_case_pool_count": len(cases),
        "source_cases": chosen,
        "coverage": {
            "source_case_count": len(chosen),
            "same_module_case_count": len(same_module_cases),
            "component_count": len(components),
            "missing_required_count": len(missing),
            "uses_only_approved_ifc_links": True,
        },
        "total": {
            "confirmed_amount": 0,
            "estimated_amount": total,
            "display_total": total,
            "missing_amount": None,
            "currency": "KRW",
        },
        "cost_type_summary": cost_type_summary(components),
        "components": components,
        "missing": missing,
        "warnings": [
            "Only approved IFC-Notion-project_module links are used.",
            "Material-level pricing is not used until actual_costs are linked to material_id/quantity/unit_price.",
            "Site/foundation/transport conditions remain separate inputs and should not be inferred from missing BIM data.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an estimate from approved IFC/Notion evidence only.")
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()

    estimate = build_estimate(load_request(args.request))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(estimate, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "estimated_amount": estimate["total"]["estimated_amount"],
        "source_case_count": estimate["coverage"]["source_case_count"],
        "same_module_case_count": estimate["coverage"]["same_module_case_count"],
        "component_count": estimate["coverage"]["component_count"],
        "missing_required_count": estimate["coverage"]["missing_required_count"],
    }, ensure_ascii=False, indent=2))
    print(str(args.out))


if __name__ == "__main__":
    main()
