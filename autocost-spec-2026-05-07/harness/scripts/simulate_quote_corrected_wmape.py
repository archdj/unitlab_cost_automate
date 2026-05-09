"""견적서 amount 로 자재 actual 을 보정 시 wMAPE 변화 시뮬레이션.

(project, work_code) 셀별로:
- 견적서 amount sum (sidecar material_quote_lines)
- actual amount (운영 DB actual_costs 재료비)
견적서 amount 가 있는 셀은 actual 을 quote_sum 으로 대체. 없는 셀은 그대로.
이후 LOO backtest 자재 wMAPE 측정.

해석:
- 큰 폭 개선 → 데이터 품질(자재 분류 누락)이 wMAPE 39.9%의 진짜 병목.
- 미미하면 모델 fit 한계가 더 큰 원인.
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

ENRICHED_DB = ROOT / "harness" / "data" / "autocost_enriched.db"

LOG: list[str] = []
def log(s=""): LOG.append(str(s))


def load_quote_sums() -> dict[tuple[str, str], float]:
    """sidecar에서 (project_code, work_code) → quote amount sum."""
    out: dict[tuple, float] = defaultdict(float)
    con = sqlite3.connect(ENRICHED_DB)
    for r in con.execute("""
        SELECT project_code, work_code, SUM(amount)
        FROM material_quote_lines
        WHERE project_code IS NOT NULL AND work_code IS NOT NULL AND amount IS NOT NULL
        GROUP BY project_code, work_code
    """):
        out[(r[0], r[1])] = float(r[2] or 0)
    con.close()
    return out


def load_samples(corrected: dict[tuple[str, str], float] | None = None):
    """운영 DB에서 LOO 학습 입력 로드. corrected 가 있으면 자재 actual을 그 값으로 대체."""
    con = sqlite3.connect(f"file:{OPERATIONAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    norm = workcode_normalize_map(con)

    raw = list(con.execute("""
        SELECT
          ac.project_id,
          ac.work_code_id,
          COALESCE(ac.source_ref, 'unknown') AS cost_type,
          SUM(ac.total_amount) AS amount,
          p.project_code,
          mt.module_code,
          mt.floor_area_m2,
          mt.pyeong,
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
        nwc = norm[r["work_code_id"]]
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            continue
        wc = nwc["normalized_code"]
        key = (r["project_id"], wc, r["cost_type"])
        if key in grouped:
            grouped[key]["amount"] += int(r["amount"] or 0)
        else:
            grouped[key] = {
                "project_id":           r["project_id"],
                "project_code":         r["project_code"],
                "module_code":          r["module_code"],
                "normalized_work_code": wc,
                "work_name":            nwc["normalized_name"],
                "category":             nwc["category"],
                "cost_type":            r["cost_type"],
                "amount":               int(r["amount"] or 0),
                "floor_area_m2":        area,
                "pyeong":               float(r["pyeong"] or 0),
                "grade":                r["grade"],
                "structure_type":       r["structure_type"] or "STEEL",
            }

    # corrected 적용 — 자재(재료비) 셀만
    n_corrected = 0
    correction_amount_total = 0
    if corrected:
        # project_code 기준 매핑 위해 project_code별로 그룹
        pc_to_pid: dict[str, int] = {}
        for s in grouped.values():
            pc_to_pid[s["project_code"]] = s["project_id"]

        for (project_code, work_code), quote_sum in corrected.items():
            pid = pc_to_pid.get(project_code)
            if pid is None:
                continue
            key = (pid, work_code, "재료비")
            if key in grouped:
                old = grouped[key]["amount"]
                grouped[key]["amount"] = int(quote_sum)
                n_corrected += 1
                correction_amount_total += abs(quote_sum - old)
            else:
                # 신규 셀 (actual 에 없던 work_code) — 학습용으로 추가
                # 임의 메타가 필요한데, 같은 project의 다른 셀에서 복사
                meta = next((s for s in grouped.values() if s["project_id"] == pid), None)
                if not meta:
                    continue
                grouped[key] = {
                    "project_id":           pid,
                    "project_code":         project_code,
                    "module_code":          meta["module_code"],
                    "normalized_work_code": work_code,
                    "work_name":            work_code,
                    "category":             "?",
                    "cost_type":            "재료비",
                    "amount":               int(quote_sum),
                    "floor_area_m2":        meta["floor_area_m2"],
                    "pyeong":               meta["pyeong"],
                    "grade":                meta["grade"],
                    "structure_type":       meta["structure_type"],
                }
                n_corrected += 1
                correction_amount_total += quote_sum

    samples = []
    for s in grouped.values():
        s["rate_per_m2"] = s["amount"] / s["floor_area_m2"] if s["floor_area_m2"] else 0
        if s["rate_per_m2"] <= 0:
            continue
        samples.append(s)
    con.close()
    return samples, n_corrected, correction_amount_total


