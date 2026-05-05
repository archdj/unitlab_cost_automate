from __future__ import annotations

import csv
import difflib
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "unitlab-cost-analysis"
DB = REPO / "db" / "cost_analysis.db"
IFC_DIR = REPO / "ifc"
OUT_DIR = ROOT / "cost-analysis-program-plan" / "harness" / "reports"
SQL_DIR = ROOT / "cost-analysis-program-plan" / "harness" / "sql"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def local_ifc_files() -> list[dict]:
    files = []
    for path in sorted(IFC_DIR.glob("*.ifc")):
        files.append({
            "name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    return files


def fetch_ifc_records(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """
        SELECT f.ifc_file_id, f.file_path, f.file_hash, f.project_id, f.module_type_id,
               f.parsed_at,
               p.project_code, p.project_name,
               mt.module_code, mt.module_name, mt.floor_area_m2, mt.pyeong,
               COUNT(DISTINCT bq.bim_qty_id) AS bim_rows,
               COUNT(DISTINCT ac.actual_cost_id) AS actual_rows
        FROM ifc_files f
        LEFT JOIN projects p ON f.project_id = p.project_id
        LEFT JOIN module_types mt ON f.module_type_id = mt.module_type_id
        LEFT JOIN bim_quantities bq ON f.ifc_file_id = bq.ifc_file_id
        LEFT JOIN actual_costs ac ON p.project_id = ac.project_id
        GROUP BY f.ifc_file_id
        ORDER BY f.ifc_file_id
        """
    ).fetchall()]


def best_local_match(file_name: str, locals_: list[dict]) -> tuple[dict | None, float]:
    exact = [f for f in locals_ if f["name"] == file_name]
    if exact:
        return exact[0], 1.0
    names = [f["name"] for f in locals_]
    matches = difflib.get_close_matches(file_name, names, n=1, cutoff=0.0)
    if not matches:
        return None, 0.0
    name = matches[0]
    score = difflib.SequenceMatcher(None, file_name, name).ratio()
    return next(f for f in locals_ if f["name"] == name), score


def path_repair_plan(records: list[dict], locals_: list[dict]) -> list[dict]:
    plan = []
    for rec in records:
        db_name = Path(rec["file_path"] or "").name
        match, score = best_local_match(db_name, locals_)
        proposed_action = "none"
        requires_review = False
        reasons = []

        if not match:
            proposed_action = "manual_review"
            requires_review = True
            reasons.append("no_local_candidate")
        elif score == 1.0:
            if rec["file_path"] != match["path"] or rec["file_hash"] != match["sha256"]:
                proposed_action = "update_path_and_hash"
                if rec["file_hash"] and rec["file_hash"] != match["sha256"]:
                    requires_review = True
                    reasons.append("hash_mismatch")
                else:
                    reasons.append("stale_path_or_missing_hash")
        elif score >= 0.72:
            proposed_action = "review_then_update_path_and_hash"
            requires_review = True
            reasons.append("fuzzy_filename_match")
        else:
            proposed_action = "manual_review"
            requires_review = True
            reasons.append("weak_filename_match")

        plan.append({
            "ifc_file_id": rec["ifc_file_id"],
            "project_code": rec["project_code"],
            "db_file_name": db_name,
            "db_file_path": rec["file_path"],
            "db_file_hash": rec["file_hash"],
            "candidate_file_name": match["name"] if match else None,
            "candidate_file_path": match["path"] if match else None,
            "candidate_sha256": match["sha256"] if match else None,
            "match_score": round(score, 3),
            "proposed_action": proposed_action,
            "requires_review": requires_review,
            "reasons": reasons,
            "sql_preview": (
                "UPDATE ifc_files SET file_path=?, file_hash=?, file_size_mb=? WHERE ifc_file_id=?;"
                if match and proposed_action in {"update_path_and_hash", "review_then_update_path_and_hash"}
                else None
            ),
        })
    return plan


def project_module_rows(con: sqlite3.Connection) -> dict[int, list[dict]]:
    rows = con.execute(
        """
        SELECT pm.project_id, pm.project_module_id, pm.module_type_id,
               mt.module_code, mt.module_name, mt.floor_area_m2, mt.pyeong
        FROM project_modules pm
        JOIN module_types mt ON pm.module_type_id = mt.module_type_id
        """
    ).fetchall()
    out: dict[int, list[dict]] = {}
    for row in rows:
        out.setdefault(row["project_id"], []).append(dict(row))
    return out


def module_repair_plan(con: sqlite3.Connection, records: list[dict]) -> list[dict]:
    pm_by_project = project_module_rows(con)
    plan = []
    seen_project: set[int] = set()
    for rec in records:
        project_id = rec["project_id"]
        if not project_id or project_id in seen_project:
            continue
        seen_project.add(project_id)

        existing = pm_by_project.get(project_id, [])
        issues = []
        proposed_action = "none"
        sql_preview = None
        requires_review = False

        if not existing:
            if rec["actual_rows"] and rec["module_type_id"]:
                proposed_action = "insert_project_module_from_ifc_module"
                sql_preview = "INSERT INTO project_modules(project_id, module_type_id, quantity, notes) VALUES(?,?,1,?);"
                requires_review = True
                issues.append("project_has_actual_costs_and_ifc_but_no_project_module")
            else:
                proposed_action = "manual_review"
                requires_review = True
                issues.append("project_module_missing_without_enough_basis")
        else:
            if rec["module_type_id"] and all(e["module_type_id"] != rec["module_type_id"] for e in existing):
                proposed_action = "manual_review_module_conflict"
                requires_review = True
                issues.append("ifc_module_type_not_in_project_modules")

        plan.append({
            "project_id": project_id,
            "project_code": rec["project_code"],
            "project_name": rec["project_name"],
            "ifc_file_id": rec["ifc_file_id"],
            "ifc_module_type_id": rec["module_type_id"],
            "ifc_module_code": rec["module_code"],
            "ifc_module_name": rec["module_name"],
            "existing_project_modules": existing,
            "actual_rows": rec["actual_rows"],
            "bim_rows": rec["bim_rows"],
            "proposed_action": proposed_action,
            "requires_review": requires_review,
            "issues": issues,
            "sql_preview": sql_preview,
        })
    return [p for p in plan if p["proposed_action"] != "none"]


def review_template(records: list[dict], path_plan: list[dict], module_plan: list[dict]) -> list[dict]:
    path_by_id = {p["ifc_file_id"]: p for p in path_plan}
    module_by_project = {p["project_id"]: p for p in module_plan}
    rows = []
    for rec in records:
        path_item = path_by_id.get(rec["ifc_file_id"], {})
        module_item = module_by_project.get(rec["project_id"], {})
        rows.append({
            "ifc_file_id": rec["ifc_file_id"],
            "db_file_name": Path(rec["file_path"] or "").name,
            "candidate_file_name": path_item.get("candidate_file_name"),
            "project_code": rec["project_code"],
            "project_name": rec["project_name"],
            "ifc_module_code": rec["module_code"],
            "bim_rows": rec["bim_rows"],
            "actual_rows": rec["actual_rows"],
            "path_action": path_item.get("proposed_action"),
            "module_action": module_item.get("proposed_action"),
            "approval_status": "pending",
            "approved_project_code": "",
            "approved_module_code": "",
            "reviewer": "",
            "notes": "",
        })
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_sql_schema(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """-- IFC/Notion alignment review schema. Review and apply manually.
CREATE TABLE IF NOT EXISTS ifc_project_link_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ifc_file_id INTEGER NOT NULL REFERENCES ifc_files(ifc_file_id),
    db_file_name TEXT,
    candidate_file_name TEXT,
    current_project_code TEXT,
    approved_project_code TEXT,
    current_module_code TEXT,
    approved_module_code TEXT,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    notes TEXT,
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ifc_review_ifc_file
    ON ifc_project_link_reviews(ifc_file_id);

CREATE INDEX IF NOT EXISTS idx_ifc_review_status
    ON ifc_project_link_reviews(approval_status);
""",
        encoding="utf-8",
    )


def main() -> None:
    con = connect()
    locals_ = local_ifc_files()
    records = fetch_ifc_records(con)
    path_plan = path_repair_plan(records, locals_)
    module_plan = module_repair_plan(con, records)
    template_rows = review_template(records, path_plan, module_plan)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "ifc_path_repair_plan.json").write_text(
        json.dumps(path_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "ifc_project_module_repair_plan.json").write_text(
        json.dumps(module_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(OUT_DIR / "ifc_project_link_review_template.csv", template_rows)
    write_sql_schema(SQL_DIR / "ifc_project_link_reviews_schema.sql")

    summary = {
        "ifc_records": len(records),
        "local_ifc_files": len(locals_),
        "path_actions": {},
        "module_actions": {},
        "outputs": {
            "path_repair_plan": str(OUT_DIR / "ifc_path_repair_plan.json"),
            "module_repair_plan": str(OUT_DIR / "ifc_project_module_repair_plan.json"),
            "review_template": str(OUT_DIR / "ifc_project_link_review_template.csv"),
            "review_schema": str(SQL_DIR / "ifc_project_link_reviews_schema.sql"),
        },
    }
    for item in path_plan:
        action = item["proposed_action"]
        summary["path_actions"][action] = summary["path_actions"].get(action, 0) + 1
    for item in module_plan:
        action = item["proposed_action"]
        summary["module_actions"][action] = summary["module_actions"].get(action, 0) + 1

    (OUT_DIR / "ifc_cleanup_plan_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
