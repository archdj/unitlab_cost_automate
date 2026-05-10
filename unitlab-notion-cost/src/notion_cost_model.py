"""v10.0-notion: Notion 실원가만으로 동작하는 견적 모델.

학습:
    pool = (work_code × cost_type) 별로 모인 (project, rate_per_m2, grade, pyeong, ...) 레코드.

예측:
    입력 모듈의 grade/pyeong/area를 받아, 공종 × 비용유형마다 유사 사례 풀에서
    median rate를 골라 amount를 산출한다. tier 별 fallback 으로 sample 수가 부족한
    case에 대비한다.

CLI:
    python src/notion_cost_model.py predict --module T-15-STD --quantity 1
    python src/notion_cost_model.py train               # cost_predictions에 저장 (skip if you don't want)
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# allow `python src/notion_cost_model.py` 실행
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly,
    connect_enriched,
    list_modules,
    load_actual_samples,
    load_actual_samples_v2,
    build_pcode_to_sidecar_pid_bridge,
    load_quote_sums_keyed_by_sidecar_pid,
    apply_quote_corrections_to_samples,
)


MODEL_VERSION = "v10.0-notion"
MODEL_VERSION_V2 = "v10.1-notion-sidecar-quote"
MIN_TIER_SAMPLES = 2   # tier 채택 최소 샘플 수
TARGET_SAMPLE_FOR_FULL_CONFIDENCE = 8


# ─────────────────────────────────────────────────────────────────────────────
# Pool: 학습 데이터
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Pool:
    """In-memory rate pool keyed by (work_code, cost_type).

    `total_projects`는 학습 데이터의 unique project 수. 각 cell의 sample_count /
    total_projects 가 곧 적용 확률(applicability rate)이며 amount 산출 시 곱해진다.
    """
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
        kept = [s for s in self.samples if s["project_id"] != project_id]
        return Pool.from_samples(kept)

    def keys(self):
        return self.by_key.keys()

    def applicability(
        self,
        work_code: str,
        cost_type: str,
        grade: str | None = None,
        target_area: float | None = None,
        area_ratio_band: tuple[float, float] = (0.5, 2.0),
    ) -> float:
        """이 (work_code, cost_type)이 비슷한 grade·size 프로젝트에서 등장한 비율.

        target_area 가 주어지면 면적 비율이 area_ratio_band 안에 드는 프로젝트만 본다.
        이게 outlier 케이스(예: 16.5m² 캠프 모듈)에 큰 모듈의 공종이 그대로 적용되는 것을 막는다.
        """
        cell = self.by_key.get((work_code, cost_type), [])

        def in_size_band(area: float) -> bool:
            if target_area is None or target_area <= 0 or area <= 0:
                return True
            ratio = area / target_area
            return area_ratio_band[0] <= ratio <= area_ratio_band[1]

        if grade is not None:
            denom_projects = {
                s["project_id"] for s in self.samples
                if s["grade"] == grade and in_size_band(s["floor_area_m2"])
            }
            cell_projects = {
                s["project_id"] for s in cell
                if s["grade"] == grade and in_size_band(s["floor_area_m2"])
            }
        else:
            denom_projects = {
                s["project_id"] for s in self.samples
                if in_size_band(s["floor_area_m2"])
            }
            cell_projects = {
                s["project_id"] for s in cell
                if in_size_band(s["floor_area_m2"])
            }
        denom = max(len(denom_projects), 1)
        return len(cell_projects) / denom


# ─────────────────────────────────────────────────────────────────────────────
# Tiered similarity
# ─────────────────────────────────────────────────────────────────────────────

def select_tier(samples: list[dict], grade: str, pyeong: float) -> tuple[str, list[dict]]:
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


# ─────────────────────────────────────────────────────────────────────────────
# Statistics helpers
# ─────────────────────────────────────────────────────────────────────────────

def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lower = int(math.floor(pos))
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = pos - lower
    return sorted_values[lower] * (1 - frac) + sorted_values[upper] * frac


def confidence_score(n: int, lower: float, upper: float, median: float) -> float:
    sample_term = min(1.0, n / TARGET_SAMPLE_FOR_FULL_CONFIDENCE)
    spread = (upper - lower) / median if median else 1.0
    spread_term = max(0.0, 1.0 - spread)
    return round(0.5 * sample_term + 0.5 * spread_term, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Predict
# ─────────────────────────────────────────────────────────────────────────────

def predict_cell(
    samples: list[dict],
    grade: str,
    pyeong: float,
    target_area: float,
    work_code: str,
    cost_type: str,
    applicability: float,
) -> dict | None:
    if not samples or applicability <= 0:
        return None
    tier_name, chosen = select_tier(samples, grade, pyeong)
    rates = sorted(s["rate_per_m2"] for s in chosen)
    if not rates:
        return None
    median_rate = percentile(rates, 0.5)
    lo_rate     = percentile(rates, 0.25)
    hi_rate     = percentile(rates, 0.75)

    # 적용 확률(applicability)을 곱해 expected amount 산출
    sample_meta = chosen[0]
    expected_amount = median_rate * target_area * applicability
    return {
        "work_code":    work_code,
        "work_name":    sample_meta["work_name"],
        "category":     sample_meta["category"],
        "cost_type":    cost_type,
        "amount":       int(round(expected_amount)),
        "rate_per_m2":  int(round(median_rate)),
        "applicability": round(applicability, 3),
        "lower":        int(round(lo_rate * target_area * applicability)),
        "upper":        int(round(hi_rate * target_area * applicability)),
        "sample_count": len(chosen),
        "tier_used":    tier_name,
        "confidence":   confidence_score(len(chosen), lo_rate, hi_rate, median_rate),
        "source_cases": sorted({s["project_code"] for s in chosen}),
    }


def predict_for_module(pool: Pool, *, grade: str, pyeong: float, area_m2: float) -> dict:
    breakdown = []
    missing = []

    # 학습 풀 size 분포 정보 (UI 노출용)
    size_band = (area_m2 * 0.5, area_m2 * 2.0)
    in_band_projects = sorted({
        (s["project_code"], s["module_code"], s["floor_area_m2"], s["grade"])
        for s in pool.samples
        if size_band[0] <= s["floor_area_m2"] <= size_band[1]
    })
    same_grade_in_band = [p for p in in_band_projects if p[3] == grade]

    # 작은 모듈 경고: 비슷한 size + grade 학습 데이터가 거의 없으면
    pool_warnings: list[str] = []
    if len(same_grade_in_band) < 2:
        pool_warnings.append(
            f"동등급({grade}) + 비슷한 면적({size_band[0]:.0f}~{size_band[1]:.0f}m²) "
            f"학습 데이터 {len(same_grade_in_band)}개 — 신뢰도 매우 낮음"
        )
    if len(in_band_projects) < 2:
        pool_warnings.append(
            f"비슷한 면적({size_band[0]:.0f}~{size_band[1]:.0f}m²) 학습 데이터 {len(in_band_projects)}개 — "
            f"전체 풀의 큰 모듈로 fallback됨"
        )

    for (work_code, cost_type), samples in pool.by_key.items():
        # 1) 같은 grade + 비슷한 size
        applicability = pool.applicability(work_code, cost_type, grade=grade, target_area=area_m2)
        tier_used_for_appl = "same_grade_size_band"
        # 2) fallback: 비슷한 size (grade 무관)
        if applicability == 0:
            applicability = pool.applicability(work_code, cost_type, target_area=area_m2)
            tier_used_for_appl = "size_band"
        # 3) fallback: 같은 grade (size 무관)
        if applicability == 0:
            applicability = pool.applicability(work_code, cost_type, grade=grade)
            tier_used_for_appl = "same_grade"
        # 4) fallback: 전체
        if applicability == 0:
            applicability = pool.applicability(work_code, cost_type)
            tier_used_for_appl = "all"
        cell = predict_cell(samples, grade, pyeong, area_m2, work_code, cost_type, applicability)
        if cell is None:
            missing.append({"work_code": work_code, "cost_type": cost_type})
            continue
        cell["applicability_tier"] = tier_used_for_appl
        breakdown.append(cell)
    breakdown.sort(key=lambda x: x["amount"], reverse=True)

    total = sum(b["amount"] for b in breakdown)
    lower = sum(b["lower"] for b in breakdown)
    upper = sum(b["upper"] for b in breakdown)

    return {
        "model_version":      MODEL_VERSION,
        "input": {
            "grade":      grade,
            "pyeong":     pyeong,
            "area_m2":    area_m2,
        },
        "total":              total,
        "confidence_lower":   lower,
        "confidence_upper":   upper,
        "breakdown":          breakdown,
        "missing_workcodes":  missing,
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
        "warnings":           pool_warnings,
    }


def predict_request(pool: Pool, modules: list[dict]) -> dict:
    """modules: [{module_code, quantity}]. 운영 DB에서 module 메타 조회."""
    con = connect_readonly()
    mods = {m["module_code"]: m for m in list_modules(con)}
    con.close()

    items = []
    total_area = 0.0
    breakdown_by_key: dict[tuple, dict] = {}

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
            "module_code":  m["module_code"],
            "module_name":  m["module_name"],
            "quantity":     qty,
            "extended_area_m2": area,
            "predicted":    single,
        })
        # 합산용 — 같은 (work_code, cost_type)는 누적
        for cell in single["breakdown"]:
            key = (cell["work_code"], cell["cost_type"])
            base = breakdown_by_key.setdefault(key, {**cell, "amount": 0, "lower": 0, "upper": 0, "sample_count": cell["sample_count"]})
            base["amount"] += cell["amount"]
            base["lower"]  += cell["lower"]
            base["upper"]  += cell["upper"]

    consolidated = sorted(breakdown_by_key.values(), key=lambda x: x["amount"], reverse=True)
    grand_total = sum(b["amount"] for b in consolidated)
    grand_lower = sum(b["lower"] for b in consolidated)
    grand_upper = sum(b["upper"] for b in consolidated)

    return {
        "model_version":     MODEL_VERSION,
        "modules":           items,
        "total_area_m2":     total_area,
        "total":             grand_total,
        "confidence_lower":  grand_lower,
        "confidence_upper":  grand_upper,
        "breakdown":         consolidated,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Train (load samples → Pool)
# ─────────────────────────────────────────────────────────────────────────────

def build_pool() -> Pool:
    """v1 학습 풀 (운영 DB only, N=8). cost_type=source_ref 버그 있음 — 레거시."""
    con = connect_readonly()
    samples = load_actual_samples(con)
    con.close()
    return Pool.from_samples(samples)


def build_pool_v2(apply_quote_corrections: bool = True) -> tuple[Pool, dict]:
    """v2 production 학습 풀 (sidecar N=15) + quote correction 옵션.

    sidecar `actual_costs_enriched` (1420 cost rows, MAT/LAB/EXP/MIXED/ETC 정규화)
    + DEFAULT_FILTERS (F scenario: noise wc 제외 + all statuses + drop MIXED).

    apply_quote_corrections=True 시 sidecar `material_quote_lines` 의
    (project_code, work_code) amount sum 으로 자재 셀 actual 보정 — 검증된
    자재 wMAPE proj-sum -3.15pp 안정 개선.

    Returns (pool, build_stats: dict).
    """
    # backtest_v2.DEFAULT_FILTERS 와 동일 (importing 하면 순환 참조 위험)
    from data_access import LEARNABLE_COST_TYPES, LEARNABLE_STATUS_RELAXED
    DEFAULT_FILTERS = dict(
        cost_types=LEARNABLE_COST_TYPES,
        statuses=LEARNABLE_STATUS_RELAXED,
        drop_mixed=True,
        exclude_noise_work_codes=True,
        use_all_statuses=True,
    )

    op = connect_readonly()
    en = connect_enriched()
    samples = load_actual_samples_v2(en, op, **DEFAULT_FILTERS)
    n_baseline = len(samples)
    correction_stats = None

    if apply_quote_corrections:
        bridge = build_pcode_to_sidecar_pid_bridge(en, op)
        quote_keyed, qstats = load_quote_sums_keyed_by_sidecar_pid(en, bridge)
        # Make a deep-ish copy — apply_quote_corrections_to_samples mutates
        samples = [dict(s) for s in samples]
        samples, cstats = apply_quote_corrections_to_samples(samples, quote_keyed)
        correction_stats = {**qstats, **cstats, "bridge_size": len(bridge)}

    en.close(); op.close()
    pool = Pool.from_samples(samples)
    return pool, {
        "model_version": MODEL_VERSION_V2 if apply_quote_corrections else "v10.1-notion-sidecar",
        "n_baseline_samples": n_baseline,
        "n_after_corrections": len(samples),
        "n_projects": pool.total_projects,
        "n_cells": len(pool.by_key),
        "quote_correction_applied": apply_quote_corrections,
        "correction_stats": correction_stats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def cli_predict(module_code: str, quantity: int):
    pool = build_pool()
    res = predict_request(pool, [{"module_code": module_code, "quantity": quantity}])
    print(json.dumps({
        "input":    {"module_code": module_code, "quantity": quantity},
        "total":    res["total"],
        "lower":    res["confidence_lower"],
        "upper":    res["confidence_upper"],
        "area":     res["total_area_m2"],
    }, ensure_ascii=False, indent=2))
    print()
    print(f"{'공종':12s} {'유형':12s} {'금액(원)':>12s} {'단가/m²':>10s} {'tier':25s} {'sample':>6s} {'conf':>5s}")
    for b in res["breakdown"]:
        print(f"  {b['work_code']:10s} {b['cost_type']:12s} {b['amount']:>12,} {b['rate_per_m2']:>10,} {b['tier_used']:25s} {b['sample_count']:>6} {b['confidence']:>5}")


def cli_dump_pool():
    pool = build_pool()
    print(f"unique (work_code, cost_type) cells: {len(pool.by_key)}")
    print(f"total samples: {len(pool.samples)}")
    print()
    by_wc: dict[str, dict] = defaultdict(lambda: {"samples": 0, "amount": 0, "cost_types": set()})
    for (wc, ct), rows in pool.by_key.items():
        d = by_wc[wc]
        d["samples"] += len(rows)
        d["amount"]  += sum(r["amount"] for r in rows)
        d["cost_types"].add(ct)
    for wc, d in sorted(by_wc.items(), key=lambda x: -x[1]["amount"])[:15]:
        print(f"  {wc:18s} samples={d['samples']:>3} amount={d['amount']/1e6:>7.1f}M  cost_types={','.join(sorted(d['cost_types']))}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("predict")
    pp.add_argument("--module", required=True)
    pp.add_argument("--quantity", type=int, default=1)

    sub.add_parser("pool")

    args = p.parse_args()
    if args.cmd == "predict":
        cli_predict(args.module, args.quantity)
    elif args.cmd == "pool":
        cli_dump_pool()


if __name__ == "__main__":
    main()
