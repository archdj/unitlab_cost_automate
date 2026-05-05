from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "unitlab-cost-analysis"
DB = REPO / "db" / "cost_analysis.db"
IFC_DIR = REPO / "ifc"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "ifc_notion_alignment_report.json"


KNOWN_BAD_PREFIXES = ("N-IFC-",)
MIN_TOKEN_OVERLAP = 0.25


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    text = Path(text).stem if "\\" in text or "/" in text else text
    raw = re.findall(r"[0-9A-Za-z가-힣]+", text.lower())
    stop = {"ifc", "주택", "근생", "수정", "심의", "recovery", "template", "unit", "lab"}
    return {t for t in raw if len(t) >= 2 and t not in stop}


def token_overlap(a: str | None, b: str | None) -> float:
    ta = tokens(a)
    tb = tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def local_ifc_map() -> dict[str, Path]:
    return {p.name: p for p in IFC_DIR.glob("*.ifc")}


def classify_status(issues: list[str], warnings: list[str]) -> str:
    if issues:
        return "fail"
    if warnings:
        return "review"
    return "pass"


def fetch_ifc_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        """
        SELECT f.ifc_file_id, f.file_path, f.file_hash, f.module_type_id AS ifc_module_type_id,
               f.project_id, f.parsed_at,
               p.project_code, p.project_name,
               mt.module_code AS ifc_module_code, mt.module_name AS ifc_module_name,
               mt.floor_area_m2 AS ifc_module_area, mt.pyeong AS ifc_module_pyeong,
               pm.module_type_id AS project_module_type_id,
               pmt.module_code AS project_module_code,
               pmt.floor_area_m2 AS project_module_area,
               COUNT(bq.bim_qty_id) AS bim_rows,
               SUM(bq.quantity) AS bim_quantity_sum,
               COUNT(DISTINCT ac.actual_cost_id) AS actual_rows,
               SUM(DISTINCT ac.total_amount) AS actual_total
        FROM ifc_files f
        LEFT JOIN projects p ON f.project_id = p.project_id
        LEFT JOIN module_types mt ON f.module_type_id = mt.module_type_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types pmt ON pm.module_type_id = pmt.module_type_id
        LEFT JOIN bim_quantities bq ON f.ifc_file_id = bq.ifc_file_id
        LEFT JOIN actual_costs ac ON p.project_id = ac.project_id
        GROUP BY f.ifc_file_id, pm.project_module_id
        ORDER BY p.project_code, f.ifc_file_id
        """
    ).fetchall()


def workcode_alignment(con: sqlite3.Connection, ifc_file_id: int, project_id: int | None) -> list[dict]:
    if not project_id:
        return []
    rows = con.execute(
        """
        WITH bim AS (
            SELECT wc.work_code, wc.work_name_ko, SUM(bq.quantity) AS bim_qty, COUNT(*) AS bim_rows
            FROM bim_quantities bq
            JOIN work_codes wc ON bq.work_code_id = wc.work_code_id
            WHERE bq.ifc_file_id = ?
            GROUP BY wc.work_code_id
        ),
        actual AS (
            SELECT wc.work_code, SUM(ac.total_amount) AS actual_amount, COUNT(*) AS actual_rows
            FROM actual_costs ac
            JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
            WHERE ac.project_id = ?
            GROUP BY wc.work_code_id
        )
        SELECT COALESCE(bim.work_code, actual.work_code) AS work_code,
               COALESCE(bim.work_name_ko, '') AS work_name_ko,
               COALESCE(bim.bim_qty, 0) AS bim_qty,
               COALESCE(bim.bim_rows, 0) AS bim_rows,
               COALESCE(actual.actual_amount, 0) AS actual_amount,
               COALESCE(actual.actual_rows, 0) AS actual_rows
        FROM bim
        FULL OUTER JOIN actual ON bim.work_code = actual.work_code
        ORDER BY actual_amount DESC, bim_qty DESC
        """,
        (ifc_file_id, project_id),
    ).fetchall()
    return [dict(r) for r in rows]


def workcode_alignment_sqlite(con: sqlite3.Connection, ifc_file_id: int, project_id: int | None) -> list[dict]:
    if not project_id:
        return []
    rows = con.execute(
        """
        WITH bim AS (
            SELECT wc.work_code, wc.work_name_ko, SUM(bq.quantity) AS bim_qty, COUNT(*) AS bim_rows
            FROM bim_quantities bq
            JOIN work_codes wc ON bq.work_code_id = wc.work_code_id
            WHERE bq.ifc_file_id = ?
            GROUP BY wc.work_code_id
        ),
        actual AS (
            SELECT wc.work_code, wc.work_name_ko, SUM(ac.total_amount) AS actual_amount, COUNT(*) AS actual_rows
            FROM actual_costs ac
            JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
            WHERE ac.project_id = ?
            GROUP BY wc.work_code_id
        ),
        keys AS (
            SELECT work_code FROM bim
            UNION
            SELECT work_code FROM actual
        )
        SELECT k.work_code,
               COALESCE(bim.work_name_ko, actual.work_name_ko, '') AS work_name_ko,
               COALESCE(bim.bim_qty, 0) AS bim_qty,
               COALESCE(bim.bim_rows, 0) AS bim_rows,
               COALESCE(actual.actual_amount, 0) AS actual_amount,
               COALESCE(actual.actual_rows, 0) AS actual_rows
        FROM keys k
        LEFT JOIN bim ON k.work_code = bim.work_code
        LEFT JOIN actual ON k.work_code = actual.work_code
        ORDER BY actual_amount DESC, bim_qty DESC
        """,
        (ifc_file_id, project_id),
    ).fetchall()
    return [dict(r) for r in rows]


