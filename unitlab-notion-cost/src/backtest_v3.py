"""LOO backtest v3 — 운영 DB 기반 + sidecar corrections optional.

비교 측정:
  v3 OFF: corrections 미적용 (운영 DB actual_costs 그대로)
  v3 ON : sidecar actual_cost_corrections 적용 (work_code row 단위 재분류)

자재(MAT) wMAPE 변화 정량화 = corrections 효과.

주의: v3는 운영 DB 학습 가능 프로젝트(N=8)만 사용. v2 (sidecar, N=15) 와는
프로젝트 set이 다르므로 직접 비교 불가. v3 OFF vs v3 ON 으로만 효과 분리.
"""
from __future__ import annotations

import json
import sys
import statistics
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly,
    connect_enriched,
    load_actual_samples_v3,
    list_projects_for_backtest,
)
from notion_cost_model import Pool, predict_for_module


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "backtest_v3_corrections_compare.json"


def bucket_actuals_by_project(samples: list[dict]) -> dict[int, dict[tuple[str, str], int]]:
    out: dict[int, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for s in samples:
        out[s["project_id"]][(s["normalized_work_code"], s["cost_type"])] += s["amount"]
    return out


def run_one(samples: list[dict], projects: list[dict], label: str) -> dict:
    proj_meta = {p["project_id"]: p for p in projects}
    learnable = {p["project_id"] for p in projects if p["module_code"]}
    samples = [s for s in samples if s["project_id"] in learnable]

    full_pool = Pool.from_samples(samples)
    actuals_by_project = bucket_actuals_by_project(samples)

    project_records = []
    cost_type_errors: dict[str, dict] = defaultdict(
        lambda: {"errors": [], "abs_diff": 0, "actual": 0}
    )
    workcode_errors: dict[str, dict] = defaultdict(
        lambda: {"errors": [], "abs_diff": 0, "actual": 0}
    )

    for proj in projects:
        pid = proj["project_id"]
        if pid not in learnable:
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
            "actual":       actual_total,
            "predicted":    pred_total,
            "error_pct":    round(total_err * 100, 1),
            "abs_error_pct": round(abs(total_err) * 100, 1),
        })

    # Aggregate
    abs_errors = [r["abs_error_pct"] / 100 for r in project_records]
    actuals = [r["actual"] for r in project_records]
    abs_diffs = [abs(r["predicted"] - r["actual"]) for r in project_records]
    n = len(abs_errors)
    overall = {
        "label": label,
        "sample_count": n,
        "mae_pct": round(sum(abs_errors)/n * 100, 1) if n else 0,
        "median_abs_error_pct": round(statistics.median(abs_errors) * 100, 1) if n else 0,
        "weighted_mape_pct": round(sum(abs_diffs)/sum(actuals) * 100, 1) if sum(actuals) else 0,
        "within_20_pct": round(sum(1 for e in abs_errors if e <= 0.20) / n * 100, 1) if n else 0,
        "hit_rate_within_20": f"{sum(1 for e in abs_errors if e <= 0.20)}/{n}",
    }

    by_cost_type = []
    for ct, d in cost_type_errors.items():
        if not d["errors"]:
            continue
        by_cost_type.append({
            "key": ct,
            "sample_count": len(d["errors"]),
            "mae_pct": round(sum(d["errors"])/len(d["errors"]) * 100, 1),
            "weighted_mape_pct": round(d["abs_diff"]/d["actual"] * 100, 1) if d["actual"] else 0,
            "actual_sum": d["actual"],
        })
    by_cost_type.sort(key=lambda x: -x["actual_sum"])

    by_workcode_top = []
    for wc, d in workcode_errors.items():
        if not d["errors"]:
            continue
        by_workcode_top.append({
            "key": wc,
            "sample_count": len(d["errors"]),
            "weighted_mape_pct": round(d["abs_diff"]/d["actual"] * 100, 1) if d["actual"] else 0,
            "actual_sum": d["actual"],
        })
    by_workcode_top.sort(key=lambda x: -x["actual_sum"])

    return {
        "overall": overall,
        "by_cost_type": by_cost_type,
        "by_workcode_top10": by_workcode_top[:10],
        "projects": project_records,
    }


def run() -> dict:
    op = connect_readonly()
    en = connect_enriched()

    s_off = load_actual_samples_v3(op, apply_corrections=False)
    s_on  = load_actual_samples_v3(op, apply_corrections=True, corrections_con=en)
    projects = list_projects_for_backtest(op)

    op.close(); en.close()

    print(f"v3 OFF: samples={len(s_off)}, projects={len(projects)}")
    print(f"v3 ON : samples={len(s_on)},  projects={len(projects)}")
    print()

    r_off = run_one(s_off, projects, "corrections=OFF")
    r_on  = run_one(s_on,  projects, "corrections=ON")

    print("\n=== Comparison ===")
    print(f"{'metric':30s}  {'OFF':>10s}  {'ON':>10s}  {'delta':>10s}")
    for k in ("sample_count", "mae_pct", "median_abs_error_pct", "weighted_mape_pct", "within_20_pct"):
        a = r_off['overall'][k]
        b = r_on['overall'][k]
        d = b - a if isinstance(a, (int, float)) else "-"
        print(f"  {k:28s}  {a:>10}  {b:>10}  {d:>+10.2f}" if isinstance(d, (int, float)) else f"  {k:28s}  {a:>10}  {b:>10}  {'-':>10}")
    print(f"  {'hit_rate_within_20':28s}  {r_off['overall']['hit_rate_within_20']:>10}  {r_on['overall']['hit_rate_within_20']:>10}")

    print("\n=== by cost_type ===")
    print(f"{'cost_type':10s}  {'OFF wMAPE':>10s}  {'ON wMAPE':>10s}  {'delta':>10s}")
    off_ct = {x['key']: x for x in r_off['by_cost_type']}
    on_ct  = {x['key']: x for x in r_on['by_cost_type']}
    for ct in ("MAT", "LAB", "EXP", "ETC"):
        a = off_ct.get(ct, {}).get('weighted_mape_pct')
        b = on_ct.get(ct, {}).get('weighted_mape_pct')
        if a is None or b is None:
            print(f"  {ct:10s}  {'-':>10}  {'-':>10}")
            continue
        print(f"  {ct:10s}  {a:>10.1f}  {b:>10.1f}  {b-a:>+10.2f}")

    out = {
        "model_version": "v10.0-notion-v3-operational",
        "data_source": "operational cost_analysis.db (PR-1 cost_type) + sidecar corrections optional",
        "off": r_off,
        "on": r_on,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")
    return out


if __name__ == "__main__":
    run()
