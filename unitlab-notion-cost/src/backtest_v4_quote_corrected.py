"""LOO backtest v4 — 견적서 amount로 자재 actual 보정 시뮬레이션.

출처: autocost-spec/harness/scripts/simulate_quote_corrected_wmape.py 마이그
(v11.0 src 의존 → unitlab-notion-cost 모듈로 교체).

비교 측정:
  baseline:  운영 DB actual_costs 그대로
  corrected: sidecar material_quote_lines (project_code, work_code) → quote_sum 으로
             자재(cost_type=MAT) 셀 actual amount 대체. quote만 있고 actual 없는
             셀은 학습 풀에 추가.

자재 wMAPE 측정 단위:
  - cell-단위 wMAPE: backtest_v2/v3와 동일 (work_code × cost_type 셀별)
  - project-sum wMAPE: 프로젝트별 자재 합계 기준 (메모리 시뮬 21.7%→14~16% 수치)

Status: 2026-05-10 마이그.
"""
from __future__ import annotations

import json
import sys
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly,
    connect_enriched,
    load_actual_samples_v3,
    list_projects_for_backtest,
    LEARNABLE_COST_TYPES,
)
from notion_cost_model import Pool, predict_for_module


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "backtest_v4_quote_corrected.json"
MAT_LABEL = "MAT"


def load_quote_sums(en_con: sqlite3.Connection) -> dict[tuple[str, str], float]:
    """sidecar material_quote_lines → (project_code, work_code) → 견적서 amount sum."""
    out: dict[tuple, float] = defaultdict(float)
    for r in en_con.execute("""
        SELECT project_code, work_code, SUM(amount) AS s
        FROM material_quote_lines
        WHERE project_code IS NOT NULL
          AND work_code IS NOT NULL
          AND amount IS NOT NULL
        GROUP BY project_code, work_code
    """):
        out[(r["project_code"], r["work_code"])] = float(r["s"] or 0)
    return dict(out)


def apply_quote_corrections(
    samples: list[dict],
    quote_sums: dict[tuple[str, str], float],
) -> tuple[list[dict], dict]:
    """자재(MAT) 셀 amount를 quote_sum으로 대체. 신규 셀은 추가.

    Returns (corrected_samples, stats).
    """
    # project_code → project meta (학습 풀에 있는 프로젝트만)
    pc_to_meta: dict[str, dict] = {}
    for s in samples:
        if s["project_code"] not in pc_to_meta:
            pc_to_meta[s["project_code"]] = s

    # (project_id, normalized_work_code, cost_type) → sample dict
    keyed = {(s["project_id"], s["normalized_work_code"], s["cost_type"]): s for s in samples}

    n_replaced = 0
    n_added = 0
    delta_amount = 0
    skipped_no_project = 0

    for (pcode, wc), qsum in quote_sums.items():
        meta = pc_to_meta.get(pcode)
        if meta is None:
            # 프로젝트가 학습 풀에 없음 (운영 DB에 module 매칭 안 된 경우 등)
            skipped_no_project += 1
            continue
        pid = meta["project_id"]
        key = (pid, wc, MAT_LABEL)
        if key in keyed:
            old = keyed[key]["amount"]
            keyed[key]["amount"] = int(qsum)
            keyed[key]["rate_per_m2"] = qsum / keyed[key]["floor_area_m2"] if keyed[key]["floor_area_m2"] else 0
            n_replaced += 1
            delta_amount += abs(qsum - old)
        else:
            # 신규 cell (actual에 없던 work_code) — 학습 풀에 추가
            new_sample = {
                "project_id":           pid,
                "project_code":         pcode,
                "module_code":          meta["module_code"],
                "normalized_work_code": wc,
                "work_name":            wc,
                "category":             "?",
                "cost_type":            MAT_LABEL,
                "amount":               int(qsum),
                "floor_area_m2":        meta["floor_area_m2"],
                "pyeong":               meta["pyeong"],
                "grade":                meta["grade"],
                "structure_type":       meta["structure_type"],
                "rate_per_m2":          qsum / meta["floor_area_m2"] if meta["floor_area_m2"] else 0,
            }
            if new_sample["rate_per_m2"] > 0:
                samples.append(new_sample)
                keyed[key] = new_sample
                n_added += 1
                delta_amount += qsum

    # filter zero rate_per_m2
    samples = [s for s in samples if s.get("rate_per_m2", 0) > 0]
    return samples, {
        "n_replaced": n_replaced,
        "n_added": n_added,
        "delta_amount": int(delta_amount),
        "skipped_no_project": skipped_no_project,
    }


