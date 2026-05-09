"""트리거 재협상 근거용 baseline metrics 통합 측정.

여러 measurement 정의를 한 번에 산출:
1. project-sum 단위 wMAPE (전체/자재)
2. cell-단위 wMAPE (cost_type별)
3. hit-rate within±10/15/20/25
4. work_code별 wMAPE (자재 한정)
5. project별 abs_error_pct
"""
from __future__ import annotations

import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.config import OPERATIONAL_DB
from src.db import workcode_normalize_map
from src.model import Pool, predict_for_module

LOG: list[str] = []
def log(s=""): LOG.append(str(s))


def main():
    con = sqlite3.connect(f"file:{OPERATIONAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    norm = workcode_normalize_map(con)

    # samples
    raw = list(con.execute("""
        SELECT
          ac.project_id, ac.work_code_id,
          COALESCE(ac.source_ref, 'unknown') AS cost_type,
          SUM(ac.total_amount) AS amount,
          p.project_code, mt.module_code, mt.floor_area_m2, mt.pyeong,
          UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
          mt.structure_type
        FROM actual_costs ac
        JOIN projects p              ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ('approved','promoted','validated')
        GROUP BY ac.project_id, ac.work_code_id, COALESCE(ac.source_ref, 'unknown')
    """))

    grouped: dict[tuple, dict] = {}
    for r in raw:
        nwc = norm.get(r["work_code_id"])
        if not nwc:
            continue
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            continue
        wc = nwc["normalized_code"]
        key = (r["project_id"], wc, r["cost_type"])
        if key in grouped:
            grouped[key]["amount"] += int(r["amount"] or 0)
        else:
            grouped[key] = {
                "project_id": r["project_id"], "project_code": r["project_code"],
                "module_code": r["module_code"], "normalized_work_code": wc,
                "work_name": wc, "category": nwc["category"], "cost_type": r["cost_type"],
                "amount": int(r["amount"] or 0), "floor_area_m2": area,
                "pyeong": float(r["pyeong"] or 0), "grade": r["grade"],
                "structure_type": r["structure_type"] or "STEEL",
            }
    samples = []
    for s in grouped.values():
        s["rate_per_m2"] = s["amount"] / s["floor_area_m2"]
        if s["rate_per_m2"] > 0:
            samples.append(s)

    projects = [dict(r) for r in con.execute("""
        SELECT p.project_id, p.project_code, mt.module_code,
               mt.floor_area_m2, mt.pyeong,
               UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac          ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm  ON p.project_id = pm.project_id
        LEFT JOIN module_types mt     ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0 AND mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        GROUP BY p.project_id
        HAVING actual_total > 1000000
        ORDER BY actual_total DESC
    """)]

    full_pool = Pool.from_samples(samples)

    # LOO
    project_records = []
    cell_errors_by_ct: dict[str, dict] = defaultdict(lambda: {"abs": 0, "actual": 0, "n": 0, "errs": []})
    cell_errors_by_wc_mat: dict[str, dict] = defaultdict(lambda: {"abs": 0, "actual": 0, "n": 0, "errs": []})

    for proj in projects:
        pid = proj["project_id"]
        train = full_pool.exclude_project(pid)
        actual_kv: dict = defaultdict(int)
        for s in samples:
            if s["project_id"] == pid:
                actual_kv[(s["normalized_work_code"], s["cost_type"])] += s["amount"]
        if not actual_kv:
            continue
        pred = predict_for_module(train, grade=proj["grade"],
                                  pyeong=float(proj["pyeong"] or 0),
                                  area_m2=float(proj["floor_area_m2"]))
        pred_kv = {(b["work_code"], b["cost_type"]): b["amount"] for b in pred["breakdown"]}

        for k in set(actual_kv) | set(pred_kv):
            wc, ct = k
            a = actual_kv.get(k, 0)
            p = pred_kv.get(k, 0)
            if a > 0:
                err = abs(p - a) / a
                cell_errors_by_ct[ct]["abs"] += abs(p - a)
                cell_errors_by_ct[ct]["actual"] += a
                cell_errors_by_ct[ct]["n"] += 1
                cell_errors_by_ct[ct]["errs"].append(err)
                if ct == "재료비":
                    cell_errors_by_wc_mat[wc]["abs"] += abs(p - a)
                    cell_errors_by_wc_mat[wc]["actual"] += a
                    cell_errors_by_wc_mat[wc]["n"] += 1
                    cell_errors_by_wc_mat[wc]["errs"].append(err)

        actual_tot = sum(actual_kv.values())
        pred_tot   = pred["total"]
        actual_mat = sum(v for k, v in actual_kv.items() if k[1] == "재료비")
        pred_mat   = sum(v for k, v in pred_kv.items()   if k[1] == "재료비")
        project_records.append({
            "project_code": proj["project_code"],
            "actual_total": actual_tot, "pred_total": pred_tot,
            "actual_mat":   actual_mat, "pred_mat":   pred_mat,
            "err_total_pct": (pred_tot - actual_tot) / actual_tot * 100,
            "err_mat_pct":   ((pred_mat - actual_mat) / actual_mat * 100) if actual_mat > 0 else None,
        })

    log(f"=== 학습 프로젝트: {len(project_records)} ===\n")

    # 1. project-sum wMAPE
    def proj_wmape(records, key_a, key_p):
        num = sum(abs(r[key_p] - r[key_a]) for r in records if r[key_a] > 0)
        den = sum(r[key_a] for r in records if r[key_a] > 0)
        return (num / den * 100) if den else None

    log("=== 1. PROJECT-SUM wMAPE ===")
    log(f"  전체 wMAPE         : {proj_wmape(project_records, 'actual_total', 'pred_total'):.1f}%")
    log(f"  자재 wMAPE         : {proj_wmape(project_records, 'actual_mat', 'pred_mat'):.1f}%")
    log()

    # 2. cell-단위 wMAPE
    log("=== 2. CELL-단위 wMAPE (cost_type별) ===")
    log(f"  {'ct':15s} {'n':>4s} {'wMAPE':>7s} {'mean_err':>8s} {'median':>8s} {'max':>7s}")
    for ct, v in sorted(cell_errors_by_ct.items(), key=lambda x: -x[1]["abs"]):
        wm = v["abs"] / v["actual"] * 100 if v["actual"] else 0
        errs = v["errs"]
        mean = statistics.mean(errs) * 100 if errs else 0
        med = statistics.median(errs) * 100 if errs else 0
        mx = max(errs) * 100 if errs else 0
        log(f"  {ct:15s} {v['n']:>4d} {wm:>6.1f}% {mean:>7.1f}% {med:>7.1f}% {mx:>6.1f}%")
    log()

    # 3. hit-rate (project-level 전체 abs_error_pct 기준)
    abs_errs_total = sorted(abs(r["err_total_pct"]) for r in project_records)
    abs_errs_mat = sorted(abs(r["err_mat_pct"]) for r in project_records if r["err_mat_pct"] is not None)
    n_t, n_m = len(abs_errs_total), len(abs_errs_mat)

    def hit_rate(errs, threshold):
        if not errs:
            return 0
        return sum(1 for e in errs if e <= threshold) / len(errs) * 100

    log("=== 3. PROJECT-LEVEL HIT-RATE (within ±N%) ===")
    log(f"  {'threshold':10s} {'전체':>8s} {'자재':>8s}")
    for thr in [10, 15, 20, 25, 30]:
        ht = hit_rate(abs_errs_total, thr)
        hm = hit_rate(abs_errs_mat, thr)
        log(f"  ±{thr:>3d}%      {ht:>7.1f}% {hm:>7.1f}%")
    log()

    # 4. work_code별 자재 wMAPE
    log("=== 4. WORK_CODE별 자재 wMAPE (priority desc) ===")
    log(f"  {'wc':12s} {'n':>3s} {'wMAPE':>7s} {'abs':>7s} {'actual':>8s}")
    sorted_wcs = sorted(cell_errors_by_wc_mat.items(), key=lambda x: -x[1]["abs"])
    for wc, v in sorted_wcs:
        wm = v["abs"] / v["actual"] * 100 if v["actual"] else 0
        log(f"  {wc:12s} {v['n']:>3d} {wm:>6.1f}% {v['abs']/1e6:>6.1f}M {v['actual']/1e6:>7.1f}M")
    log()

    # 5. project-level 상세
    log("=== 5. PROJECT 상세 ===")
    log(f"  {'project':28s} {'actual':>9s} {'pred':>9s} {'err':>7s} {'mat_err':>8s}")
    for p in project_records:
        log(f"  {p['project_code'][:28]:28s} {p['actual_total']/1e6:>7.1f}M "
            f"{p['pred_total']/1e6:>7.1f}M {p['err_total_pct']:>+6.1f}% "
            f"{p['err_mat_pct'] or 0:>+7.1f}%")

    out = ROOT / "harness" / "reports" / "_baseline_metrics_consolidated.txt"
    out.write_text("\n".join(LOG), encoding="utf-8")
    con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"ERROR: {e}\n{traceback.format_exc()}")
        out = ROOT / "harness" / "reports" / "_baseline_metrics_consolidated.txt"
        out.write_text("\n".join(LOG), encoding="utf-8")