def validate() -> dict:
    con = connect()
    local_files = local_ifc_map()
    records = []
    rows = fetch_ifc_rows(con)

    seen_ifc_ids: set[int] = set()
    for r in rows:
        if r["ifc_file_id"] in seen_ifc_ids:
            continue
        seen_ifc_ids.add(r["ifc_file_id"])

        issues: list[str] = []
        warnings: list[str] = []
        file_name = Path(r["file_path"] or "").name
        local_path = local_files.get(file_name)

        if not r["project_id"]:
            issues.append("ifc_has_no_project_id")
        if not r["project_code"]:
            issues.append("ifc_project_missing")
        if r["project_code"] and any(str(r["project_code"]).startswith(p) for p in KNOWN_BAD_PREFIXES):
            warnings.append("project_created_from_ifc_fallback_code")
        if not local_path:
            issues.append("ifc_file_path_not_found_in_local_ifc_dir")
        if r["file_path"] and str(r["file_path"]).lower().startswith("c:\\users\\ehwns\\"):
            warnings.append("ifc_file_path_points_to_previous_machine")
        if not r["file_hash"]:
            warnings.append("missing_file_hash")
        if not r["bim_rows"]:
            issues.append("ifc_has_no_bim_quantities")
        if not r["actual_rows"]:
            warnings.append("linked_project_has_no_notion_actual_costs")
        if not r["project_module_type_id"]:
            warnings.append("linked_project_has_no_project_modules_row")
        if r["project_module_type_id"] and r["ifc_module_type_id"] != r["project_module_type_id"]:
            issues.append("ifc_module_type_differs_from_project_module_type")

        overlap = token_overlap(file_name, r["project_name"])
        if overlap < MIN_TOKEN_OVERLAP and not str(r["project_code"] or "").startswith("N-IFC-"):
            warnings.append("ifc_filename_project_name_low_token_overlap")

        workcodes = workcode_alignment_sqlite(con, r["ifc_file_id"], r["project_id"])
        bim_workcodes = {w["work_code"] for w in workcodes if w["bim_rows"] > 0}
        actual_workcodes = {w["work_code"] for w in workcodes if w["actual_rows"] > 0}
        if r["actual_rows"] and r["bim_rows"]:
            common = bim_workcodes & actual_workcodes
            coverage = len(common) / len(bim_workcodes | actual_workcodes) if (bim_workcodes | actual_workcodes) else 0
            if coverage < 0.25:
                warnings.append("low_workcode_overlap_between_bim_and_notion_actuals")
        else:
            coverage = 0

        records.append({
            "ifc_file_id": r["ifc_file_id"],
            "file_name": file_name,
            "db_file_path": r["file_path"],
            "local_file_exists": bool(local_path),
            "local_file_path": str(local_path) if local_path else None,
            "file_hash": r["file_hash"],
            "project": {
                "project_id": r["project_id"],
                "project_code": r["project_code"],
                "project_name": r["project_name"],
            },
            "ifc_module": {
                "module_type_id": r["ifc_module_type_id"],
                "module_code": r["ifc_module_code"],
                "module_name": r["ifc_module_name"],
                "floor_area_m2": r["ifc_module_area"],
                "pyeong": r["ifc_module_pyeong"],
            },
            "project_module": {
                "module_type_id": r["project_module_type_id"],
                "module_code": r["project_module_code"],
                "floor_area_m2": r["project_module_area"],
            },
            "counts": {
                "bim_rows": r["bim_rows"],
                "bim_quantity_sum": r["bim_quantity_sum"],
                "actual_rows": r["actual_rows"],
                "actual_total": r["actual_total"],
                "bim_workcode_count": len(bim_workcodes),
                "actual_workcode_count": len(actual_workcodes),
                "workcode_overlap_ratio": round(coverage, 3),
            },
            "name_token_overlap": round(overlap, 3),
            "top_workcode_alignment": workcodes[:20],
            "issues": issues,
            "warnings": warnings,
            "status": classify_status(issues, warnings),
        })

    status_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    for rec in records:
        status_counts[rec["status"]] = status_counts.get(rec["status"], 0) + 1
        for issue in rec["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        for warning in rec["warnings"]:
            warning_counts[warning] = warning_counts.get(warning, 0) + 1

    return {
        "summary": {
            "ifc_records": len(records),
            "local_ifc_files": len(local_files),
            "status_counts": status_counts,
            "issue_counts": dict(sorted(issue_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "safe_to_use_for_prediction": status_counts.get("fail", 0) == 0,
        },
        "validation_rules": {
            "fail": [
                "missing project link",
                "missing local IFC file",
                "missing BIM quantities",
                "IFC module differs from project module",
            ],
            "review": [
                "path points to previous machine",
                "missing file hash",
                "project created from fallback N-IFC code",
                "project has no actual costs",
                "project has no project_modules row",
                "low filename/project token overlap",
                "low BIM/Notion work-code overlap",
            ],
        },
        "records": records,
    }


def main() -> None:
    report = validate()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(REPORT))
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
