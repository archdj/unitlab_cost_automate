"""LOO backtest v2 — sidecar enriched DB 사용. 항목별(자재/노무/장비/혼합/기타) MAPE 측정.

Q10 A 부활 (cost_type=노션 '선택' 직접 매핑) + 16 학습 가능 프로젝트.
v1 backtest.py와 다른 점:
  - data_access의 v2 함수 (sidecar 기반) 사용
  - cost_type 라벨이 의미 있음 (MAT/LAB/EXP/MIXED/ETC)
  - **자재 MAPE 측정 시 MAT 카테고리만 대상**, MIXED는 제외 (Q12 1차 escalation)
  - 출력 reports/loo_backtest_by_cost_type.json — 흡수 트리거 평가용
"""
from __future__ import annotations

import json
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
    LEARNABLE_STATUS_RELAXED,
)
from notion_cost_model import Pool, predict_for_module, MODEL_VERSION


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "loo_backtest_by_cost_type.json"

# F scenario filter — backtest_sweep.py에서 best baseline. 측정값은 reports/sweep_results.json 참조.
DEFAULT_FILTERS = dict(
    cost_types=LEARNABLE_COST_TYPES,
    statuses=LEARNABLE_STATUS_RELAXED,
    drop_mixed=True,
    exclude_noise_work_codes=True,
    use_all_statuses=True,
)

# 흡수 트리거 평가 — 자재 MAPE 측정에서 MIXED 라벨 행은 제외 (혼합 비용은 분리 불능).
MATERIAL_MAPE_FOCUS = "MAT"


