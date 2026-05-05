from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
ALIGNMENT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_notion_alignment_report.json"
APPROVED = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "approved_ifc_prediction_inputs.json"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_cleanup_verification.json"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def main() -> None:
    con = connect()
    alignment = json.loads(ALIGNMENT.read_text(encoding="utf-8"))
    approved = json.loads(APPROVED.read_text(encoding="utf-8"))
    review_counts = {
        r["approval_status"]: r["cnt"]
        for r in con.execute(
            "SELECT approval_status, COUNT(*) cnt FROM ifc_project_link_reviews GROUP BY approval_status"
        )
    }
    approved_bad = [r for r in approved["records"] if not r["file_path"] or not Path(r["file_path"]).exists()]
    approved_without_actuals = [r for r in approved["records"] if not r["actual_rows"]]
    approved_without_bim = [r for r in approved["records"] if not r["bim_rows"]]
    approved_without_project_module = [
        dict(r) for r in con.execute(
            """
            SELECT r.ifc_file_id, p.project_code
            FROM ifc_project_link_reviews r
            JOIN ifc_files f ON r.ifc_file_id = f.ifc_file_id
            JOIN projects p ON f.project_id = p.project_id
            LEFT JOIN project_modules pm ON p.project_id = pm.project_id
             AND pm.module_type_id = f.module_type_id
            WHERE r.approval_status = 'approved'
              AND pm.project_module_id IS NULL
            """
        )
    ]

    checks = {
        "all_reviews_classified": "pending" not in review_counts,
        "approved_files_exist": not approved_bad,
        "approved_have_actuals": not approved_without_actuals,
        "approved_have_bim": not approved_without_bim,
        "approved_have_project_module": not approved_without_project_module,
        "unresolved_alignment_failures_remain": alignment["summary"]["status_counts"].get("fail", 0),
    }
    report = {
        "review_counts": review_counts,
        "approved_input_summary": approved["summary"],
        "checks": checks,
        "failures": {
            "approved_bad_file_path": approved_bad,
            "approved_without_actuals": approved_without_actuals,
            "approved_without_bim": approved_without_bim,
            "approved_without_project_module": approved_without_project_module,
        },
        "safe_to_run_prediction_on_approved_inputs": (
            checks["all_reviews_classified"]
            and checks["approved_files_exist"]
            and checks["approved_have_actuals"]
            and checks["approved_have_bim"]
            and checks["approved_have_project_module"]
            and approved["summary"]["approved_ifc_inputs"] > 0
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "review_counts": review_counts,
        "approved_inputs": approved["summary"]["approved_ifc_inputs"],
        "safe_to_run_prediction_on_approved_inputs": report["safe_to_run_prediction_on_approved_inputs"],
    }, ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
