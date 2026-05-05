from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "partial_ifc_workcode_candidates.json"

MIN_ACTUAL_AMOUNT = 1_000_000
MIN_BIM_ROWS = 1


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def workcode_maps(con: sqlite3.Connection) -> dict[int, dict]:
    rows = [dict(r) for r in con.execute(
        """
        SELECT work_code_id, work_code, parent_code_id, level, category, work_name_ko
        FROM work_codes
        """
    ).fetchall()]
    by_id = {row["work_code_id"]: row for row in rows}
    cache: dict[int, dict] = {}

    def normalized(row_id: int) -> dict:
        if row_id in cache:
            return cache[row_id]
        cur = by_id[row_id]
        while cur["level"] > 2 and cur.get("parent_code_id") and by_id.get(cur["parent_code_id"]):
            cur = by_id[cur["parent_code_id"]]
        cache[row_id] = cur
        return cur

    return {
        row_id: {
            **row,
            "normalized_work_code": normalized(row_id)["work_code"],
            "normalized_work_name": normalized(row_id)["work_name_ko"],
        }
        for row_id, row in by_id.items()
    }


def unapproved_ifc_records(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """
        SELECT f.ifc_file_id, f.file_path, f.project_id, f.module_type_id,
               p.project_code, p.project_name,
               mt.module_code, mt.module_name, mt.floor_area_m2, mt.pyeong,
               r.approval_status, r.notes
        FROM ifc_project_link_reviews r
        JOIN ifc_files f ON r.ifc_file_id = f.ifc_file_id
        LEFT JOIN projects p ON f.project_id = p.project_id
        LEFT JOIN module_types mt ON f.module_type_id = mt.module_type_id
        WHERE r.approval_status != 'approved'
        ORDER BY r.approval_status, p.project_code, f.ifc_file_id
        """
    ).fetchall()]