def list_projects():
    con = sqlite3.connect(f"file:{OPERATIONAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = list(con.execute("""
        SELECT p.project_id, p.project_code, p.project_name,
               mt.module_code, mt.floor_area_m2, mt.pyeong,
               UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac          ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm  ON p.project_id = pm.project_id
        LEFT JOIN module_types mt     ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        GROUP BY p.project_id
        HAVING actual_total > 1000000
        ORDER BY actual_total DESC
    """))
    con.close()
    return [dict(r) for r in rows]


def run_loo(samples, projects):
    full_pool = Pool.from_samples(samples)
    workcode_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})
    cost_type_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})
    project_records = []

    for proj in projects:
        pid = proj["project_id"]
        train_pool = full_pool.exclude_project(pid)
        actual_kv: dict[tuple, int] = defaultdict(int)
        for s in samples:
            if s["project_id"] == pid:
                actual_kv[(s["normalized_work_code"], s["cost_type"])] += s["amount"]
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
            a, p = actual_kv.get(k, 0), pred_kv.get(k, 0)
            wc, ct = k
            if a > 0:
                err = abs(p - a) / a
                workcode_errors[wc]["errors"].append(err)
                workcode_errors[wc]["abs_diff"] += abs(p - a)
                workcode_errors[wc]["actual"] += a
                cost_type_errors[ct]["errors"].append(err)
                cost_type_errors[ct]["abs_diff"] += abs(p - a)
                cost_type_errors[ct]["actual"] += a

        # 자재 wMAPE (project-sum)
        actual_mat = sum(v for k, v in actual_kv.items() if k[1] == "재료비")
        pred_mat = sum(v for k, v in pred_kv.items() if k[1] == "재료비")
        project_records.append({
            "project_code": proj["project_code"],
            "actual_total": actual_total,
            "pred_total":   prediction["total"],
            "actual_mat":   actual_mat,
            "pred_mat":     pred_mat,
        })

    # 집계
    def overall_metrics(records, key_a, key_p):
        abs_diff = sum(abs(r[key_p] - r[key_a]) for r in records if r[key_a] > 0)
        actual_sum = sum(r[key_a] for r in records if r[key_a] > 0)
        return round(abs_diff / actual_sum * 100, 1) if actual_sum else None

    return {
        "overall_wmape":     overall_metrics(project_records, "actual_total", "pred_total"),
        "material_wmape":    overall_metrics(project_records, "actual_mat", "pred_mat"),
        "by_workcode":       sorted([
            {
                "wc":   wc,
                "n":    len(v["errors"]),
                "wmape": round(v["abs_diff"] / v["actual"] * 100, 1) if v["actual"] else None,
                "abs_diff": v["abs_diff"],
                "actual":   v["actual"],
            }
            for wc, v in workcode_errors.items()
        ], key=lambda x: -x["abs_diff"]),
        "by_cost_type":      sorted([
            {
                "ct":   ct,
                "n":    len(v["errors"]),
                "wmape": round(v["abs_diff"] / v["actual"] * 100, 1) if v["actual"] else None,
                "abs_diff": v["abs_diff"],
                "actual":   v["actual"],
            }
            for ct, v in cost_type_errors.items()
        ], key=lambda x: -x["abs_diff"]),
        "projects":          project_records,
    }


def main():
    quote_sums = load_quote_sums()
    log(f"=== sidecar quote sums ===")
    log(f"  cells: {len(quote_sums)}")
    log(f"  total quote amount: {sum(quote_sums.values())/1e6:.1f}M")
    log()

    projects = list_projects()
    log(f"projects: {len(projects)}")

    # === BASELINE ===
    samples_b, _, _ = load_samples(corrected=None)
    log(f"baseline samples: {len(samples_b)}")
    base = run_loo(samples_b, projects)

    # === CORRECTED ===
    samples_c, n_corrected, correction_amt = load_samples(corrected=quote_sums)
    log(f"corrected samples: {len(samples_c)}  (n_corrected_cells={n_corrected}, total_correction={correction_amt/1e6:.1f}M)")
    corr = run_loo(samples_c, projects)

    log()
    log(f"=== wMAPE 비교 ===")
    log(f"  {'metric':25s} {'baseline':>10s} {'corrected':>10s} {'delta':>8s}")
    for label, b, c in [
        ("전체 wMAPE",       base["overall_wmape"],     corr["overall_wmape"]),
        ("자재 wMAPE",       base["material_wmape"],    corr["material_wmape"]),
    ]:
        delta = (c - b) if (b is not None and c is not None) else None
        log(f"  {label:25s} {b:>9.1f}% {c:>9.1f}% {delta:>+7.1f}pp")
    log()

    # by_cost_type
    log("=== cost_type 비교 ===")
    log(f"  {'ct':15s} {'b_n':>3s} {'b_wMAPE':>8s} {'c_n':>3s} {'c_wMAPE':>8s}")
    b_ct = {x["ct"]: x for x in base["by_cost_type"]}
    c_ct = {x["ct"]: x for x in corr["by_cost_type"]}
    for ct in set(b_ct) | set(c_ct):
        b = b_ct.get(ct, {})
        c = c_ct.get(ct, {})
        log(f"  {ct:15s} {b.get('n',0):>3d} {b.get('wmape', '-'):>7}% "
            f"{c.get('n',0):>3d} {c.get('wmape', '-'):>7}%")
    log()

    # by_workcode (자재만 보고 싶은데 cost_type 분리 안됨 — work_code별 통합)
    log("=== work_code 비교 (top 12 abs_diff) ===")
    log(f"  {'wc':12s} {'b_wMAPE':>8s} {'c_wMAPE':>8s} {'b_abs':>7s} {'c_abs':>7s}")
    b_wc = {x["wc"]: x for x in base["by_workcode"]}
    c_wc = {x["wc"]: x for x in corr["by_workcode"]}
    all_wcs = set(b_wc) | set(c_wc)
    rows = []
    for wc in all_wcs:
        b = b_wc.get(wc, {})
        c = c_wc.get(wc, {})
        rows.append({
            "wc": wc,
            "b_wmape": b.get("wmape"),
            "c_wmape": c.get("wmape"),
            "b_abs": b.get("abs_diff", 0),
            "c_abs": c.get("abs_diff", 0),
        })
    rows.sort(key=lambda x: -max(x["b_abs"], x["c_abs"]))
    for r in rows[:12]:
        bw = f"{r['b_wmape']:.1f}%" if r["b_wmape"] is not None else "-"
        cw = f"{r['c_wmape']:.1f}%" if r["c_wmape"] is not None else "-"
        log(f"  {r['wc']:12s} {bw:>8s} {cw:>8s} {r['b_abs']/1e6:>6.1f}M {r['c_abs']/1e6:>6.1f}M")

    out = ROOT / "harness" / "reports" / "_quote_correction_simulation.txt"
    out.write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        out = ROOT / "harness" / "reports" / "_quote_correction_simulation.txt"
        out.write_text("\n".join(LOG), encoding="utf-8")
