from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "approved_ifc_prediction_inputs.json"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def main() -> None:
    con = connect()
    rows = con.execute(
        """
        SELECT f.ifc_file_id, f.file_path, f.file_hash, f.file_size_mb,
               p.project_id, p.project_code, p.project_name,
               mt.module_type_id, mt.module_code, mt.module_name, mt.floor_area_m2, mt.pyeong,
               r.approval_status, r.reviewed_at,
               COUNT(DISTINCT bq.bim_qty_id) AS bim_rows,
               COUNT(DISTINCT ac.actual_cost_id) AS actual_rows,
               SUM(DISTINCT ac.total_amount) AS actual_total
        FROM ifc_project_link_reviews r
        JOIN ifc_files f ON r.ifc_file_id = f.ifc_file_id
        JOIN projects p ON f.project_id = p.project_id
        JOIN module_types mt ON f.module_type_id = mt.module_type_id
        JOIN project_modules pm ON p.project_id = pm.project_id
           AND pm.module_type_id = f.module_type_id
        LEFT JOIN bim_quantities bq ON f.ifc_file_id = bq.ifc_file_id
        LEFT JOIN actual_costs ac ON p.project_id = ac.project_id
        WHERE r.approval_status = 'approved'
        GROUP BY f.ifc_file_id
        ORDER BY p.project_code
        """
    ).fetchall()
    records = [dict(r) for r in rows]
    report = {
        "summary": {
            "approved_ifc_inputs": len(records),
            "safe_for_prediction": len(records) > 0,
        },
        "records": records,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
