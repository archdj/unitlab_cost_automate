from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "verified_evidence_dataset.json"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def main() -> None:
    con = connect()
    rows = con.execute(
        """
        SELECT f.ifc_file_id, p.project_code, p.project_name,
               mt.module_code, mt.module_name, mt.floor_area_m2, mt.pyeong,
               wc.category, wc.work_code, wc.work_name_ko,
               ac.source_ref AS cost_type,
               SUM(ac.total_amount) AS actual_amount,
               COUNT(ac.actual_cost_id) AS actual_rows,
               (
                   SELECT SUM(bq.quantity)
                   FROM bim_quantities bq
                   JOIN work_codes bwc ON bq.work_code_id = bwc.work_code_id
                   WHERE bq.ifc_file_id = f.ifc_file_id
                     AND (
                         bwc.work_code = wc.work_code
                         OR bwc.work_code LIKE wc.work_code || '-%'
                         OR wc.work_code LIKE bwc.work_code || '-%'
                     )
               ) AS related_bim_quantity
        FROM ifc_project_link_reviews r
        JOIN ifc_files f ON r.ifc_file_id = f.ifc_file_id
        JOIN projects p ON f.project_id = p.project_id
        JOIN module_types mt ON f.module_type_id = mt.module_type_id
        JOIN project_modules pm ON p.project_id = pm.project_id
           AND pm.module_type_id = f.module_type_id
        JOIN actual_costs ac ON p.project_id = ac.project_id
        JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
        WHERE r.approval_status = 'approved'
        GROUP BY f.ifc_file_id, wc.work_code_id, ac.source_ref
        ORDER BY p.project_code, actual_amount DESC
        """
    ).fetchall()

    records = []
    for row in rows:
        item = dict(row)
        area = item["floor_area_m2"] or 0
        item["actual_amount_per_m2"] = round(item["actual_amount"] / area) if area else None
        if item["related_bim_quantity"]:
            item["actual_amount_per_bim_quantity"] = round(item["actual_amount"] / item["related_bim_quantity"], 2)
        else:
            item["actual_amount_per_bim_quantity"] = None
        item["evidence_status"] = "verified_ifc_notion_project_module"
        records.append(item)

    projects = sorted({r["project_code"] for r in records})
    report = {
        "summary": {
            "verified_projects": len(projects),
            "verified_project_codes": projects,
            "rows": len(records),
        },
        "records": records,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