def bucket_actuals_by_project(samples: list[dict]) -> dict[int, dict[tuple[str, str], int]]:
    """전체 samples를 project_id → (work_code, cost_type) → amount로 1회 pass에 집계.
    LOO loop에서 O(n_samples) scan을 O(1) lookup으로 대체."""
    out: dict[int, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for s in samples:
        out[s["project_id"]][(s["normalized_work_code"], s["cost_type"])] += s["amount"]
    return out


def project_actual_breakdown(samples: list[dict], project_id: int) -> dict:
    """Held-out project의 actual을 (work_code, cost_type) → amount.
    Single-call helper; LOO loop에서는 bucket_actuals_by_project 권장."""
    out: dict[tuple[str, str], int] = defaultdict(int)
    for s in samples:
        if s["project_id"] == project_id:
            out[(s["normalized_work_code"], s["cost_type"])] += s["amount"]
    return out


def run() -> dict:
    op_con = connect_readonly()
    en_con = connect_enriched()
    samples = load_actual_samples_v2(en_con, op_con, **DEFAULT_FILTERS)
    projects = list_projects_for_backtest_v2(en_con, op_con)
    en_con.close(); op_con.close()

    proj_meta = {p["project_id"]: p for p in projects}
    learnable_proj_ids = {p["project_id"] for p in projects if p["module_code"]}
    samples = [s for s in samples if s["project_id"] in learnable_proj_ids]

    print(f"projects in backtest: {len(learnable_proj_ids)}")
    print(f"total learning samples: {len(samples)}")

    full_pool = Pool.from_samples(samples)
    actuals_by_project = bucket_actuals_by_project(samples)
    print(f"pool cells: {len(full_pool.by_key)}")
    print()

    project_records = []
    workcode_errors:  dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})
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

        area_m2 = proj["floor_area_m2"]
        prediction = predict_for_module(
            train_pool,
            grade=proj["grade"],
            pyeong=proj["pyeong"],
            area_m2=area_m2,
        )
        pred_kv: dict[tuple[str, str], int] = {
            (b["work_code"], b["cost_type"]): b["amount"]
            for b in prediction["breakdown"]
        }

        # Per-key (workcode, cost_type) error aggregation
        all_keys = set(actual_kv) | set(pred_kv)
        for k in all_keys:
            a = actual_kv.get(k, 0)
            p = pred_kv.get(k, 0)
            wc, ct = k
            if a > 0:
                err = abs(p - a) / a
                workcode_errors[wc]["errors"].append(err)
                workcode_errors[wc]["abs_diff"] += abs(p - a)
                workcode_errors[wc]["actual"] += a
                cost_type_errors[ct]["errors"].append(err)
                cost_type_errors[ct]["abs_diff"] += abs(p - a)
                cost_type_errors[ct]["actual"] += a

        pred_total = prediction["total"]
        total_err = (pred_total - actual_total) / actual_total

        project_records.append({
            "project_code":  proj["project_code"],
            "project_name":  proj["project_name"],
            "module_code":   proj["module_code"],
            "area_m2":       area_m2,
            "grade":         proj["grade"],
            "pyeong":        proj["pyeong"],
            "actual":        actual_total,
            "predicted":     pred_total,
            "lower":         prediction["confidence_lower"],
            "upper":         prediction["confidence_upper"],
            "error_pct":     round(total_err * 100, 1),
            "abs_error_pct": round(abs(total_err) * 100, 1),
            "actual_by_cost_type":    {
                ct: sum(v for (_, c), v in actual_kv.items() if c == ct)
                for ct in {c for _, c in actual_kv}
            },
            "predicted_by_cost_type": {
                ct: sum(v for (_, c), v in pred_kv.items() if c == ct)
                for ct in {c for _, c in pred_kv}
            },
        })

    # Aggregate
    def agg(errors_dict: dict[str, dict]) -> list[dict]:
        rows = []
        for k, d in errors_dict.items():
            errs = sorted(d["errors"])
            if not errs:
                continue
            n = len(errs)
            rows.append({
                "key":             k,
                "sample_count":    n,
                "mae_pct":         round(statistics.mean(errs) * 100, 1),
                "median_abs_error_pct": round(statistics.median(errs) * 100, 1),
                "weighted_mape_pct":    round(d["abs_diff"] / d["actual"] * 100, 1) if d["actual"] else None,
                "max_pct":         round(max(errs) * 100, 1),
                "actual_sum":      d["actual"],
                "priority_score":  round(statistics.mean(errs) * d["actual"]),
            })
        return sorted(rows, key=lambda x: -x["priority_score"])

    workcode_rows  = agg(workcode_errors)
    cost_type_rows = agg(cost_type_errors)

    # Overall (project total level)
    abs_errs = sorted(r["abs_error_pct"] for r in project_records)
    n = len(abs_errs)
    abs_diff_total   = sum(abs(r["predicted"] - r["actual"]) for r in project_records)
    actual_total_sum = sum(r["actual"] for r in project_records)

    overall = {
        "sample_count": n,
        "mae_pct":      round(statistics.mean(abs_errs), 1) if n else 0,
        "median_abs_error_pct": round(statistics.median(abs_errs), 1) if n else 0,
        "weighted_mape_pct": round(abs_diff_total / actual_total_sum * 100, 1) if actual_total_sum else None,
        "within_10_pct": round(sum(1 for e in abs_errs if e <= 10) / n * 100, 1) if n else 0,
        "within_20_pct": round(sum(1 for e in abs_errs if e <= 20) / n * 100, 1) if n else 0,
        "within_30_pct": round(sum(1 for e in abs_errs if e <= 30) / n * 100, 1) if n else 0,
        "hit_rate_within_20": f"{sum(1 for e in abs_errs if e <= 20)}/{n}",
    }

    # 흡수 트리거 평가: 자재 MAPE
    mat_row = next((r for r in cost_type_rows if r["key"] == MATERIAL_MAPE_FOCUS), None)
    merge_eval = {
        "trigger": "자재(MAT) weighted MAPE < 15%",
        "current_material_mape_pct": mat_row["weighted_mape_pct"] if mat_row else None,
        "merge_eligible": (mat_row is not None and mat_row["weighted_mape_pct"] is not None
                          and mat_row["weighted_mape_pct"] < 15.0),
        "note": "Q12 1차 escalation: MIXED 행은 학습엔 포함, 자재 MAPE 측정에선 별도 라벨로 분리.",
    }

    report = {
        "model_version":     f"{MODEL_VERSION}-v2-sidecar",
        "data_source":       "sidecar autocost_enriched.db (Zip 3, 2026-05-09)",
        "overall":           overall,
        "merge_eval":        merge_eval,
        "by_cost_type":      cost_type_rows,
        "by_workcode":       workcode_rows[:30],  # top 30
        "projects":          project_records,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def print_report(rep: dict) -> None:
    print(f"=== LOO Backtest v2 — {rep['model_version']} ===")
    print(f"data: {rep['data_source']}")
    print()

    o = rep["overall"]
    print(f"전체 ({o['sample_count']}개 프로젝트)")
    print(f"  중앙값 APE:           {o['median_abs_error_pct']}%")
    print(f"  Weighted MAPE:        {o['weighted_mape_pct']}%")
    print(f"  ±20% hit-rate:        {o['hit_rate_within_20']} ({o['within_20_pct']}%)")
    print(f"  ±10% hit-rate:        {o['within_10_pct']}%")
    print()

    me = rep["merge_eval"]
    eligible = "✅ 도달" if me["merge_eligible"] else "❌ 미달"
    print(f"흡수 트리거: {me['trigger']}")
    print(f"  현재 자재 MAPE:       {me['current_material_mape_pct']}%  →  {eligible}")
    print()

    print("비용유형(cost_type)별 MAPE:")
    print(f"  {'type':10s} {'n':>4s} {'MAE':>7s} {'wMAPE':>7s} {'actual':>10s}")
    for c in rep["by_cost_type"]:
        actual_m = c['actual_sum'] / 1e6
        wmape = c.get('weighted_mape_pct')
        wmape_str = f"{wmape:>6.1f}%" if wmape is not None else "    -"
        print(f"  {c['key']:10s} {c['sample_count']:>4d} {c['mae_pct']:>6.1f}% {wmape_str} {actual_m:>8.1f}M")
    print()

    print(f"프로젝트별 (n={len(rep['projects'])}):")
    print(f"  {'project':40s} {'mod':10s} {'area':>5s} {'actual':>8s} {'predicted':>10s} {'error':>7s}")
    for p in rep["projects"]:
        name = (p["project_name"] or p["project_code"])[:40]
        print(f"  {name:40s} {(p['module_code'] or '-')[:10]:10s} {p['area_m2']:>4.1f}m {p['actual']/1e6:>6.1f}M {p['predicted']/1e6:>8.1f}M {p['error_pct']:>+6.1f}%")
    print()

    print("공종별 priority TOP 10:")
    print(f"  {'work_code':25s} {'n':>3s} {'MAE':>6s} {'wMAPE':>6s} {'actual':>10s}")
    for w in rep["by_workcode"][:10]:
        actual_m = w['actual_sum'] / 1e6
        wmape = w.get('weighted_mape_pct')
        wmape_str = f"{wmape:>5.1f}%" if wmape is not None else "    -"
        print(f"  {w['key'][:25]:25s} {w['sample_count']:>3d} {w['mae_pct']:>5.1f}% {wmape_str} {actual_m:>8.1f}M")


if __name__ == "__main__":
    rep = run()
    print_report(rep)
    print()
    print(f"리포트 저장: {REPORT_PATH}")
