"""Bootstrap LOO MAPE — cost_type별 95% CI 산출.

각 LOO 결과(15 프로젝트)에서 resampling(B=1000) → cost_type별 weighted MAPE 분포 →
[2.5%, 97.5%] CI. F filter scenario 기반.

흡수 트리거 평가용: 점추정 39.5%(자재)가 CI [X%, Y%]면 "정확도 우연 도달" 위험 평가 가능.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly, connect_enriched,
    list_projects_for_backtest_v2, load_actual_samples_v2,
)
from notion_cost_model import Pool, predict_for_module
from backtest_v2 import DEFAULT_FILTERS

REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "bootstrap_ci.json"

B = 1000  # bootstrap iterations
SEED = 42


def per_project_cost_type_records() -> list[dict]:
    """각 프로젝트별 cost_type 별 (predicted, actual)를 산출.
    Bootstrap에서는 프로젝트 단위로 resample (15개에서 with replacement).
    """
    op_con = connect_readonly()
    en_con = connect_enriched()
    samples = load_actual_samples_v2(en_con, op_con, **DEFAULT_FILTERS)
    projects = list_projects_for_backtest_v2(en_con, op_con)
    en_con.close(); op_con.close()

    learnable_pids = {p["project_id"] for p in projects if p["module_code"]}
    samples = [s for s in samples if s["project_id"] in learnable_pids]
    full_pool = Pool.from_samples(samples)

    records = []
    for proj in projects:
        pid = proj["project_id"]
        if pid not in learnable_pids:
            continue
        train_pool = full_pool.exclude_project(pid)
        proj_samples = [s for s in samples if s["project_id"] == pid]
        actual_by_ct: dict[str, int] = defaultdict(int)
        for s in proj_samples:
            actual_by_ct[s["cost_type"]] += s["amount"]
        if not actual_by_ct:
            continue
        prediction = predict_for_module(
            train_pool,
            grade=proj["grade"], pyeong=proj["pyeong"],
            area_m2=proj["floor_area_m2"],
        )
        pred_by_ct: dict[str, int] = defaultdict(int)
        for b in prediction["breakdown"]:
            pred_by_ct[b["cost_type"]] += b["amount"]
        records.append({
            "project_id": pid,
            "name":       proj["project_name"],
            "actual_total":    sum(actual_by_ct.values()),
            "predicted_total": sum(pred_by_ct.values()),
            "actual_by_ct":    dict(actual_by_ct),
            "predicted_by_ct": dict(pred_by_ct),
        })
    return records


def bootstrap_metrics(records: list[dict], B: int = 1000, seed: int = 42) -> dict:
    rnd = random.Random(seed)
    n = len(records)
    # DEFAULT_FILTERS에서 학습에 들어가는 cost_type 도출 (drop_mixed=True면 MIXED 제외).
    cost_types = tuple(
        t for t in DEFAULT_FILTERS["cost_types"]
        if not (DEFAULT_FILTERS.get("drop_mixed") and t == "MIXED")
    )

    # Precompute (actual, predicted, abs_diff, ape%) per record × cost_type — static across resamples.
    pairs_total = [(r["actual_total"], r["predicted_total"]) for r in records]
    pairs_by_ct: dict[str, list[tuple[int, int]]] = {
        ct: [(r["actual_by_ct"].get(ct, 0), r["predicted_by_ct"].get(ct, 0)) for r in records]
        for ct in cost_types
    }
    apes_total = [
        abs(p - a) / a * 100 if a > 0 else None
        for a, p in pairs_total
    ]

    def wmape_from_indices(pairs: list[tuple[int, int]], idx: list[int]) -> float | None:
        abs_diff = 0; actual_sum = 0
        for i in idx:
            a, p = pairs[i]
            if a > 0:
                abs_diff += abs(p - a)
                actual_sum += a
        return (abs_diff / actual_sum * 100) if actual_sum else None

    metrics_dist: dict[str, list[float]] = {ct: [] for ct in cost_types}
    metrics_dist["total_wmape"] = []
    metrics_dist["median_ape"]  = []
    metrics_dist["hit_rate_20"] = []

    for _ in range(B):
        idx = [rnd.randint(0, n - 1) for _ in range(n)]
        for ct in cost_types:
            v = wmape_from_indices(pairs_by_ct[ct], idx)
            if v is not None:
                metrics_dist[ct].append(v)
        v = wmape_from_indices(pairs_total, idx)
        if v is not None:
            metrics_dist["total_wmape"].append(v)
        sampled_apes = [apes_total[i] for i in idx if apes_total[i] is not None]
        if sampled_apes:
            metrics_dist["median_ape"].append(statistics.median(sampled_apes))
            n_hit = sum(1 for e in sampled_apes if e <= 20)
            metrics_dist["hit_rate_20"].append(n_hit / len(sampled_apes) * 100)

    def ci(values: list[float]) -> dict:
        if not values:
            return {"point": None, "low": None, "high": None, "n_resamples": 0}
        srt = sorted(values)
        return {
            "n_resamples": len(srt),
            "point":  round(statistics.median(srt), 1),
            "low":    round(srt[int(len(srt) * 0.025)], 1),
            "high":   round(srt[int(len(srt) * 0.975)], 1),
            "mean":   round(statistics.mean(srt), 1),
            "stdev":  round(statistics.stdev(srt), 1) if len(srt) > 1 else None,
        }

    return {k: ci(v) for k, v in metrics_dist.items()}


def main() -> int:
    records = per_project_cost_type_records()
    print(f"projects in bootstrap: {len(records)}")
    print()

    cis = bootstrap_metrics(records, B=B, seed=SEED)

    print(f"=== Bootstrap 95% CI (B={B}) ===")
    print(f"{'metric':14} {'point':>7} {'95% CI':>20} {'mean':>7} {'stdev':>7}")
    for k, ci in cis.items():
        if ci["point"] is None:
            print(f"  {k:12} (no data)")
            continue
        ci_str = f"[{ci['low']:>5.1f}%, {ci['high']:>5.1f}%]"
        print(f"  {k:12} {ci['point']:>5.1f}% {ci_str:>20} {ci['mean']:>5.1f}% {ci['stdev']:>5.1f}%")
    print()

    # Trigger evaluation: γ thresholds
    print("=== γ 트리거 평가 (CI 상한 기준) ===")
    proposed = {
        "MAT":         30,    # 자재
        "LAB":         50,    # 노무
        "EXP":         50,    # 경비
        "total_wmape": 30,    # 총액
        "median_ape":  20,    # median APE
        "hit_rate_20": 50,    # hit-rate (lower-bound)
    }
    for k, threshold in proposed.items():
        ci = cis.get(k)
        if not ci or ci["point"] is None:
            continue
        if k == "hit_rate_20":
            ok = ci["low"] >= threshold  # hit-rate는 lower bound
            sign = ">="
            cmp = ci["low"]
        else:
            ok = ci["high"] < threshold  # MAPE는 upper bound
            sign = "<"
            cmp = ci["high"]
        mark = "✅" if ok else "❌"
        print(f"  {k:12} CI {sign} {threshold}%   actual={cmp}%   {mark}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({"records": records, "cis": cis, "proposed": proposed},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
