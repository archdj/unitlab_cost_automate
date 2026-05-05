"""v9 + v10 ensemble grid search and selection.

각 LOO 프로젝트에 대해 v9-knn / v10 두 예측을 합쳐 4가지 전략 비교:
  S1. simple_avg            — 0.5 / 0.5
  S2. conf_weighted         — w_v10 = v10 평균 cell confidence (0~1)
  S3. conditional           — v10에 warning 있으면 v9 only, 없으면 v10 only
  S4. grid                  — w in [0..1] step 0.05, MAE 최저 가중치

선택된 best ensemble을 cost_predictions에 v11.0-ensemble로 저장.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    DB_PATH,
    connect_readonly,
    list_projects_for_backtest,
    load_actual_samples,
)
from notion_cost_model import Pool, predict_for_module, MODEL_VERSION

V9_VERSION = "v9.0-hybrid-knn"
V11_VERSION = "v11.0-ensemble"


def fetch_v9_predictions(con: sqlite3.Connection) -> dict[int, int]:
    return {
        r["project_id"]: int(r["predicted_total"] or 0)
        for r in con.execute(
            "SELECT project_id, predicted_total FROM cost_predictions WHERE model_version=?",
            (V9_VERSION,),
        )
    }


def loo_pairs() -> list[dict]:
    """각 프로젝트의 v9 / v10 / actual 페어."""
    ro = connect_readonly()
    samples = load_actual_samples(ro)
    projects = list_projects_for_backtest(ro)
    v9 = fetch_v9_predictions(ro)
    ro.close()

    full_pool = Pool.from_samples(samples)

    rows = []
    for p in projects:
        pid = p["project_id"]
        if pid not in v9:
            continue
        train = full_pool.exclude_project(pid)
        v10_pred = predict_for_module(
            train,
            grade=p["grade"],
            pyeong=float(p["pyeong"] or 0),
            area_m2=float(p["floor_area_m2"]),
        )
        v10_amount = v10_pred["total"]
        v10_conf_avg = statistics.mean([c["confidence"] for c in v10_pred["breakdown"]]) if v10_pred["breakdown"] else 0
        rows.append({
            "project_id":  pid,
            "project_code": p["project_code"],
            "module_code": p["module_code"],
            "area_m2":     float(p["floor_area_m2"]),
            "grade":       p["grade"],
            "pyeong":      float(p["pyeong"] or 0),
            "actual":      int(p["actual_total"]),
            "v9":          v9[pid],
            "v10":         v10_amount,
            "v10_conf":    v10_conf_avg,
            "v10_warnings": list(v10_pred.get("warnings") or []),
            "v10_breakdown": v10_pred["breakdown"],
            "v10_lower":   v10_pred["confidence_lower"],
            "v10_upper":   v10_pred["confidence_upper"],
        })
    return rows


def metrics(amounts: list[int], actuals: list[int]) -> dict:
    errs = [abs(a - act) / act for a, act in zip(amounts, actuals)]
    n = len(errs)
    return {
        "n":            n,
        "mae_pct":      round(statistics.mean(errs) * 100, 1),
        "median_pct":   round(statistics.median(errs) * 100, 1),
        "weighted_mape_pct": round(
            sum(abs(a - act) for a, act in zip(amounts, actuals)) /
            sum(actuals) * 100, 1
        ) if sum(actuals) else None,
        "within_10":    sum(1 for e in errs if e <= 0.10),
        "within_20":    sum(1 for e in errs if e <= 0.20),
        "within_30":    sum(1 for e in errs if e <= 0.30),
    }


def evaluate_strategies(pairs: list[dict]) -> dict:
    actuals = [p["actual"] for p in pairs]

    # S1
    s1 = [round((p["v9"] + p["v10"]) / 2) for p in pairs]
    # S2
    s2 = [round(p["v9"] * (1 - p["v10_conf"]) + p["v10"] * p["v10_conf"]) for p in pairs]
    # S3
    s3 = [p["v9"] if p["v10_warnings"] else p["v10"] for p in pairs]
    # S4 grid
    best_w = 0.0
    best_metric = None
    grid_results = {}
    for w in [round(0.05 * i, 2) for i in range(21)]:  # 0.0 to 1.0 step 0.05
        amts = [round(p["v9"] * (1 - w) + p["v10"] * w) for p in pairs]
        m = metrics(amts, actuals)
        grid_results[w] = m
        if best_metric is None or m["mae_pct"] < best_metric["mae_pct"]:
            best_metric = m
            best_w = w
    s4 = [round(p["v9"] * (1 - best_w) + p["v10"] * best_w) for p in pairs]

    return {
        "v9":      {"amounts": [p["v9"] for p in pairs],  "metrics": metrics([p["v9"] for p in pairs], actuals)},
        "v10":     {"amounts": [p["v10"] for p in pairs], "metrics": metrics([p["v10"] for p in pairs], actuals)},
        "S1_simple_avg":    {"amounts": s1, "metrics": metrics(s1, actuals)},
        "S2_conf_weighted": {"amounts": s2, "metrics": metrics(s2, actuals)},
        "S3_conditional":   {"amounts": s3, "metrics": metrics(s3, actuals)},
        "S4_grid_optimal":  {"amounts": s4, "metrics": metrics(s4, actuals), "best_w": best_w},
        "grid_results":     grid_results,
    }


def print_summary(pairs: list[dict], evals: dict) -> None:
    print("=== Ensemble Strategy Comparison (LOO, n={}) ===".format(len(pairs)))
    print()
    print(f"{'strategy':25s} {'MAE':>7s} {'median':>8s} {'wMAPE':>7s} {'±10':>5s} {'±20':>5s} {'±30':>5s}")
    for name in ["v9", "v10", "S1_simple_avg", "S2_conf_weighted", "S3_conditional", "S4_grid_optimal"]:
        m = evals[name]["metrics"]
        extra = f" w={evals[name]['best_w']}" if name == "S4_grid_optimal" else ""
        print(f"  {name+extra:23s} {m['mae_pct']:>6.1f}% {m['median_pct']:>7.1f}% {m['weighted_mape_pct']:>6.1f}% {m['within_10']:>3d}/{m['n']} {m['within_20']:>3d}/{m['n']} {m['within_30']:>3d}/{m['n']}")

    print()
    print("프로젝트별 best 전략:")
    print(f"{'project':28s} {'actual':>8s} {'v9 err':>8s} {'v10 err':>8s} {'S1':>8s} {'S2':>8s} {'S3':>8s} {'S4':>8s}")
    for i, p in enumerate(pairs):
        actual = p["actual"]
        e9 = (p["v9"] - actual) / actual * 100
        e10 = (p["v10"] - actual) / actual * 100
        e1 = (evals["S1_simple_avg"]["amounts"][i] - actual) / actual * 100
        e2 = (evals["S2_conf_weighted"]["amounts"][i] - actual) / actual * 100
        e3 = (evals["S3_conditional"]["amounts"][i] - actual) / actual * 100
        e4 = (evals["S4_grid_optimal"]["amounts"][i] - actual) / actual * 100
        code = p["project_code"][:28]
        print(f"  {code:28s} {actual/1e6:>6.1f}M {e9:>+6.1f}% {e10:>+6.1f}% {e1:>+6.1f}% {e2:>+6.1f}% {e3:>+6.1f}% {e4:>+6.1f}%")


def save_best_ensemble(pairs: list[dict], best_amounts: list[int], strategy_label: str) -> int:
    rw = sqlite3.connect(str(DB_PATH))
    cur = rw.cursor()
    cur.execute("DELETE FROM cost_predictions WHERE model_version=?", (V11_VERSION,))
    inserted = 0
    for p, amt in zip(pairs, best_amounts):
        # module_type_id 조회
        mt_row = cur.execute(
            "SELECT module_type_id FROM module_types WHERE module_code=?",
            (p["module_code"],),
        ).fetchone()
        mt_id = mt_row[0] if mt_row else None
        actual = p["actual"]
        err_pct = (amt - actual) / actual * 100 if actual else None
        cur.execute("""
            INSERT INTO cost_predictions(
                project_id, module_type_id, predicted_total,
                confidence_lower, confidence_upper, breakdown,
                model_version, input_features, predicted_by,
                actual_amount, error_pct
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            p["project_id"], mt_id, amt,
            p["v10_lower"], p["v10_upper"],  # band는 v10 그대로
            json.dumps({
                "ensemble_strategy": strategy_label,
                "v9": p["v9"], "v10": p["v10"],
                "v10_breakdown": p["v10_breakdown"],
            }, ensure_ascii=False),
            V11_VERSION,
            json.dumps({"grade": p["grade"], "pyeong": p["pyeong"], "area_m2": p["area_m2"], "loo": True}, ensure_ascii=False),
            f"ensemble-{strategy_label}",
            actual,
            round(err_pct, 1) if err_pct is not None else None,
        ))
        inserted += 1
    rw.commit()
    rw.close()
    return inserted


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    pairs = loo_pairs()
    evals = evaluate_strategies(pairs)
    print_summary(pairs, evals)

    # n=8에서 MAE는 outlier 1건에 좌우되므로 median 우선, 동률 시 within_20 많은 것
    # S4 grid는 over-fit 위험 — 후보에서 제외
    candidates = ["S1_simple_avg", "S2_conf_weighted", "S3_conditional"]
    def score(name):
        m = evals[name]["metrics"]
        return (m["median_pct"], -m["within_20"], m["mae_pct"])
    best = min(candidates, key=score)
    inserted = save_best_ensemble(pairs, evals[best]["amounts"], best)
    print()
    print(f"=> Best strategy: {best}")
    print(f"   Saved to cost_predictions as {V11_VERSION}: {inserted} rows")


if __name__ == "__main__":
    main()
