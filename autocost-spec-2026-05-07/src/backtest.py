"""LOO backtest — v11.0-autocost-mvp 모델 정확도 측정.

각 프로젝트를 한 개씩 빼고 (test) 나머지로 학습한 뒤, 빠진 프로젝트의 실원가
대비 예측 오차를 측정. 총액 / 공종별 / 비용유형별로 MAE, weighted MAPE, ±20% hit rate.

Usage:
    python -m src.backtest
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import MODEL_REPORTS, MODEL_VERSION
from src.db import connect_readonly, list_projects_for_backtest, load_actual_samples
from src.model import Pool, predict_for_module


REPORT_PATH = MODEL_REPORTS / f"loo_backtest_{MODEL_VERSION}.json"


def project_actual_breakdown(samples: list[dict], project_id: int) -> dict:
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

    full_pool = Pool.from_samples(all_samples)
    print(f"projects in backtest: {len(projects)}")
    print(f"total samples:        {len(all_samples)}")
    print(f"pool cells:           {len(full_pool.by_key)}")
    print()

    project_records: list[dict] = []
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
        pred_kv = {(b["work_code"], b["cost_type"]): b["amount"] for b in prediction["breakdown"]}

        for k in set(actual_kv) | set(pred_kv):
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
            "module_code":   proj["module_code"],
            "area_m2":       proj["floor_area_m2"],
            "grade":         proj["grade"],
            "actual":        actual_total,
            "predicted":     pred_total,
            "lower":         prediction["confidence_lower"],
            "upper":         prediction["confidence_upper"],
            "error_pct":     round(total_err * 100, 1),
            "abs_error_pct": round(abs(total_err) * 100, 1),
        })

    def agg(d: dict) -> list[dict]:
        rows = []
        for k, v in d.items():
            errs = sorted(v["errors"])
            if not errs:
                continue
            rows.append({
                "key":                  k,
                "sample_count":         len(errs),
                "mae_pct":              round(statistics.mean(errs) * 100, 1),
                "median_abs_error_pct": round(statistics.median(errs) * 100, 1),
                "weighted_mape_pct":    round(v["abs_diff"] / v["actual"] * 100, 1) if v["actual"] else None,
                "max_pct":              round(max(errs) * 100, 1),
                "actual_sum":           v["actual"],
                "priority_score":       round(statistics.mean(errs) * v["actual"]),
            })
        return sorted(rows, key=lambda x: -x["priority_score"])

    abs_errs = sorted(r["abs_error_pct"] for r in project_records)
    n = len(abs_errs)
    abs_diff_total = sum(abs(r["predicted"] - r["actual"]) for r in project_records)
    actual_total_sum = sum(r["actual"] for r in project_records)

    overall = {
        "sample_count":          n,
        "mae_pct":               round(statistics.mean(abs_errs), 1) if n else 0,
        "median_abs_error_pct":  round(statistics.median(abs_errs), 1) if n else 0,
        "weighted_mape_pct":     round(abs_diff_total / actual_total_sum * 100, 1) if actual_total_sum else None,
        "within_10_pct":         round(sum(1 for e in abs_errs if e <= 10) / n * 100, 1) if n else 0,
        "within_20_pct":         round(sum(1 for e in abs_errs if e <= 20) / n * 100, 1) if n else 0,
        "within_30_pct":         round(sum(1 for e in abs_errs if e <= 30) / n * 100, 1) if n else 0,
    }

    return {
        "model_version":  MODEL_VERSION,
        "overall":        overall,
        "by_workcode":    agg(workcode_errors),
        "by_cost_type":   agg(cost_type_errors),
        "projects":       project_records,
    }


def print_report(rep: dict) -> None:
    print(f"=== LOO Backtest — {rep['model_version']} ===\n")
    o = rep["overall"]
    print(f"전체 ({o['sample_count']}개 프로젝트)")
    print(f"  MAE                  : {o['mae_pct']}%")
    print(f"  중앙값 |APE|         : {o['median_abs_error_pct']}%")
    print(f"  Weighted MAPE        : {o['weighted_mape_pct']}%")
    print(f"  ±10%                 : {o['within_10_pct']}%")
    print(f"  ±20%                 : {o['within_20_pct']}%")
    print(f"  ±30%                 : {o['within_30_pct']}%\n")

    print("프로젝트별:")
    print(f"  {'project':30s} {'module':10s} {'area':>5s} {'actual':>9s} {'pred':>9s} {'err':>7s}")
    for p in rep["projects"]:
        print(f"  {(p['project_code'] or '')[:30]:30s} "
              f"{(p['module_code'] or '-')[:10]:10s} "
              f"{p['area_m2']:>5.1f} "
              f"{p['actual']/1e6:>7.1f}M "
              f"{p['predicted']/1e6:>7.1f}M "
              f"{p['error_pct']:>+6.1f}%")
    print()

    print("비용유형별:")
    print(f"  {'cost_type':18s} {'n':>3s} {'MAE':>6s} {'wMAPE':>6s} {'actual':>10s}")
    for c in rep["by_cost_type"]:
        wm = c.get('weighted_mape_pct')
        wm_s = f"{wm}%" if wm is not None else "-"
        print(f"  {(c['key'] or '')[:18]:18s} {c['sample_count']:>3d} "
              f"{c['mae_pct']:>5.1f}% {wm_s:>6s} {c['actual_sum']/1e6:>8.1f}M")
    print()

    print("공종별 TOP 10 (priority = MAE × actual):")
    print(f"  {'work_code':12s} {'n':>3s} {'MAE':>6s} {'중앙값':>6s} {'wMAPE':>6s} {'actual':>10s}")
    for w in rep["by_workcode"][:10]:
        wm = w.get('weighted_mape_pct')
        wm_s = f"{wm}%" if wm is not None else "-"
        print(f"  {w['key']:12s} {w['sample_count']:>3d} "
              f"{w['mae_pct']:>5.1f}% {w['median_abs_error_pct']:>5.1f}% "
              f"{wm_s:>6s} {w['actual_sum']/1e6:>8.1f}M")


if __name__ == "__main__":
    rep = run()
    print_report(rep)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH}")
