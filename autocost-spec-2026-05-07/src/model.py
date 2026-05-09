"""Pool 기반 (work_code × cost_type) tier 예측. v10.0-notion 패턴 승계."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from .config import (
    MODEL_VERSION,
    MIN_TIER_SAMPLES,
    TARGET_SAMPLE_FOR_FULL_CONFIDENCE,
)
from .db import connect_readonly, list_modules, load_actual_samples


@dataclass
class Pool:
    by_key: dict[tuple[str, str], list[dict]]
    samples: list[dict]
    total_projects: int

    @classmethod
    def from_samples(cls, samples: list[dict]) -> "Pool":
        by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for s in samples:
            by_key[(s["normalized_work_code"], s["cost_type"])].append(s)
        total_projects = len({s["project_id"] for s in samples}) or 1
        return cls(by_key=dict(by_key), samples=samples, total_projects=total_projects)

    def exclude_project(self, project_id: int) -> "Pool":
        """LOO backtest 용 — 특정 project를 제외한 새 풀."""
        kept = [s for s in self.samples if s["project_id"] != project_id]
        return Pool.from_samples(kept)

    def applicability(
        self,
        work_code: str,
        cost_type: str,
        grade: str | None = None,
        target_area: float | None = None,
        area_ratio_band: tuple[float, float] = (0.5, 2.0),
    ) -> float:
        cell = self.by_key.get((work_code, cost_type), [])

        def in_band(area: float) -> bool:
            if target_area is None or target_area <= 0 or area <= 0:
                return True
            ratio = area / target_area
            return area_ratio_band[0] <= ratio <= area_ratio_band[1]

        denom = {s["project_id"] for s in self.samples
                 if (grade is None or s["grade"] == grade) and in_band(s["floor_area_m2"])}
        cell_p = {s["project_id"] for s in cell
                  if (grade is None or s["grade"] == grade) and in_band(s["floor_area_m2"])}
        return len(cell_p) / max(len(denom), 1)


def select_tier(samples: list[dict], grade: str, pyeong: float):
    tiers = [
        ("same_grade_close_pyeong",
         [s for s in samples if s["grade"] == grade and abs(s["pyeong"] - pyeong) <= 3]),
        ("same_grade",
         [s for s in samples if s["grade"] == grade]),
        ("close_pyeong",
         [s for s in samples if abs(s["pyeong"] - pyeong) <= 5]),
        ("all", samples),
    ]
    for name, t in tiers:
        if len(t) >= MIN_TIER_SAMPLES:
            return name, t
    return "all", samples


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def confidence_score(n: int, lower: float, upper: float, median: float) -> float:
    sample_term = min(1.0, n / TARGET_SAMPLE_FOR_FULL_CONFIDENCE)
    spread = (upper - lower) / median if median else 1.0
    spread_term = max(0.0, 1.0 - spread)
    return round(0.5 * sample_term + 0.5 * spread_term, 2)


def predict_cell(samples, grade, pyeong, target_area, work_code, cost_type, applicability):
    if not samples or applicability <= 0:
        return None
    tier_name, chosen = select_tier(samples, grade, pyeong)
    rates = sorted(s["rate_per_m2"] for s in chosen)
    if not rates:
        return None
    median_rate = percentile(rates, 0.5)
    lo_rate = percentile(rates, 0.25)
    hi_rate = percentile(rates, 0.75)
    meta = chosen[0]
    return {
        "work_code":     work_code,
        "work_name":     meta["work_name"],
        "category":      meta["category"],
        "cost_type":     cost_type,
        "amount":        int(round(median_rate * target_area * applicability)),
        "rate_per_m2":   int(round(median_rate)),
        "applicability": round(applicability, 3),
        "lower":         int(round(lo_rate * target_area * applicability)),
        "upper":         int(round(hi_rate * target_area * applicability)),
        "sample_count":  len(chosen),
        "tier_used":     tier_name,
        "confidence":    confidence_score(len(chosen), lo_rate, hi_rate, median_rate),
        "source_cases":  sorted({s["project_code"] for s in chosen}),
    }


def predict_for_module(pool: Pool, *, grade: str, pyeong: float, area_m2: float) -> dict:
    breakdown, missing = [], []
    size_band = (area_m2 * 0.5, area_m2 * 2.0)
    in_band_projects = sorted({
        (s["project_code"], s["module_code"], s["floor_area_m2"], s["grade"])
        for s in pool.samples
        if size_band[0] <= s["floor_area_m2"] <= size_band[1]
    })
    same_grade_in_band = [p for p in in_band_projects if p[3] == grade]

    warnings: list[str] = []
    if len(same_grade_in_band) < 2:
        warnings.append(
            f"동등급({grade}) + 비슷한 면적({size_band[0]:.0f}~{size_band[1]:.0f}m²) "
            f"학습 데이터 {len(same_grade_in_band)}개 — 신뢰도 매우 낮음"
        )
    if len(in_band_projects) < 2:
        warnings.append(
            f"비슷한 면적 학습 데이터 {len(in_band_projects)}개 — 큰 모듈로 fallback됨"
        )

    for (work_code, cost_type), samples in pool.by_key.items():
        appl = pool.applicability(work_code, cost_type, grade=grade, target_area=area_m2)
        tier = "same_grade_size_band"
        if appl == 0:
            appl = pool.applicability(work_code, cost_type, target_area=area_m2)
            tier = "size_band"
        if appl == 0:
            appl = pool.applicability(work_code, cost_type, grade=grade)
            tier = "same_grade"
        if appl == 0:
            appl = pool.applicability(work_code, cost_type)
            tier = "all"
        cell = predict_cell(samples, grade, pyeong, area_m2, work_code, cost_type, appl)
        if cell is None:
            missing.append({"work_code": work_code, "cost_type": cost_type})
            continue
        cell["applicability_tier"] = tier
        breakdown.append(cell)

    breakdown.sort(key=lambda x: x["amount"], reverse=True)
    return {
        "model_version":     MODEL_VERSION,
        "input":             {"grade": grade, "pyeong": pyeong, "area_m2": area_m2},
        "total":             sum(b["amount"] for b in breakdown),
        "confidence_lower":  sum(b["lower"] for b in breakdown),
        "confidence_upper":  sum(b["upper"] for b in breakdown),
        "breakdown":         breakdown,
        "missing_workcodes": missing,
        "training_pool": {
            "size_band":           [round(size_band[0], 1), round(size_band[1], 1)],
            "in_band_projects":    [
                {"project_code": p[0], "module_code": p[1], "floor_area_m2": p[2], "grade": p[3]}
                for p in in_band_projects
            ],
            "in_band_count":       len(in_band_projects),
            "same_grade_in_band":  len(same_grade_in_band),
            "total_pool_projects": pool.total_projects,
        },
        "warnings": warnings,
    }


def predict_request(pool: Pool, modules: list[dict]) -> dict:
    """modules: [{module_code, quantity}]."""
    con = connect_readonly()
    mods = {m["module_code"]: m for m in list_modules(con)}
    con.close()

    items, total_area = [], 0.0
    by_key: dict[tuple, dict] = {}
    for req in modules:
        m = mods.get(req["module_code"])
        if m is None:
            continue
        qty = int(req.get("quantity", 1))
        area = float(m["floor_area_m2"]) * qty
        total_area += area
        single = predict_for_module(
            pool,
            grade=m["grade"],
            pyeong=float(m["pyeong"] or 0),
            area_m2=area,
        )
        items.append({
            "module_code":      m["module_code"],
            "module_name":      m["module_name"],
            "quantity":         qty,
            "extended_area_m2": area,
            "predicted":        single,
        })
        for cell in single["breakdown"]:
            k = (cell["work_code"], cell["cost_type"])
            base = by_key.setdefault(k, {**cell, "amount": 0, "lower": 0, "upper": 0})
            base["amount"] += cell["amount"]
            base["lower"]  += cell["lower"]
            base["upper"]  += cell["upper"]

    consolidated = sorted(by_key.values(), key=lambda x: x["amount"], reverse=True)
    return {
        "model_version":    MODEL_VERSION,
        "modules":          items,
        "total_area_m2":    total_area,
        "total":            sum(b["amount"] for b in consolidated),
        "confidence_lower": sum(b["lower"] for b in consolidated),
        "confidence_upper": sum(b["upper"] for b in consolidated),
        "breakdown":        consolidated,
    }


def build_pool() -> Pool:
    con = connect_readonly()
    samples = load_actual_samples(con)
    con.close()
    return Pool.from_samples(samples)
