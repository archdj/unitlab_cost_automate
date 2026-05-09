"""F7 Explainability — 영향 변수, 유사 프로젝트, 데이터 품질."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .db import connect_readonly
from .model import Pool


def top_features(prediction: dict, n: int = 5) -> list[dict]:
    """breakdown 중 amount 기준 상위 N개 — '이 비용이 총액을 얼마나 결정했는지'."""
    total = max(prediction.get("total", 0), 1)
    items = prediction.get("breakdown", [])[:n]
    out = []
    for cell in items:
        out.append({
            "work_code":    cell["work_code"],
            "work_name":    cell["work_name"],
            "cost_type":    cell["cost_type"],
            "amount":       cell["amount"],
            "contribution": round(cell["amount"] / total, 4),
            "tier_used":    cell.get("tier_used"),
            "sample_count": cell.get("sample_count"),
            "confidence":   cell.get("confidence"),
        })
    return out


def similar_projects(
    pool: Pool,
    *,
    grade: str,
    area_m2: float,
    n: int = 3,
) -> list[dict]:
    """모듈/평형/등급 가중 거리 기준 상위 N개 프로젝트 + 실제 합계."""
    by_proj: dict[str, dict] = defaultdict(lambda: {"actual_total": 0, "rows": 0})
    for s in pool.samples:
        d = by_proj[s["project_code"]]
        d["project_code"] = s["project_code"]
        d["module_code"]  = s["module_code"]
        d["floor_area_m2"] = s["floor_area_m2"]
        d["grade"]        = s["grade"]
        d["actual_total"] += s["amount"]
        d["rows"]         += 1

    def distance(p) -> float:
        grade_term = 0.0 if p["grade"] == grade else 0.5
        area = p["floor_area_m2"] or 0
        if area <= 0 or area_m2 <= 0:
            area_term = 1.0
        else:
            area_term = min(abs(area - area_m2) / area_m2, 1.0)
        return 0.6 * grade_term + 0.4 * area_term

    ranked = sorted(by_proj.values(), key=distance)[:n]
    return [{
        "project_code":  p["project_code"],
        "module_code":   p["module_code"],
        "floor_area_m2": p["floor_area_m2"],
        "grade":         p["grade"],
        "actual_total":  int(p["actual_total"]),
        "row_count":     p["rows"],
        "match_score":   round(1 - distance(p), 3),
    } for p in ranked]


def data_quality(pool: Pool) -> dict:
    """학습 풀의 누락률/최신성/매핑 커버리지 지표."""
    n = len(pool.samples)
    projects = {s["project_id"] for s in pool.samples}
    work_codes = {s["normalized_work_code"] for s in pool.samples}
    cost_types = {s["cost_type"] for s in pool.samples}

    # 운영 DB 직접 — 결측 + 최신성
    con = connect_readonly()
    dates = list(con.execute("""
        SELECT MIN(settlement_date) AS first_date,
               MAX(settlement_date) AS last_date,
               COUNT(*) AS rows_total
        FROM actual_costs
        WHERE settlement_date IS NOT NULL AND total_amount > 0
    """))[0]
    null_quantity = con.execute(
        "SELECT COUNT(*) FROM actual_costs WHERE actual_quantity IS NULL"
    ).fetchone()[0]
    rows_total = dates["rows_total"] or 1
    con.close()

    last = dates["last_date"]
    months_since_last = None
    if last:
        try:
            y, m, d = (int(x) for x in last.split("-")[:3])
            today = date.today()
            months_since_last = round(
                (today.year - y) * 12 + (today.month - m) + (today.day - d) / 30, 1
            )
        except Exception:
            months_since_last = None

    return {
        "samples_in_pool":      n,
        "projects_in_pool":     len(projects),
        "work_codes_in_pool":   len(work_codes),
        "cost_types_in_pool":   sorted(cost_types),
        "first_settlement":     dates["first_date"],
        "last_settlement":      last,
        "months_since_last":    months_since_last,
        "actual_quantity_null_rate": round(null_quantity / rows_total, 4),
    }
