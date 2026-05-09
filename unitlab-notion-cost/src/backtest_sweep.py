"""LOO backtest sweep — 여러 filter 시나리오로 자재 MAPE 변화 추적.

각 시나리오 측정:
  - baseline: status='입금완료' + MAT/LAB/EXP/MIXED/ETC
  - relaxed: + '진행 전'
  - drop_mixed: relaxed + MIXED 제외 (Q12 2차)
  - completed_only: relaxed + drop_mixed + progress_stage='완료'/'준공 대기'

출력: 비교표 + reports/sweep_results.json
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly,
    connect_enriched,
    list_projects_for_backtest_v2,
    load_actual_samples_v2,
    LEARNABLE_COST_TYPES,
    LEARNABLE_STATUS,
    LEARNABLE_STATUS_RELAXED,
)
from notion_cost_model import Pool, predict_for_module
from backtest_v2 import bucket_actuals_by_project


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "sweep_results.json"


def run_one(
    *,
    label: str,
    cost_types: tuple[str, ...],
    statuses: tuple[str, ...],
    drop_mixed: bool,
    completed_only: bool = False,
    exclude_noise_work_codes: bool = False,
    use_all_statuses: bool = False,
    outlier_pct: float | None = None,
    op_con: sqlite3.Connection | None = None,
    en_con: sqlite3.Connection | None = None,
    completed_pids: set | None = None,
) -> dict:
    own_conn = op_con is None or en_con is None
    if own_conn:
        op_con = connect_readonly()
        en_con = connect_enriched()
    samples = load_actual_samples_v2(
        en_con, op_con,
        cost_types=cost_types,
        statuses=statuses,
        drop_mixed=drop_mixed,
        exclude_noise_work_codes=exclude_noise_work_codes,
        use_all_statuses=use_all_statuses,
        outlier_pct=outlier_pct,
    )
    projects = list_projects_for_backtest_v2(en_con, op_con)

    if completed_only:
        if completed_pids is None:
            completed_pids = {
                r[0] for r in en_con.execute(
                    "SELECT project_notion_id FROM projects_master "
                    "WHERE progress_stage IN ('완료','준공 대기')"
                )
            }
        projects = [p for p in projects if p["project_notion_id"] in completed_pids]

    if own_conn:
        en_con.close(); op_con.close()

    learnable_proj_ids = {p["project_id"] for p in projects if p["module_code"]}
    samples = [s for s in samples if s["project_id"] in learnable_proj_ids]
    n_samples = len(samples)
    n_projects = len(learnable_proj_ids)

    full_pool = Pool.from_samples(samples)
    actuals_by_project = bucket_actuals_by_project(samples)
    project_records = []
    cost_type_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})

    for proj in projects:
        pid = proj["project_id"]
        if pid not in learnable_proj_ids:
            continue
        train_pool = full_pool.exclude_project(pid)
        actual_kv = actuals_by_project.get(pid, {})
        actual_total = sum(actual_kv.values())
        if actual_total <= 0:
            continue
        prediction = predict_for_module(
            train_pool,
            grade=proj["grade"],
            pyeong=proj["pyeong"],
            area_m2=proj["floor_area_m2"],
        )
        pred_kv = {
            (b["work_code"], b["cost_type"]): b["amount"]
            for b in prediction["breakdown"]
        }
        for k in set(actual_kv) | set(pred_kv):
            a = actual_kv.get(k, 0)
            p = pred_kv.get(k, 0)
            _, ct = k
            if a > 0:
                err = abs(p - a) / a
                cost_type_errors[ct]["errors"].append(err)
                cost_type_errors[ct]["abs_diff"] += abs(p - a)
                cost_type_errors[ct]["actual"] += a

        pred_total = prediction["total"]
        total_err  = (pred_total - actual_total) / actual_total
        project_records.append({
            "project_code": proj["project_code"],
            "actual": actual_total, "predicted": pred_total,
            "abs_error_pct": round(abs(total_err) * 100, 1),
        })

    abs_errs = sorted(r["abs_error_pct"] for r in project_records)
    n = len(abs_errs)
    abs_diff_total = sum(abs(r["predicted"] - r["actual"]) for r in project_records)
    actual_total_sum = sum(r["actual"] for r in project_records)

    def mape_for(ct: str) -> float | None:
        d = cost_type_errors.get(ct)
        if not d or not d["actual"]:
            return None
        return round(d["abs_diff"] / d["actual"] * 100, 1)

    return {
        "label":            label,
        "n_samples":        n_samples,
        "n_projects":       n_projects,
        "loo_n":            n,
        "median_ape_pct":   round(statistics.median(abs_errs), 1) if n else None,
        "weighted_mape_pct": round(abs_diff_total / actual_total_sum * 100, 1) if actual_total_sum else None,
        "within_20_pct":    round(sum(1 for e in abs_errs if e <= 20) / n * 100, 1) if n else 0,
        "within_20_count":  f"{sum(1 for e in abs_errs if e <= 20)}/{n}",
        "mat_mape_pct":     mape_for("MAT"),
        "lab_mape_pct":     mape_for("LAB"),
        "exp_mape_pct":     mape_for("EXP"),
        "mixed_mape_pct":   mape_for("MIXED"),
        "etc_mape_pct":     mape_for("ETC"),
    }


def main() -> int:
    scenarios = [
        dict(label="baseline (settled+all types)",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS, drop_mixed=False),
        dict(label="A. + 진행 전",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED, drop_mixed=False),
        dict(label="B. A + drop MIXED",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED, drop_mixed=True),
        dict(label="C. B + only 완료/준공",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED,
             drop_mixed=True, completed_only=True),
        dict(label="D. C + drop noise wc",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED,
             drop_mixed=True, completed_only=True, exclude_noise_work_codes=True),
        dict(label="E. D + all statuses",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED,
             drop_mixed=True, completed_only=True, exclude_noise_work_codes=True,
             use_all_statuses=True),
        dict(label="F. all statuses + drop noise (no completed-only)",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED,
             drop_mixed=True, completed_only=False, exclude_noise_work_codes=True,
             use_all_statuses=True),
        dict(label="G. F + outlier P95",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED,
             drop_mixed=True, completed_only=False, exclude_noise_work_codes=True,
             use_all_statuses=True, outlier_pct=0.95),
        dict(label="H. F + outlier P90",
             cost_types=LEARNABLE_COST_TYPES, statuses=LEARNABLE_STATUS_RELAXED,
             drop_mixed=True, completed_only=False, exclude_noise_work_codes=True,
             use_all_statuses=True, outlier_pct=0.90),
    ]

    # Connection 한 번 열어 모든 scenario 공유 — module_types/projects_master 중복 query 회피
    op_con = connect_readonly()
    en_con = connect_enriched()
    completed_pids = {
        r[0] for r in en_con.execute(
            "SELECT project_notion_id FROM projects_master "
            "WHERE progress_stage IN ('완료','준공 대기')"
        )
    }

    results = []
    for s in scenarios:
        print(f"running: {s['label']} ...")
        r = run_one(**s, op_con=op_con, en_con=en_con, completed_pids=completed_pids)
        results.append(r)

    en_con.close(); op_con.close()

    print()
    print("=" * 100)
    print(f"{'scenario':<40} {'samples':>7} {'proj':>4} {'wMAPE':>6} {'±20%':>8} {'MAT':>6} {'LAB':>6} {'EXP':>6} {'MIX':>6}")
    print("-" * 100)
    for r in results:
        def fmt(v):
            return f"{v:>5.1f}%" if v is not None else "    -"
        print(f"{r['label']:<40} {r['n_samples']:>7} {r['n_projects']:>4} "
              f"{fmt(r['weighted_mape_pct'])} {r['within_20_count']:>8} "
              f"{fmt(r['mat_mape_pct'])} {fmt(r['lab_mape_pct'])} "
              f"{fmt(r['exp_mape_pct'])} {fmt(r['mixed_mape_pct'])}")

    print()
    print(f"흡수 트리거(자재 MAPE < 15%) 도달 시나리오: ", end="")
    eligible = [r['label'] for r in results if r['mat_mape_pct'] and r['mat_mape_pct'] < 15.0]
    print(eligible if eligible else "없음")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(f"저장: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
