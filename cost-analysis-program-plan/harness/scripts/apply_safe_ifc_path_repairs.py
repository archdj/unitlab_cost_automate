from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "unitlab-cost-analysis"
DB = REPO / "db" / "cost_analysis.db"
PLAN = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_path_repair_plan.json"


def backup_db() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DB.with_name(f"cost_analysis.before_ifc_path_repair.{stamp}.db")
    shutil.copy2(DB, backup)
    return backup


def safe_items() -> list[dict]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    return [
        item for item in plan
        if item["proposed_action"] == "update_path_and_hash"
        and not item["requires_review"]
        and item["candidate_file_path"]
        and item["candidate_sha256"]
    ]


def apply(apply_changes: bool) -> dict:
    items = safe_items()
    result = {
        "mode": "apply" if apply_changes else "dry_run",
        "safe_update_count": len(items),
        "updated": [],
        "backup_path": None,
    }
    if not apply_changes:
        result["updated"] = [
            {
                "ifc_file_id": item["ifc_file_id"],
                "project_code": item["project_code"],
                "new_file_path": item["candidate_file_path"],
                "new_file_hash": item["candidate_sha256"],
            }
            for item in items
        ]
        return result

    backup = backup_db()
    result["backup_path"] = str(backup)
    con = sqlite3.connect(DB)
    try:
        for item in items:
            size_mb = Path(item["candidate_file_path"]).stat().st_size / (1024 * 1024)
            con.execute(
                """
                UPDATE ifc_files
                   SET file_path = ?,
                       file_hash = ?,
                       file_size_mb = ?
                 WHERE ifc_file_id = ?
                """,
                (
                    item["candidate_file_path"],
                    item["candidate_sha256"],
                    round(size_mb, 4),
                    item["ifc_file_id"],
                ),
            )
            result["updated"].append({
                "ifc_file_id": item["ifc_file_id"],
                "project_code": item["project_code"],
                "new_file_path": item["candidate_file_path"],
                "new_file_hash": item["candidate_sha256"],
            })
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply safe IFC path/hash repairs.")
    parser.add_argument("--apply", action="store_true", help="write DB updates; default is dry-run")
    args = parser.parse_args()
    print(json.dumps(apply(args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
