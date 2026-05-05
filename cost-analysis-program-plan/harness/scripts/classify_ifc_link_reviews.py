from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
ALIGNMENT_REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_notion_alignment_report.json"
OVERLAP_REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_notion_workcode_overlap_report.json"
OUT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_link_review_classification.json"


def load_reports() -> tuple[dict, dict]:
    alignment = json.loads(ALIGNMENT_REPORT.read_text(encoding="utf-8"))
    overlap = json.loads(OVERLAP_REPORT.read_text(encoding="utf-8"))
    return alignment, overlap


def classify_record(alignment: dict, overlap: dict) -> dict:
    issues = set(alignment.get("issues", []))
    warnings = set(alignment.get("warnings", []))
    project_code = alignment["project"]["project_code"]
    overlap_ratio = overlap.get("normalized_workcode_overlap_ratio", 0)
    amount_coverage = overlap.get("actual_amount_coverage_by_matched_bim_workcodes", 0)

    if "ifc_file_path_not_found_in_local_ifc_dir" in issues:
        status = "needs_source_file"
        reason = "local IFC file is missing or only fuzzy matched"
    elif "ifc_module_type_differs_from_project_module_type" in issues:
        status = "needs_module_confirmation"
        reason = "IFC module differs from project module"
    elif "linked_project_has_no_notion_actual_costs" in warnings:
        status = "rejected"
        reason = "linked project has no Notion actual costs"
    elif "project_created_from_ifc_fallback_code" in warnings:
        status = "needs_project_confirmation"
        reason = "project was created from IFC fallback code"
    elif "linked_project_has_no_project_modules_row" in warnings:
        status = "needs_module_confirmation"
        reason = "linked project has no project_modules row"
    elif amount_coverage >= 0.70 and overlap_ratio >= 0.30:
        status = "approved"
        reason = "local file exists, module link exists, actual costs exist, and work-code coverage is acceptable"
    else:
        status = "needs_workcode_review"
        reason = "BIM/Notion work-code coverage is low"

    return {
        "ifc_file_id": alignment["ifc_file_id"],
        "file_name": alignment["file_name"],
        "project_code": project_code,
        "approved_project_code": project_code if status == "approved" else "",
        "current_module_code": alignment["ifc_module"]["module_code"],
        "approved_module_code": alignment["ifc_module"]["module_code"] if status == "approved" else "",
        "classification": status,
        "reason": reason,
        "amount_coverage": amount_coverage,
        "overlap_ratio": overlap_ratio,
        "alignment_status": alignment["status"],
        "issues": sorted(issues),
        "warnings": sorted(warnings),
    }


def apply_classifications(classifications: list[dict]) -> None:
    con = sqlite3.connect(DB)
    now = datetime.now().isoformat(timespec="seconds")
    try:
        for item in classifications:
            con.execute(
                """
                UPDATE ifc_project_link_reviews
                   SET approval_status = ?,
                       approved_project_code = ?,
                       approved_module_code = ?,
                       reviewer = COALESCE(NULLIF(reviewer, ''), 'harness'),
                       notes = ?,
                       reviewed_at = ?
                 WHERE ifc_file_id = ?
                   AND approval_status = 'pending'
                """,
                (
                    item["classification"],
                    item["approved_project_code"],
                    item["approved_module_code"],
                    item["reason"],
                    now,
                    item["ifc_file_id"],
                ),
            )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    alignment, overlap = load_reports()
    overlap_by_ifc = {r["ifc_file_id"]: r for r in overlap["records"]}
    classifications = [
        classify_record(rec, overlap_by_ifc.get(rec["ifc_file_id"], {}))
        for rec in alignment["records"]
    ]
    apply_classifications(classifications)
    summary: dict[str, int] = {}
    for item in classifications:
        summary[item["classification"]] = summary.get(item["classification"], 0) + 1
    output = {"summary": summary, "classifications": classifications}
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(str(OUT))


if __name__ == "__main__":
    main()
