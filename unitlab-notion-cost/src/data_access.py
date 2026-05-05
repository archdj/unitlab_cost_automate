"""Read-only access to the operational DB. No IFC tables touched."""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT.parent / "unitlab-cost-analysis" / "db" / "cost_analysis.db"


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def connect_readonly() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"운영 DB 없음: {DB_PATH}")
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def workcode_normalize_map(con: sqlite3.Connection) -> dict[int, dict]:
    """work_code_id → {normalized_code, normalized_name, level, category}.
    level 3 → level 2로, 그 외는 self."""
    rows = [dict(r) for r in con.execute(
        "SELECT work_code_id, work_code, parent_code_id, level, category, work_name_ko, unit FROM work_codes"
    )]
    by_id = {r["work_code_id"]: r for r in rows}
    cache: dict[int, dict] = {}

    def normalized(row_id: int) -> dict:
        if row_id in cache:
            return cache[row_id]
        cur = by_id[row_id]
        while cur["level"] > 2 and cur.get("parent_code_id") and by_id.get(cur["parent_code_id"]):
            cur = by_id[cur["parent_code_id"]]
        cache[row_id] = cur
        return cur

    return {
        wid: {
            "normalized_code": normalized(wid)["work_code"],
            "normalized_name": normalized(wid)["work_name_ko"],
            "category":        normalized(wid)["category"],
            "level":           by_id[wid]["level"],
            "definition_unit": normalized(wid)["unit"],
        }
        for wid in by_id
    }


def load_actual_samples(con: sqlite3.Connection) -> list[dict]:
    """One row per (project, normalized_work_code, cost_type).

    Returns rows ready for fitting:
        project_id / project_code / module_code / floor_area_m2 / pyeong / grade /
        normalized_work_code / work_name / category / cost_type / amount / rate_per_m2
    """
    norm = workcode_normalize_map(con)

    raw = list(con.execute("""
        SELECT
          ac.project_id,
          ac.work_code_id,
          COALESCE(ac.source_ref, 'unknown') AS cost_type,
          SUM(ac.total_amount) AS amount,
          p.project_code,
          mt.module_code,
          mt.floor_area_m2,
          mt.pyeong,
          UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
          mt.structure_type
        FROM actual_costs ac
        JOIN projects p           ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
        GROUP BY ac.project_id, ac.work_code_id, COALESCE(ac.source_ref, 'unknown')
    """))

    grouped: dict[tuple, dict] = {}
    for r in raw:
        nwc = norm[r["work_code_id"]]
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            # 면적 없는 프로젝트는 학습에서 제외 (rate 산출 불가)
            continue
        key = (r["project_id"], nwc["normalized_code"], r["cost_type"])
        if key in grouped:
            grouped[key]["amount"] += int(r["amount"] or 0)
        else:
            grouped[key] = {
                "project_id":            r["project_id"],
                "project_code":          r["project_code"],
                "module_code":           r["module_code"],
                "normalized_work_code":  nwc["normalized_code"],
                "work_name":             nwc["normalized_name"],
                "category":              nwc["category"],
                "cost_type":             r["cost_type"],
                "amount":                int(r["amount"] or 0),
                "floor_area_m2":         area,
                "pyeong":                float(r["pyeong"] or 0),
                "grade":                 r["grade"],
                "structure_type":        r["structure_type"] or "STEEL",
            }

    samples = []
    for s in grouped.values():
        s["rate_per_m2"] = s["amount"] / s["floor_area_m2"] if s["floor_area_m2"] else 0
        if s["rate_per_m2"] <= 0:
            continue
        samples.append(s)
    return samples


def list_modules(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("""
        SELECT module_type_id, module_code, module_name,
               floor_area_m2, pyeong, structure_type,
               UPPER(COALESCE(finish_grade, 'UNKNOWN')) AS grade
        FROM module_types
        WHERE floor_area_m2 IS NOT NULL AND floor_area_m2 > 0
          AND module_code NOT LIKE 'IFC-%'
    """)]


def list_projects_for_backtest(con: sqlite3.Connection) -> list[dict]:
    """Projects with module info AND actual cost > some minimum."""
    return [dict(r) for r in con.execute("""
        SELECT p.project_id, p.project_code, p.project_name,
               mt.module_code, mt.floor_area_m2, mt.pyeong,
               UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac      ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        GROUP BY p.project_id
        HAVING actual_total > 1000000
        ORDER BY actual_total DESC
    """)]


if __name__ == "__main__":
    con = connect_readonly()
    samples = load_actual_samples(con)
    print(f"actual samples: {len(samples)}")
    print(f"projects: {len({s['project_id'] for s in samples})}")
    print(f"work_codes: {len({s['normalized_work_code'] for s in samples})}")
    print(f"cost_types: {sorted({s['cost_type'] for s in samples})}")
