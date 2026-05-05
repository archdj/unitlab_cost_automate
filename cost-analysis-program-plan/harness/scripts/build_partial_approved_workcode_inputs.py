from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "partial_approved_workcode_inputs.json"


def main() -> None:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        """
        SELECT p.review_id, p.ifc_file_id, p.project_code, p.module_code,
               p.normalized_work_code, p.actual_amount, p.bim_quantity,
               p.actual_amount_per_bim_quantity, p.cost_types,
               p.approval_status, p.notes, l.approval_status AS ifc_link_status
        FROM partial_ifc_workcode_reviews p
        JOIN ifc_project_link_reviews l ON p.ifc_file_id = l.ifc_file_id
        WHERE p.approval_status = 'approved_partial'
        ORDER BY p.normalized_work_code, p.project_code
        """
    ).fetchall()]
    by_work: dict[str, dict] = {}
    for row in rows:
        code = row["normalized_work_code"]
        item = by_work.setdefault(code, {
            "normalized_work_code": code,
            "count": 0,
            "actual_amount": 0,
            "bim_quantity": 0.0,
            "records": [],
        })
        item["count"] += 1
        item["actual_amount"] += int(row["actual_amount"] or 0)
        item["bim_quantity"] += float(row["bim_quantity"] or 0)
        row["cost_types"] = json.loads(row["cost_types"] or "{}")
        item["records"].append(row)
    for item in by_work.values():
        item["weighted_amount_per_bim_quantity"] = (
            round(item["actual_amount"] / item["bim_quantity"], 2)
            if item["bim_quantity"] else None
        )
    report = {
        "summary": {
            "approved_partial_rows": len(rows),
            "workcode_count": len(by_work),
            "total_actual_amount": sum(int(r["actual_amount"] or 0) for r in rows),
        },
        "by_workcode": sorted(by_work.values(), key=lambda x: x["actual_amount"], reverse=True),
        "records": rows,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
