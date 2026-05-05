from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
SCHEMA = ROOT / "cost-analysis-program-plan" / "harness" / "sql" / "ifc_project_link_reviews_schema.sql"
TEMPLATE = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_project_link_review_template.csv"


def read_rows() -> list[dict]:
    with TEMPLATE.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    con = sqlite3.connect(DB)
    try:
        con.executescript(SCHEMA.read_text(encoding="utf-8"))
        inserted = 0
        skipped = 0
        for row in read_rows():
            exists = con.execute(
                """
                SELECT 1
                FROM ifc_project_link_reviews
                WHERE ifc_file_id = ? AND approval_status = 'pending'
                """,
                (row["ifc_file_id"],),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            con.execute(
                """
                INSERT INTO ifc_project_link_reviews(
                    ifc_file_id, db_file_name, candidate_file_name,
                    current_project_code, approved_project_code,
                    current_module_code, approved_module_code,
                    approval_status, reviewer, notes
                )
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["ifc_file_id"],
                    row["db_file_name"],
                    row["candidate_file_name"],
                    row["project_code"],
                    row["approved_project_code"],
                    row["ifc_module_code"],
                    row["approved_module_code"],
                    row["approval_status"] or "pending",
                    row["reviewer"],
                    row["notes"],
                ),
            )
            inserted += 1
        con.commit()
        print(json.dumps({"inserted": inserted, "skipped": skipped}, ensure_ascii=False, indent=2))
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
