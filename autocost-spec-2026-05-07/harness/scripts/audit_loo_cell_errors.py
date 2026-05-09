"""LOO 시 셀 단위 오차 추적.

backtest와 동일한 메커니즘으로, 각 LOO 회차마다 셀별 actual / predicted /
err 를 dump하고 err 상위 셀의 raw row 까지 추출. baseline의 max_pct=2940%
같은 폭주가 어디서 오는지 식별.

Usage:
    python harness/scripts/audit_loo_cell_errors.py
"""
from __future__ import annotations

import io
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.config import HARNESS_REPORTS
from src.db import connect_readonly, list_projects_for_backtest, load_actual_samples, workcode_normalize_map
from src.model import Pool, predict_for_module

REPORT_PATH = HARNESS_REPORTS / "loo_cell_error_audit.json"

# 자재 cost_type 만 우선 추적
COST_TYPE_TARGET = "재료비"
TOP_N_PER_PROJECT = 10
TOP_N_OVERALL = 30


def cell_raw_rows(con, project_id, work_code_id_list, cost_type):
    placeholders = ",".join("?" * len(work_code_id_list))
    rows = list(con.execute(f"""
        SELECT
          ac.actual_cost_id,
          ac.actual_quantity, ac.unit, ac.unit_price, ac.total_amount,
          ac.vendor_name, ac.raw_description, ac.material_id
        FROM actual_costs ac
        WHERE ac.project_id = ?
          AND ac.work_code_id IN ({placeholders})
          AND ac.source_ref = ?
          AND ac.total_amount > 0
          AND ac.promotion_status IN ('approved','promoted','validated')
    """, [project_id, *work_code_id_list, cost_type]))
    return [dict(r) for r in rows]