def run_loo(samples: list[dict], projects: list[dict]) -> dict:
    learnable = {p["project_id"] for p in projects if p["module_code"]}
    samples = [s for s in samples if s["project_id"] in learnable]
    full_pool = Pool.from_samples(samples)

    actuals_by_project: dict[int, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for s in samples:
        actuals_by_project[s["project_id"]][(s["normalized_work_code"], s["cost_type"])] += s["amount"]

    project_records = []
    cost_type_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})
    workcode_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})

    for proj in projects:
        pid = proj["project_id"]
        if pid not in learnable:
            continue
        train = full_pool.exclude_project(pid)
        actual_kv = actuals_by_project.get(pid, {})
        actual_total = sum(actual_kv.values())
        if actual_total <= 0:
            continue

        prediction = predict_for_module(
            train,
            grade=proj["grade"],
            pyeong=proj["pyeong"],
            area_m2=proj["floor_area_m2"],
        )
        pred_kv = {(b["work_code"], b["cost_type"]): b["amount"] for b in prediction["breakdown"]}

        for k in set(actual_kv) | set(pred_kv):
            wc, ct = k
            a = actual_kv.get(k, 0)
            p = pred_kv.get(k, 0)
            if a > 0:
                err = abs(p - a) / a
                workcode_errors[wc]["errors"].append(err)
                workcode_errors[wc]["abs_diff"] += abs(p - a)
                workcode_errors[wc]["actual"] += a
                cost_type_errors[ct]["errors"].append(err)
                cost_type_errors[ct]["abs_diff"] += abs(p - a)
                cost_type_errors[ct]["actual"] += a

        actual_mat = sum(v for k, v in actual_kv.items() if k[1] == MAT_LABEL)
        pred_mat = sum(v for k, v in pred_kv.items() if k[1] == MAT_LABEL)
        project_records.append({
            "project_code": proj["project_code"],
            "module_code":  proj["module_code"],
            "actual":       actual_total,
            "predicted":    prediction["total"],
            "actual_mat":   actual_mat,
            "pred_mat":     pred_mat,
            "abs_total_pct": round(abs(prediction["total"] - actual_total) / actual_total * 100, 1),
        })

    # Aggregate
    def proj_sum_wmape(records, key_a, key_p):
        diff = sum(abs(r[key_p] - r[key_a]) for r in records if r[key_a] > 0)
        actual = sum(r[key_a] for r in records if r[key_a] > 0)
        return round(diff / actual * 100, 1) if actual else None

    total_errs = [r["abs_total_pct"] / 100 for r in project_records]
    overall = {
        "n": len(project_records),
        "total_wmape_proj_sum": proj_sum_wmape(project_records, "actual", "predicted"),
        "total_mae_pct": round(sum(total_errs) / len(total_errs) * 100, 1) if total_errs else 0,
        "total_median_pct": round(statistics.median(total_errs) * 100, 1) if total_errs else 0,
        "total_within_20": f"{sum(1 for e in total_errs if e <= 0.20)}/{len(total_errs)}",
        "material_wmape_proj_sum": proj_sum_wmape(project_records, "actual_mat", "pred_mat"),
        "material_wmape_cell": round(
            cost_type_errors[MAT_LABEL]["abs_diff"] / cost_type_errors[MAT_LABEL]["actual"] * 100, 1
        ) if cost_type_errors[MAT_LABEL]["actual"] else None,
    }

    return {
        "overall": overall,
        "by_cost_type": [
            {
                "ct": ct,
                "n": len(d["errors"]),
                "wmape_cell": round(d["abs_diff"] / d["actual"] * 100, 1) if d["actual"] else None,
                "actual": d["actual"],
            }
            for ct, d in cost_type_errors.items()
        ],
        "projects": project_records,
    }


def main():
    op = connect_readonly()
    en = connect_enriched()

    quote_sums = load_quote_sums(en)
    print(f"=== sidecar material_quote_lines ===")
    print(f"  cells: {len(quote_sums)}")
    print(f"  total quote amount: ₩{int(sum(quote_sums.values())):,}")

    projects = list_projects_for_backtest(op)
    print(f"  learnable projects (op DB module match): {len([p for p in projects if p['module_code']])}")

    # baseline
    s_base = load_actual_samples_v3(op, apply_corrections=False, drop_mixed=False)
    r_base = run_loo(s_base, projects)

    # corrected — work on a copy
    s_c = [dict(s) for s in load_actual_samples_v3(op, apply_corrections=False, drop_mixed=False)]
    s_c, stats = apply_quote_corrections(s_c, quote_sums)
    r_corr = run_loo(s_c, projects)

    op.close(); en.close()

    print(f"\n=== quote correction stats ===")
    print(f"  cells replaced (existing actual amount overridden): {stats['n_replaced']}")
    print(f"  cells added (new MAT cell from quote only):         {stats['n_added']}")
    print(f"  total |delta| amount:                                ₩{stats['delta_amount']:,}")
    print(f"  skipped (project not in learning pool):              {stats['skipped_no_project']}")

    print(f"\n=== Comparison ===")
    print(f"{'metric':38s}  {'BASELINE':>10s}  {'CORRECTED':>10s}  {'delta':>10s}")
    for k in ("total_wmape_proj_sum", "total_mae_pct", "total_median_pct", "material_wmape_proj_sum", "material_wmape_cell"):
        a = r_base["overall"].get(k)
        b = r_corr["overall"].get(k)
        if a is None or b is None:
            print(f"  {k:36s}  {'-':>10}  {'-':>10}")
            continue
        d = b - a
        print(f"  {k:36s}  {a:>9.1f}%  {b:>9.1f}%  {d:>+9.1f}pp")
    print(f"  {'total_within_20':36s}  {r_base['overall']['total_within_20']:>10}  {r_corr['overall']['total_within_20']:>10}")

    # Per-project material comparison
    print(f"\n=== Project-level material amount (top 8) ===")
    print(f"  {'project_code':30s}  {'actual_mat':>14s}  {'pred_mat':>14s}  {'corr_actual':>14s}  {'corr_pred':>14s}")
    base_proj = {r["project_code"]: r for r in r_base["projects"]}
    corr_proj = {r["project_code"]: r for r in r_corr["projects"]}
    for pc in sorted(base_proj):
        b = base_proj.get(pc, {})
        c = corr_proj.get(pc, {})
        print(f"  {pc[:30]:30s}  {b.get('actual_mat', 0):>14,}  {b.get('pred_mat', 0):>14,}  {c.get('actual_mat', 0):>14,}  {c.get('pred_mat', 0):>14,}")

    out = {
        "model_version": "v10.0-notion-v4-quote-corrected",
        "data_source": "operational cost_analysis.db (PR-1 cost_type) + sidecar material_quote_lines",
        "quote_correction_stats": stats,
        "baseline": r_base,
        "corrected": r_corr,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
