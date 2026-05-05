from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_notion_workcode_overlap_report.json"


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
    by_id = {r["work_code_id"]: r for r in rows}
    cache: dict[int, dict] = {}

    def top(row_id: int) -> dict:
        if row_id in cache:
            return cache[row_id]
        cur = by_id[row_id]
        while cur["level"] > 2 and cur.get("parent_code_id") and by_id.get(cur["parent_code_id"]):
            cur = by_id[cur["parent_code_id"]]
        cache[row_id] = cur
        return cur

    out = {}
    for row_id, row in by_id.items():
        parent = top(row_id)
        out[row_id] = {
            **row,
            "normalized_work_code_id": parent["work_code_id"],
            "normalized_work_code": parent["work_code"],
            "normalized_work_name": parent["work_name_ko"],
        }
    return out


def ifc_records(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """
        SELECT f.ifc_file_id, f.file_path, f.project_id, p.project_code, p.project_name
        FROM ifc_files f
        LEFT JOIN projects p ON f.project_id = p.project_id
        ORDER BY f.ifc_file_id
        """
    ).fetchall()]


def aggregate_bim(con: sqlite3.Connection, ifc_file_id: int, maps: dict[int, dict]) -> dict[str, dict]:
    rows = con.execute(
        """
        SELECT work_code_id, SUM(quantity) AS quantity, COUNT(*) AS row_count
        FROM bim_quantities
        WHERE ifc_file_id = ?
        GROUP BY work_code_id
        """,
        (ifc_file_id,),
    ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        m = maps[row["work_code_id"]]
        key = m["normalized_work_code"]
        item = out.setdefault(key, {
            "work_code": key,
            "work_name": m["normalized_work_name"],
            "bim_quantity": 0.0,
            "bim_rows": 0,
            "raw_bim_work_codes": set(),
        })
        item["bim_quantity"] += float(row["quantity"] or 0)
        item["bim_rows"] += int(row["row_count"] or 0)
        item["raw_bim_work_codes"].add(m["work_code"])
    return out


def aggregate_actual(con: sqlite3.Connection, project_id: int | None, maps: dict[int, dict]) -> dict[str, dict]:
    if not project_id:
        return {}
    rows = con.execute(
        """
        SELECT work_code_id, SUM(total_amount) AS amount, COUNT(*) AS row_count
        FROM actual_costs
        WHERE project_id = ?
        GROUP BY work_code_id
        """,
        (project_id,),
    ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        m = maps[row["work_code_id"]]
        key = m["normalized_work_code"]
        item = out.setdefault(key, {
            "work_code": key,
            "work_name": m["normalized_work_name"],
            "actual_amount": 0,
            "actual_rows": 0,
            "raw_actual_work_codes": set(),
        })
        item["actual_amount"] += int(row["amount"] or 0)
        item["actual_rows"] += int(row["row_count"] or 0)
        item["raw_actual_work_codes"].add(m["work_code"])
    return out


def serialize_sets(item: dict) -> dict:
    out = dict(item)
    for key in ["raw_bim_work_codes", "raw_actual_work_codes"]:
        if key in out and isinstance(out[key], set):
            out[key] = sorted(out[key])
    return out


def build_report() -> dict:
    con = connect()
    maps = workcode_maps(con)
    records = []
    for rec in ifc_records(con):
        bim = aggregate_bim(con, rec["ifc_file_id"], maps)
        actual = aggregate_actual(con, rec["project_id"], maps)
        keys = sorted(set(bim) | set(actual))
        rows = []
        for key in keys:
            merged = {
                "work_code": key,
                "work_name": (bim.get(key) or actual.get(key) or {}).get("work_name"),
                "bim_quantity": bim.get(key, {}).get("bim_quantity", 0),
                "bim_rows": bim.get(key, {}).get("bim_rows", 0),
                "actual_amount": actual.get(key, {}).get("actual_amount", 0),
                "actual_rows": actual.get(key, {}).get("actual_rows", 0),
                "raw_bim_work_codes": bim.get(key, {}).get("raw_bim_work_codes", set()),
                "raw_actual_work_codes": actual.get(key, {}).get("raw_actual_work_codes", set()),
            }
            if merged["bim_rows"] and merged["actual_rows"]:
                merged["status"] = "matched"
            elif merged["bim_rows"]:
                merged["status"] = "bim_only"
            else:
                merged["status"] = "actual_only"
            rows.append(serialize_sets(merged))

        matched = [r for r in rows if r["status"] == "matched"]
        bim_keys = {k for k, v in bim.items() if v["bim_rows"] > 0}
        actual_keys = {k for k, v in actual.items() if v["actual_rows"] > 0}
        union = bim_keys | actual_keys
        overlap_ratio = len(bim_keys & actual_keys) / len(union) if union else 0
        actual_amount_total = sum(v["actual_amount"] for v in actual.values())
        matched_actual_total = sum(r["actual_amount"] for r in matched)
        amount_coverage = matched_actual_total / actual_amount_total if actual_amount_total else 0

        records.append({
            "ifc_file_id": rec["ifc_file_id"],
            "file_name": Path(rec["file_path"] or "").name,
            "project_code": rec["project_code"],
            "project_name": rec["project_name"],
            "normalized_workcode_overlap_ratio": round(overlap_ratio, 3),
            "actual_amount_coverage_by_matched_bim_workcodes": round(amount_coverage, 3),
            "counts": {
                "bim_workcodes": len(bim_keys),
                "actual_workcodes": len(actual_keys),
                "matched_workcodes": len(bim_keys & actual_keys),
                "bim_only_workcodes": len(bim_keys - actual_keys),
                "actual_only_workcodes": len(actual_keys - bim_keys),
            },
            "top_actual_only": sorted(
                [r for r in rows if r["status"] == "actual_only"],
                key=lambda x: x["actual_amount"],
                reverse=True,
            )[:15],
            "top_bim_only": sorted(
                [r for r in rows if r["status"] == "bim_only"],
                key=lambda x: x["bim_quantity"],
                reverse=True,
            )[:15],
            "matched": sorted(matched, key=lambda x: x["actual_amount"], reverse=True)[:20],
        })

    summary = {
        "ifc_records": len(records),
        "average_normalized_overlap": round(
            sum(r["normalized_workcode_overlap_ratio"] for r in records) / len(records), 3
        ) if records else 0,
        "average_actual_amount_coverage": round(
            sum(r["actual_amount_coverage_by_matched_bim_workcodes"] for r in records) / len(records), 3
        ) if records else 0,
    }
    return {"summary": summary, "records": records}


def main() -> None:
    report = build_report()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