def main():
    con = connect_readonly()
    samples = load_actual_samples(con)
    norm = workcode_normalize_map(con)
    projects = list_projects_for_backtest(con)

    # work_code_id 그룹: normalized_code -> [work_code_id]
    norm_to_ids: dict[str, list[int]] = defaultdict(list)
    for wid, info in norm.items():
        norm_to_ids[info["normalized_code"]].append(wid)

    full_pool = Pool.from_samples(samples)

    cell_errors: list[dict] = []
    project_cells: dict[str, list[dict]] = {}
    for proj in projects:
        pid = proj["project_id"]
        train_pool = full_pool.exclude_project(pid)

        actual_kv: dict[tuple, int] = defaultdict(int)
        for s in samples:
            if s["project_id"] == pid and s["cost_type"] == COST_TYPE_TARGET:
                actual_kv[(s["normalized_work_code"], s["cost_type"])] += s["amount"]
        if not actual_kv:
            continue

        prediction = predict_for_module(
            train_pool,
            grade=proj["grade"],
            pyeong=float(proj["pyeong"] or 0),
            area_m2=float(proj["floor_area_m2"]),
        )
        pred_kv = {(b["work_code"], b["cost_type"]): b for b in prediction["breakdown"]
                   if b["cost_type"] == COST_TYPE_TARGET}

        proj_cell_rows: list[dict] = []
        for k in set(actual_kv) | set(pred_kv):
            wc, ct = k
            a = actual_kv.get(k, 0)
            pred_obj = pred_kv.get(k)
            p = pred_obj["amount"] if pred_obj else 0
            if a == 0 and p == 0:
                continue
            err = abs(p - a) / a if a > 0 else None
            proj_cell_rows.append({
                "project_code":     proj["project_code"],
                "work_code":        wc,
                "cost_type":        ct,
                "actual":           a,
                "predicted":        p,
                "abs_diff":         abs(p - a),
                "err_pct":          round(err * 100, 1) if err is not None else None,
                "applicability":    pred_obj["applicability"] if pred_obj else None,
                "tier_used":        pred_obj["tier_used"] if pred_obj else None,
                "applicability_tier": pred_obj["applicability_tier"] if pred_obj else None,
                "rate_per_m2_pred": pred_obj["rate_per_m2"] if pred_obj else None,
                "rate_per_m2_actual": round(a / float(proj["floor_area_m2"]), 0) if proj["floor_area_m2"] else None,
                "sample_count":     pred_obj["sample_count"] if pred_obj else None,
                "raw_rows":         cell_raw_rows(con, pid, norm_to_ids.get(wc, []), ct),
            })
        proj_cell_rows.sort(key=lambda x: -(x["err_pct"] or 0))
        project_cells[proj["project_code"]] = proj_cell_rows[:TOP_N_PER_PROJECT]
        cell_errors.extend(proj_cell_rows)

    cell_errors.sort(key=lambda x: -(x["err_pct"] or 0))
    top_overall = cell_errors[:TOP_N_OVERALL]

    # err 분포 통계
    err_values = [c["err_pct"] for c in cell_errors if c["err_pct"] is not None]
    err_values.sort()
    pcts = {}
    if err_values:
        n = len(err_values)
        for q in (0.5, 0.75, 0.9, 0.95, 0.99):
            pcts[f"p{int(q*100)}"] = err_values[int(q * (n - 1))]

    # work_code별 err 분포 (상위 10)
    by_wc: dict[str, dict] = defaultdict(lambda: {"errs": [], "abs_diff": 0, "actual": 0, "n_overpred": 0, "n_underpred": 0})
    for c in cell_errors:
        if c["err_pct"] is None:
            continue
        rec = by_wc[c["work_code"]]
        rec["errs"].append(c["err_pct"])
        rec["abs_diff"] += c["abs_diff"]
        rec["actual"] += c["actual"]
        if c["predicted"] > c["actual"]:
            rec["n_overpred"] += 1
        else:
            rec["n_underpred"] += 1

    by_wc_summary = []
    for wc, rec in by_wc.items():
        errs = sorted(rec["errs"])
        n = len(errs)
        by_wc_summary.append({
            "work_code":    wc,
            "n_cells":      n,
            "median_err":   errs[n // 2],
            "p90_err":      errs[int(0.9 * (n - 1))] if n else None,
            "max_err":      errs[-1] if errs else None,
            "weighted_mape": round(rec["abs_diff"] / rec["actual"] * 100, 1) if rec["actual"] else None,
            "n_overpred":   rec["n_overpred"],
            "n_underpred":  rec["n_underpred"],
            "abs_diff":     rec["abs_diff"],
            "actual_sum":   rec["actual"],
        })
    by_wc_summary.sort(key=lambda x: -x["abs_diff"])

    print(f"\n=== {COST_TYPE_TARGET} LOO cell errors ===")
    print(f"total cells: {len(cell_errors)}")
    print(f"err percentiles: {pcts}")
    print()
    print("=== work_code별 wMAPE / over vs under ===")
    print(f"  {'wc':12s} {'n':>3s} {'median':>7s} {'p90':>8s} {'max':>9s} {'wMAPE':>7s} {'over/under':>10s}")
    for w in by_wc_summary[:15]:
        print(f"  {w['work_code']:12s} {w['n_cells']:>3d} "
              f"{w['median_err']:>6.1f}% {w['p90_err']:>7.1f}% {w['max_err']:>8.1f}% "
              f"{w['weighted_mape']:>6.1f}% {w['n_overpred']:>3d}/{w['n_underpred']:<6d}")
    print()
    print(f"=== top {TOP_N_OVERALL} cell errors ===")
    for c in top_overall:
        print(f"  {c['project_code'][:24]:24s} {c['work_code']:10s} "
              f"a={c['actual']/1e6:>5.1f}M  p={c['predicted']/1e6:>5.1f}M  "
              f"err={c['err_pct']:>7.1f}%  appl={c['applicability']}  rows={len(c['raw_rows'])}")

    out = {
        "cost_type_target":  COST_TYPE_TARGET,
        "n_cells":           len(cell_errors),
        "err_percentiles":   pcts,
        "by_work_code":      by_wc_summary,
        "top_cells":         top_overall,
        "by_project":        project_cells,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH}")
    con.close()


if __name__ == "__main__":
    main()
