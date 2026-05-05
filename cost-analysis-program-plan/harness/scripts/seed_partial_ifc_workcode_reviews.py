from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
SCHEMA = ROOT / "cost-analysis-program-plan" / "harness" / "sql" / "partial_ifc_workcode_reviews_schema.sql"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "partial_ifc_workcode_candidates.json"


def main() -> None:
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    inserted = 0
    skipped = 0
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        for rec in data["records"]:
            for item in rec["usable_workcodes"]:
                exists = con.execute(
                    """
                    SELECT 1
                    FROM partial_ifc_workcode_reviews
                    WHERE ifc_file_id = ?
                      AND normalized_work_code = ?
                      AND IFNULL(bim_unit,'') = IFNULL(?, '')
                      AND approval_status = 'pending'
                    """,
                    (rec["ifc_file_id"], item["work_code"], item.get("bim_unit")),
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                con.execute(
                    """
                    INSERT INTO partial_ifc_workcode_reviews(
                        ifc_file_id, project_code, module_code, normalized_work_code,
                        bim_unit, partial_use_status, approval_status,
                        actual_amount, bim_quantity, actual_amount_per_bim_quantity,
                        cost_types, reason
                    )
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        rec["ifc_file_id"],
                        rec["project_code"],
                        rec["module_code"],
                        item["work_code"],
                        item.get("bim_unit"),
                        item["partial_use_status"],
                        "pending",
                        item["actual_amount"],
                        item["bim_quantity"],
                        item.get("actual_amount_per_bim_quantity"),
                        json.dumps(item.get("cost_types", {}), ensure_ascii=False),
                        item["partial_use_reason"],
                    ),
                )
                inserted += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(json.dumps({"inserted": inserted, "skipped": skipped}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
