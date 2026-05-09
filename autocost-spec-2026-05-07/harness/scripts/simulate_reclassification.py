"""raw_description 매핑 적용 시 자재 wMAPE 변화 시뮬레이션.

매핑 CSV(`harness/mapping/material_reclassification.csv`)의 키워드로
raw_description 매칭 → normalized_work_code 교체 → LOO backtest 재실행.

운영 DB는 read-only. 모든 변경은 in-memory 한정.
"""
from __future__ import annotations

import csv
import io
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.config import HARNESS_REPORTS, MODEL_VERSION
from src.db import connect_readonly, list_projects_for_backtest, workcode_normalize_map
from src.model import Pool, predict_for_module

REPORT_PATH = HARNESS_REPORTS / "reclassification_simulation.json"
MAPPING_CSV = ROOT / "harness" / "mapping" / "material_reclassification.csv"
LEARNABLE = ("approved", "promoted", "validated")


def load_mapping() -> list[dict]:
    rows = []
    with open(MAPPING_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if not r.get("pattern") or r["pattern"].startswith("#"):
                continue
            rows.append({
                "pattern":          r["pattern"].strip(),
                "target_work_code": r["target_work_code"].strip(),
                "confidence":       r["confidence"].strip(),
                "note":             (r.get("note") or "").strip(),
            })
    return rows


def reclassify(raw_description: str, current_wc: str, mapping: list[dict]) -> tuple[str, dict | None]:
    """raw_description에 매칭되는 패턴이 있으면 target_work_code로 교체."""
    if not raw_description:
        return current_wc, None
    for rule in mapping:
        if rule["pattern"] in raw_description:
            return rule["target_work_code"], rule
    return current_wc, None


def load_samples_with_reclassification(con, mapping: list[dict], norm: dict) -> tuple[list[dict], list[dict]]:
    """raw row 단위로 재분류 적용 후 (project, normalized_wc, cost_type) 합산."""
    placeholders = ",".join("?" * len(LEARNABLE))
    raw = list(con.execute(f"""
        SELECT
          ac.actual_cost_id,
          ac.project_id,
          ac.work_code_id,
          ac.raw_description,
          COALESCE(ac.source_ref, 'unknown') AS cost_type,
          ac.total_amount,
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
          AND ac.promotion_status IN ({placeholders})
    """, LEARNABLE))

    grouped: dict[tuple, dict] = {}
    reclassified_log: list[dict] = []
    for r in raw:
        nwc = norm.get(r["work_code_id"])
        if not nwc:
            continue
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            continue
        original_wc = nwc["normalized_code"]
        new_wc = original_wc
        rule_used = None
        # 자재(재료비)에만 재분류 적용
        if r["cost_type"] == "재료비":
            new_wc, rule_used = reclassify(r["raw_description"] or "", original_wc, mapping)
        if rule_used:
            reclassified_log.append({
                "actual_cost_id":   r["actual_cost_id"],
                "project_code":     r["project_code"],
                "raw_description":  r["raw_description"],
                "from_wc":          original_wc,
                "to_wc":            new_wc,
                "amount":           r["total_amount"],
                "rule_pattern":     rule_used["pattern"],
                "confidence":       rule_used["confidence"],
            })
        # target work_code의 work_name/category 찾기 (norm dict에서 임의로)
        # normalized_wc 가 변경된 경우 같은 wc인 다른 row의 메타 차용
        new_meta = nwc
        if new_wc != original_wc:
            # 같은 normalized_code 인 sample의 메타 찾기
            for v in norm.values():
                if v["normalized_code"] == new_wc:
                    new_meta = v
                    break
        key = (r["project_id"], new_wc, r["cost_type"])
        if key in grouped:
            grouped[key]["amount"] += int(r["total_amount"] or 0)
        else:
            grouped[key] = {
                "project_id":           r["project_id"],
                "project_code":         r["project_code"],
                "module_code":          r["module_code"],
                "normalized_work_code": new_wc,
                "work_name":            new_meta["normalized_name"],
                "category":             new_meta["category"],
                "cost_type":            r["cost_type"],
                "amount":               int(r["total_amount"] or 0),
                "floor_area_m2":        area,
                "pyeong":               float(r["pyeong"] or 0),
                "grade":                r["grade"],
                "structure_type":       r["structure_type"] or "STEEL",
            }

    samples = []
    for s in grouped.values():
        s["rate_per_m2"] = s["amount"] / s["floor_area_m2"] if s["floor_area_m2"] else 0
        if s["rate_per_m2"] <= 0:
            continue
        samples.append(s)
    return samples, reclassified_log


def run_loo(samples, projects, cost_type_filter=None) -> dict:
    """LOO backtest. cost_type_filter='재료비' 이면 자재만 측정."""
    full_pool = Pool.from_samples(samples)
    project_records = []
    workcode_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})
    cost_type_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})

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

        # cost_type_filter 적용
        if cost_type_filter:
            actual_filtered = sum(v for k, v in actual_kv.items() if k[1] == cost_type_filter)
            pred_filtered = sum(v for k, v in pred_kv.items() if k[1] == cost_type_filter)
            if actual_filtered <= 0:
                continue
            err_pct = (pred_filtered - actual_filtered) / actual_filtered * 100
            project_records.append({
                "project_code":  proj["project_code"],
                "actual":        actual_filtered,
                "predicted":     pred_filtered,
                "error_pct":     round(err_pct, 1),
                "abs_error_pct": round(abs(err_pct), 1),
            })
        else:
            pred_total = prediction["total"]
            err_pct = (pred_total - actual_total) / actual_total * 100
            project_records.append({
                "project_code":  proj["project_code"],
                "actual":        actual_total,
                "predicted":     pred_total,
                "error_pct":     round(err_pct, 1),
                "abs_error_pct": round(abs(err_pct), 1),
            })

    def agg(d):
        rows = []
        for k, v in d.items():
            errs = sorted(v["errors"])
            if not errs:
                continue
            rows.append({
                "key":               k,
                "sample_count":      len(errs),
                "mae_pct":           round(statistics.mean(errs) * 100, 1),
                "weighted_mape_pct": round(v["abs_diff"] / v["actual"] * 100, 1) if v["actual"] else None,
                "max_pct":           round(max(errs) * 100, 1),
                "actual_sum":        v["actual"],
                "abs_diff":          v["abs_diff"],
            })
        return sorted(rows, key=lambda x: -x["abs_diff"])

    abs_errs = sorted(r["abs_error_pct"] for r in project_records)
    n = len(abs_errs)
    abs_diff_total = sum(abs(r["predicted"] - r["actual"]) for r in project_records)
    actual_total_sum = sum(r["actual"] for r in project_records)
    overall = {
        "sample_count":          n,
        "mae_pct":               round(statistics.mean(abs_errs), 1) if n else 0,
        "weighted_mape_pct":     round(abs_diff_total / actual_total_sum * 100, 1) if actual_total_sum else None,
        "within_15_pct":         round(sum(1 for e in abs_errs if e <= 15) / n * 100, 1) if n else 0,
        "within_20_pct":         round(sum(1 for e in abs_errs if e <= 20) / n * 100, 1) if n else 0,
    }
    return {
        "overall":      overall,
        "by_workcode":  agg(workcode_errors),
        "by_cost_type": agg(cost_type_errors),
        "projects":     project_records,
    }