def aggregate_bim(con: sqlite3.Connection, ifc_file_id: int, maps: dict[int, dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for row in con.execute(
        """
        SELECT work_code_id, unit, SUM(quantity) quantity, COUNT(*) rows
        FROM bim_quantities
        WHERE ifc_file_id = ?
        GROUP BY work_code_id, unit
        """,
        (ifc_file_id,),
    ):
        m = maps[row["work_code_id"]]
        nwc = m["normalized_work_code"]
        unit = row["unit"]
        key = (nwc, unit)
        item = out.setdefault(key, {
            "work_code": nwc,
            "bim_unit": unit,
            "work_name": m["normalized_work_name"],
            "category": m["category"],
            "bim_quantity": 0.0,
            "bim_rows": 0,
            "raw_bim_work_codes": set(),
        })
        item["bim_quantity"] += float(row["quantity"] or 0)
        item["bim_rows"] += int(row["rows"] or 0)
        item["raw_bim_work_codes"].add(m["work_code"])
    return out


def aggregate_actual(con: sqlite3.Connection, project_id: int | None, maps: dict[int, dict]) -> dict[str, dict]:
    if not project_id:
        return {}
    out: dict[str, dict] = {}
    for row in con.execute(
        """
        SELECT work_code_id, source_ref, SUM(total_amount) amount, COUNT(*) rows
        FROM actual_costs
        WHERE project_id = ?
        GROUP BY work_code_id, source_ref
        """,
        (project_id,),
    ):
        m = maps[row["work_code_id"]]
        key = m["normalized_work_code"]
        item = out.setdefault(key, {
            "work_code": key,
            "work_name": m["normalized_work_name"],
            "category": m["category"],
            "actual_amount": 0,
            "actual_rows": 0,
            "cost_types": {},
            "raw_actual_work_codes": set(),
        })
        amount = int(row["amount"] or 0)
        item["actual_amount"] += amount
        item["actual_rows"] += int(row["rows"] or 0)
        item["cost_types"][row["source_ref"] or "unknown"] = item["cost_types"].get(row["source_ref"] or "unknown", 0) + amount
        item["raw_actual_work_codes"].add(m["work_code"])
    return out


def serial(item: dict) -> dict:
    out = dict(item)
    for key in ["raw_bim_work_codes", "raw_actual_work_codes"]:
        if isinstance(out.get(key), set):
            out[key] = sorted(out[key])
    return out


def candidate_decision(record: dict, merged: dict) -> tuple[str, str]:
    status = record["approval_status"]
    work = merged["work_code"]
    if status == "needs_source_file":
        return "blocked", "source IFC file is not verified"
    if status == "needs_module_confirmation" and work.startswith("SITE"):
        return "blocked", "site cost should not be inferred from unconfirmed module link"
    if merged["bim_rows"] < MIN_BIM_ROWS:
        return "blocked", "no BIM quantity"
    if merged.get("is_mixed_units"):
        return "needs_unit_review", f"BIM units mixed for this work code: {', '.join(merged['all_units'])}"
    if merged["actual_amount"] < MIN_ACTUAL_AMOUNT:
        return "blocked", "actual amount too small for evidence"
    if work.startswith("SITE") or work.startswith("EXT-ROOF") or work.startswith("MEP-PLMB"):
        return "review", "usable only as separate non-BIM/site or specialty cost evidence"
    return "candidate", "BIM and Notion actual cost both exist for this normalized work code"


def build_report() -> dict:
    con = connect()
    maps = workcode_maps(con)
    records = []
    summary = {"candidate": 0, "review": 0, "blocked": 0, "needs_unit_review": 0}

    for rec in unapproved_ifc_records(con):
        bim = aggregate_bim(con, rec["ifc_file_id"], maps)  # key=(work_code, unit)
        actual = aggregate_actual(con, rec["project_id"], maps)  # key=work_code

        units_per_work: dict[str, set] = {}
        for (wc, unit) in bim.keys():
            units_per_work.setdefault(wc, set()).add(unit)

        rows = []
        merged_keys = set(bim.keys()) | {(wc, None) for wc in actual.keys() if wc not in units_per_work}
        for key in sorted(merged_keys, key=lambda x: (x[0], x[1] or "")):
            wc, unit = key
            bim_item = bim.get(key, {})
            actual_item = actual.get(wc, {})
            all_units = sorted(units_per_work.get(wc, set()), key=lambda u: (u or ""))
            is_mixed = len(all_units) > 1

            biggest_unit = (
                max(all_units, key=lambda u: bim.get((wc, u), {}).get("bim_quantity", 0))
                if all_units else None
            )
            actual_share = actual_item.get("actual_amount", 0) if (not is_mixed or unit == biggest_unit) else 0
            actual_rows_share = actual_item.get("actual_rows", 0) if (not is_mixed or unit == biggest_unit) else 0
            cost_types_share = actual_item.get("cost_types", {}) if (not is_mixed or unit == biggest_unit) else {}

            merged = {
                "work_code": wc,
                "bim_unit": unit,
                "work_name": (bim_item or actual_item or {}).get("work_name"),
                "category": (bim_item or actual_item or {}).get("category"),
                "bim_quantity": bim_item.get("bim_quantity", 0),
                "bim_rows": bim_item.get("bim_rows", 0),
                "actual_amount": actual_share,
                "actual_amount_at_workcode_total": actual_item.get("actual_amount", 0),
                "actual_rows": actual_rows_share,
                "cost_types": cost_types_share,
                "raw_bim_work_codes": bim_item.get("raw_bim_work_codes", set()),
                "raw_actual_work_codes": actual_item.get("raw_actual_work_codes", set()),
                "is_mixed_units": is_mixed,
                "all_units": all_units,
            }
            decision, reason = candidate_decision(rec, merged)
            merged["partial_use_status"] = decision
            merged["partial_use_reason"] = reason
            if decision not in ("blocked", "needs_unit_review"):
                if merged["bim_quantity"]:
                    merged["actual_amount_per_bim_quantity"] = round(merged["actual_amount"] / merged["bim_quantity"], 2)
                else:
                    merged["actual_amount_per_bim_quantity"] = None
            else:
                merged["actual_amount_per_bim_quantity"] = None
            summary[decision] = summary.get(decision, 0) + 1
            rows.append(serial(merged))

        usable = [r for r in rows if r["partial_use_status"] in {"candidate", "review", "needs_unit_review"}]
        records.append({
            "ifc_file_id": rec["ifc_file_id"],
            "file_name": Path(rec["file_path"] or "").name,
            "project_code": rec["project_code"],
            "project_name": rec["project_name"],
            "module_code": rec["module_code"],
            "approval_status": rec["approval_status"],
            "review_note": rec["notes"],
            "usable_workcode_count": len(usable),
            "usable_actual_amount": sum(r["actual_amount"] for r in usable),
            "usable_workcodes": sorted(usable, key=lambda x: x["actual_amount"], reverse=True),
            "blocked_top": sorted(
                [r for r in rows if r["partial_use_status"] == "blocked"],
                key=lambda x: x["actual_amount"],
                reverse=True,
            )[:15],
        })

    return {
        "summary": {
            **summary,
            "unapproved_ifc_records": len(records),
            "ifc_with_partial_candidates": sum(1 for r in records if r["usable_workcode_count"] > 0),
            "min_actual_amount": MIN_ACTUAL_AMOUNT,
        },
        "rules": {
            "candidate": "BIM quantity and Notion actual cost exist on same normalized work code, source file is verified, and amount is material.",
            "review": "Potentially usable but should stay outside BIM quantity model or needs domain review.",
            "blocked": "Do not use for prediction/evidence until source/module/work-code issue is resolved.",
        },
        "records": records,
    }


def main() -> None:
    report = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
