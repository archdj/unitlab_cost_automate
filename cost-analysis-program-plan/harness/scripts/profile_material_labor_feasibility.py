from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT / "unitlab-cost-analysis"
DB = REPO / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "material_labor_feasibility.json"


COL_CODE = "\ucf54\ub4dc"
COL_MATERIAL = "\uc790\uc7ac\uba85"
COL_SPEC = "\uc790\uc7ac \uaddc\uaca9"
COL_DETAIL_SPEC = "\uc0c1\uc138\uaddc\uaca9"
COL_UNIT = "\ub2e8\uc704"
COL_QTY = "\uc218\ub7c9"
COL_VENDOR = "\uc5c5\uccb4\uba85"
COL_PROCESS = "\uacf5\uc815"
COL_LOCATION = "\uc0ac\uc6a9\uc704\uce58"
COL_STATUS = "\uc9c4\ud589"
COL_ORDER_DATE = "\ubc1c\uc8fc\uc77c"
COL_DELIVERY_DATE = "\ub0a9\ud488\uc77c"
COL_PROJECT = "\ud504\ub85c\uc81d\ud2b8\uba85"


def rows(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in cur.execute(sql, params).fetchall()]


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def find_csv() -> Path | None:
    files = sorted(REPO.glob("*.csv"))
    return files[0] if files else None


def profile_csv() -> dict:
    path = find_csv()
    if not path:
        return {"exists": False}

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        data = list(csv.DictReader(f))

    completed = [r for r in data if (r.get(COL_STATUS) or "").strip() == "\uc644\ub8cc"]
    material_rows = [
        r for r in data
        if (r.get(COL_MATERIAL) or "").strip()
        and parse_number(r.get(COL_QTY)) is not None
    ]

    def top(col: str, source: list[dict] = data, n: int = 20) -> list[dict]:
        c = Counter((r.get(col) or "").strip() or "(blank)" for r in source)
        return [{"value": k, "count": v} for k, v in c.most_common(n)]

    return {
        "exists": True,
        "path": str(path),
        "row_count": len(data),
        "completed_count": len(completed),
        "material_quantity_rows": len(material_rows),
        "blank_material_rows": sum(1 for r in data if not (r.get(COL_MATERIAL) or "").strip()),
        "blank_project_rows": sum(1 for r in data if not (r.get(COL_PROJECT) or "").strip()),
        "has_amount_column": any("amount" in c.lower() or "\uae08\uc561" in c for c in (data[0].keys() if data else [])),
        "top_materials": top(COL_MATERIAL, material_rows),
        "top_processes": top(COL_PROCESS),
        "top_projects": top(COL_PROJECT),
        "top_vendors": top(COL_VENDOR),
        "top_units": top(COL_UNIT, material_rows),
    }


def profile_db() -> dict:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cost_type = rows(
        cur,
        """
        SELECT source_ref AS cost_type, COUNT(*) AS row_count, SUM(total_amount) AS total_amount
        FROM actual_costs
        GROUP BY source_ref
        ORDER BY total_amount DESC
        """,
    )

    actual_linkage = rows(
        cur,
        """
        SELECT
            COUNT(*) AS total_rows,
            SUM(CASE WHEN material_id IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_material_id,
            SUM(CASE WHEN actual_quantity IS NOT NULL AND actual_quantity > 0 THEN 1 ELSE 0 END) AS rows_with_quantity,
            SUM(CASE WHEN unit_price IS NOT NULL AND unit_price > 0 THEN 1 ELSE 0 END) AS rows_with_unit_price
        FROM actual_costs
        """,
    )[0]

    by_work_cost_type = rows(
        cur,
        """
        SELECT wc.category, wc.work_code, wc.work_name_ko, ac.source_ref AS cost_type,
               COUNT(*) AS row_count, SUM(ac.total_amount) AS total_amount
        FROM actual_costs ac
        JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
        GROUP BY wc.work_code_id, ac.source_ref
        ORDER BY total_amount DESC
        LIMIT 80
        """,
    )

    labor_by_work = rows(
        cur,
        """
        SELECT wc.category, wc.work_code, wc.work_name_ko,
               COUNT(*) AS row_count, SUM(ac.total_amount) AS total_amount
        FROM actual_costs ac
        JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
        WHERE ac.source_ref = ?
        GROUP BY wc.work_code_id
        ORDER BY total_amount DESC
        """,
        ("\ub178\ubb34\ube44",),
    )

    mixed_by_work = rows(
        cur,
        """
        SELECT wc.category, wc.work_code, wc.work_name_ko,
               COUNT(*) AS row_count, SUM(ac.total_amount) AS total_amount
        FROM actual_costs ac
        JOIN work_codes wc ON ac.work_code_id = wc.work_code_id
        WHERE ac.source_ref = ?
        GROUP BY wc.work_code_id
        ORDER BY total_amount DESC
        """,
        ("\uc7ac\ub8cc\ube44+\ub178\ubb34\ube44",),
    )

    return {
        "actual_cost_linkage": actual_linkage,
        "cost_type_summary": cost_type,
        "labor_by_work": labor_by_work,
        "mixed_material_labor_by_work": mixed_by_work,
        "top_work_cost_type": by_work_cost_type,
    }


def main() -> None:
    report = {
        "summary": {
            "can_predict_by_material_now": False,
            "reason": "actual_costs has no material_id, quantity, or unit_price links; procurement CSV has material quantities but no amount column.",
            "can_extract_labor_signal_now": True,
            "labor_signal": "actual_costs.source_ref separates labor, material, mixed material+labor, expense, and other cost types.",
        },
        "db": profile_db(),
        "procurement_csv": profile_csv(),
        "recommended_feature_marts": [
            "project_material_quantity_features",
            "project_work_labor_features",
            "project_material_labor_bridge",
            "project_cost_prediction_inputs",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(REPORT))


if __name__ == "__main__":
    main()