def main():
    con = connect_readonly()
    norm = workcode_normalize_map(con)
    projects = list_projects_for_backtest(con)
    mapping = load_mapping()
    print(f"매핑 룰 로드: {len(mapping)}개\n")

    # === BASELINE (재분류 없음) ===
    samples_baseline, _ = load_samples_with_reclassification(con, [], norm)
    print(f"baseline samples: {len(samples_baseline)}")
    baseline = run_loo(samples_baseline, projects)
    baseline_material = run_loo(samples_baseline, projects, cost_type_filter="재료비")

    # === 재분류 적용 ===
    samples_v2, reclassified_log = load_samples_with_reclassification(con, mapping, norm)
    print(f"v2 samples: {len(samples_v2)}")
    print(f"재분류된 row: {len(reclassified_log)}")
    print()
    print("=== 재분류 row 샘플 ===")
    for r in reclassified_log:
        print(f"  {r['from_wc']:12s} -> {r['to_wc']:12s}  {r['amount']/1e3:>6.0f}K  '{r['raw_description'][:40]}'")
    print()

    v2 = run_loo(samples_v2, projects)
    v2_material = run_loo(samples_v2, projects, cost_type_filter="재료비")

    # === 비교 출력 ===
    print(f"\n{'metric':40s} {'baseline':>10s} {'v2':>10s} {'delta':>10s}")
    for label, b, n in [
        ("전체 wMAPE",            baseline["overall"]["weighted_mape_pct"],   v2["overall"]["weighted_mape_pct"]),
        ("전체 MAE",              baseline["overall"]["mae_pct"],             v2["overall"]["mae_pct"]),
        ("전체 within±15%",       baseline["overall"]["within_15_pct"],       v2["overall"]["within_15_pct"]),
        ("전체 within±20%",       baseline["overall"]["within_20_pct"],       v2["overall"]["within_20_pct"]),
        ("자재 wMAPE",            baseline_material["overall"]["weighted_mape_pct"], v2_material["overall"]["weighted_mape_pct"]),
        ("자재 MAE",              baseline_material["overall"]["mae_pct"],     v2_material["overall"]["mae_pct"]),
    ]:
        delta = (n - b) if (b is not None and n is not None) else None
        print(f"  {label:38s} {b:>9.1f}% {n:>9.1f}% {delta:>+9.1f}pp")

    print("\n=== 자재 by_workcode 비교 (top 10 abs_diff) ===")
    by_wc_b = {x["key"]: x for x in baseline["by_workcode"]}
    by_wc_v = {x["key"]: x for x in v2["by_workcode"]}
    all_wcs = set(by_wc_b) | set(by_wc_v)
    rows_cmp = []
    for wc in all_wcs:
        b = by_wc_b.get(wc)
        n = by_wc_v.get(wc)
        rows_cmp.append({
            "wc":           wc,
            "b_wMAPE":      b["weighted_mape_pct"] if b else None,
            "n_wMAPE":      n["weighted_mape_pct"] if n else None,
            "b_actual":     b["actual_sum"] if b else 0,
            "n_actual":     n["actual_sum"] if n else 0,
            "b_abs":        b["abs_diff"] if b else 0,
            "n_abs":        n["abs_diff"] if n else 0,
        })
    rows_cmp.sort(key=lambda x: -max(x["b_abs"], x["n_abs"]))
    print(f"  {'wc':12s} {'b_wMAPE':>8s} {'v_wMAPE':>8s} {'b_abs':>7s} {'v_abs':>7s} {'b_act':>7s} {'v_act':>7s}")
    for r in rows_cmp[:15]:
        bw = f"{r['b_wMAPE']:.1f}%" if r["b_wMAPE"] is not None else "-"
        nw = f"{r['n_wMAPE']:.1f}%" if r["n_wMAPE"] is not None else "-"
        print(f"  {r['wc']:12s} {bw:>8s} {nw:>8s} {r['b_abs']/1e6:>6.1f}M {r['n_abs']/1e6:>6.1f}M "
              f"{r['b_actual']/1e6:>6.1f}M {r['n_actual']/1e6:>6.1f}M")

    out = {
        "model_version":         MODEL_VERSION,
        "mapping_rules":         len(mapping),
        "reclassified_rows":     len(reclassified_log),
        "reclassified_log":      reclassified_log,
        "baseline":              baseline,
        "baseline_material":     baseline_material,
        "v2":                    v2,
        "v2_material":           v2_material,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")
    con.close()


if __name__ == "__main__":
    main()
