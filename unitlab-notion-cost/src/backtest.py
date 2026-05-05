"""LOO backtest for v10.0-notion.

각 프로젝트를 한 개씩 빼고(=test set) 나머지로 학습한 뒤, 빠진 프로젝트의 실원가
대비 예측 오차를 측정한다. 총액 / 공종별 / 비용유형별로 MAE, weighted MAPE,
±20% 이내 비율을 산출한다.
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
    list_projects_for_backtest,
    load_actual_samples,
)
from notion_cost_model import Pool, predict_for_module, MODEL_VERSION


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "loo_backtest.json"


def project_actual_breakdown(samples: list[dict], project_id: int) -> dict:
    """Held-out project의 actual을 (work_code, cost_type) → amount 로."""
    out: dict[tuple[str, str], int] = defaultdict(int)
    for s in samples:
        if s["project_id"] == project_id:
            out[(s["normalized_work_code"], s["cost_type"])] += s["amount"]
    return out


def run() -> dict:
    con = connect_readonly()
    all_samples = load_actual_samples(con)
    projects = list_projects_for_backtest(con)
    con.close()

    # project_id → meta
    proj_meta = {p["project_id"]: p for p in projects}
    print(f"projects in backtest: {len(projects)}")
    print(f"total samples: {len(all_samples)}")

    full_pool = Pool.from_samples(all_samples)
    print(f"pool cells: {len(full_pool.by_key)}")
    print()

    project_records = []
    workcode_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})
    cost_type_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})

    for proj in projects:
        pid = proj["project_id"]
        train_pool = full_pool.exclude_project(pid)
        actual_kv = project_actual_breakdown(all_samples, pid)
        actual_total = sum(actual_kv.values())
        if actual_total <= 0:
            continue

        prediction = predict_for_module(
            train_pool,
            grade=proj["grade"],
            pyeong=float(proj["pyeong"] or 0),
            area_m2=float(proj["floor_area_m2"]),
        )
        pred_kv: dict[tuple[str, str], int] = {
            (b["work_code"], b["cost_type"]): b["amount"]
            for b in prediction["breakdown"]
        }

        # Per-key 매칭 (예측에는 있는데 actual엔 없을 수도, 그 반대도)
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
            "project_code": proj["project_code"],
            "module_code":  proj["module_code"],
            "area_m2":      proj["floor_area_m2"],
            "grade":        proj["grade"],
            "pyeong":       proj["pyeong"],
            "actual":       actual_total,
            "predicted":    pred_total,
            "lower":        prediction["confidence_lower"],
            "upper":        prediction["confidence_upper"],
            "error_pct":    round(total_err * 100, 1),
            "abs_error_pct": round(abs(total_err) * 100, 1),
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
                "key":            k,
                "sample_count":   n,
                "mae_pct":        round(statistics.mean(errs) * 100, 1),
                "median_abs_error_pct": round(statistics.median(errs) * 100, 1),
                "weighted_mape_pct":    round(d["abs_diff"] / d["actual"] * 100, 1) if d["actual"] else None,
                "max_pct":        round(max(errs) * 100, 1),
                "actual_sum":     d["actual"],
                "priority_score": round(statistics.mean(errs) * d["actual"]),
            })
        return sorted(rows, key=lambda x: -x["priority_score"])

    workcode_rows = agg(workcode_errors)
    cost_type_rows = agg(cost_type_errors)

    # Overall (project total level)
    abs_errs = sorted(r["abs_error_pct"] for r in project_records)
    n = len(abs_errs)
    abs_diff_total = sum(abs(r["predicted"] - r["actual"]) for r in project_records)
    actual_total_sum = sum(r["actual"] for r in project_records)

    overall = {
        "sample_count": n,
        "mae_pct":      round(statistics.mean(abs_errs), 1) if n else 0,
        "median_abs_error_pct": round(statistics.median(abs_errs), 1) if n else 0,
        "weighted_mape_pct": round(abs_diff_total / actual_total_sum * 100, 1) if actual_total_sum else None,
        "within_10_pct": round(sum(1 for e in abs_errs if e <= 10) / n * 100, 1) if n else 0,
        "within_20_pct": round(sum(1 for e in abs_errs if e <= 20) / n * 100, 1) if n else 0,
        "within_30_pct": round(sum(1 for e in abs_errs if e <= 30) / n * 100, 1) if n else 0,
    }

    report = {
        "model_version":     MODEL_VERSION,
        "overall":           overall,
        "by_workcode":       workcode_rows,
        "by_cost_type":      cost_type_rows,
        "projects":          project_records,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def print_report(rep: dict) -> None:
    print(f"=== LOO Backtest — {rep['model_version']} ===")
    print()
    o = rep["overall"]
    print(f"전체 ({o['sample_count']}개 프로젝트)")
    print(f"  MAE:                  {o['mae_pct']}%")
    print(f"  중앙값 APE:           {o['median_abs_error_pct']}%")
    print(f"  Weighted MAPE:        {o['weighted_mape_pct']}%")
    print(f"  ±10%:                 {o['within_10_pct']}%")
    print(f"  ±20%:                 {o['within_20_pct']}%")
    print(f"  ±30%:                 {o['within_30_pct']}%")
    print()

    print("프로젝트별:")
    print(f"  {'project':28s} {'module':12s} {'area':>5s} {'actual':>8s} {'predicted':>10s} {'error':>7s}")
    for p in rep["projects"]:
        print(f"  {p['project_code'][:28]:28s} {(p['module_code'] or '-')[:12]:12s} {p['area_m2']:>5.1f} {p['actual']/1e6:>6.1f}M {p['predicted']/1e6:>8.1f}M  {p['error_pct']:>+5.1f}%")
    print()

    print("공종별 우선순위 TOP 10 (priority_score):")
    print(f"  {'work_code':12s} {'n':>3s} {'MAE':>6s} {'중앙값':>6s} {'wMAPE':>6s} {'actual':>10s}")
    for w in rep["by_workcode"][:10]:
        actual_m = w['actual_sum'] / 1e6
        print(f"  {w['key']:12s} {w['sample_count']:>3d} {w['mae_pct']:>5.1f}% {w['median_abs_error_pct']:>5.1f}% {w.get('weighted_mape_pct') or '-':>5}% {actual_m:>8.1f}M")
    print()

    print("비용유형별:")
    print(f"  {'cost_type':12s} {'n':>3s} {'MAE':>6s} {'wMAPE':>6s} {'actual':>10s}")
    for c in rep["by_cost_type"]:
        actual_m = c['actual_sum'] / 1e6
        print(f"  {c['key']:12s} {c['sample_count']:>3d} {c['mae_pct']:>5.1f}% {c.get('weighted_mape_pct') or '-':>5}% {actual_m:>8.1f}M")


if __name__ == "__main__":
    rep = run()
    print_report(rep)
    print()
    print(f"리포트 저장: {REPORT_PATH}")
