"""LOO backtest v6 — corrections + quote 결합 효과 측정.

v3 (운영 DB N=8) 베이스에서 4-way 비교:
  v6.0 baseline:                 corrections OFF + quote OFF
  v6.1 corrections only (= v3):  corrections ON  + quote OFF
  v6.2 quote only       (= v4):  corrections OFF + quote ON
  v6.3 BOTH                  :   corrections ON  + quote ON

이전 단독 측정 (point):
  v3 corrections only: MAT cell +2.95pp 악화 (proj-sum?)
  v4 quote only:       MAT proj-sum -4.6pp 개선 (cell +3.5pp)

결합 시 효과 모름. 가능성:
  (a) 시너지 — corrections로 row 분류 정확화 + quote amount = 더 큰 개선
  (b) cancel — corrections noise + quote가 무효화
  (c) 악화 — 두 noise 합성
"""
from __future__ import annotations

import json
import sys
import statistics
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly,
    connect_enriched,
    load_actual_samples_v3,
    list_projects_for_backtest,
)
from notion_cost_model import Pool, predict_for_module
from backtest_v4_quote_corrected import load_quote_sums, apply_quote_corrections, run_loo


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "backtest_v6_combined.json"


def measure(samples, projects, label):
    r = run_loo(samples, projects)
    overall = r["overall"]
    return {
        "label": label,
        "n": overall["n"],
        "total_wmape": overall["total_wmape_proj_sum"],
        "total_mae": overall["total_mae_pct"],
        "total_median": overall["total_median_pct"],
        "total_within_20": overall["total_within_20"],
        "mat_proj_sum": overall["material_wmape_proj_sum"],
        "mat_cell": overall["material_wmape_cell"],
    }


def main():
    op = connect_readonly()
    en = connect_enriched()

    quote_sums = load_quote_sums(en)
    projects = list_projects_for_backtest(op)
    print(f"=== Setup ===")
    print(f"  quote cells: {len(quote_sums)}")
    print(f"  projects: {len([p for p in projects if p['module_code']])}")

    # 4 conditions
    print("\n=== Loading samples for each condition ===")
    s_baseline = load_actual_samples_v3(op, apply_corrections=False, drop_mixed=False)
    s_corr = load_actual_samples_v3(op, apply_corrections=True, corrections_con=en, drop_mixed=False)

    s_quote = [dict(s) for s in load_actual_samples_v3(op, apply_corrections=False, drop_mixed=False)]
    s_quote, _ = apply_quote_corrections(s_quote, quote_sums)

    s_both = [dict(s) for s in load_actual_samples_v3(op, apply_corrections=True, corrections_con=en, drop_mixed=False)]
    s_both, _ = apply_quote_corrections(s_both, quote_sums)

    print(f"  baseline:                 {len(s_baseline)} samples")
    print(f"  corrections only:         {len(s_corr)}")
    print(f"  quote only:               {len(s_quote)}")
    print(f"  both:                     {len(s_both)}")

    op.close(); en.close()

    # Measure
    print("\n=== Running LOO for each condition ===")
    r_base = measure(s_baseline, projects, "v6.0 baseline (corrections=OFF, quote=OFF)")
    r_corr = measure(s_corr, projects, "v6.1 corrections only")
    r_quote = measure(s_quote, projects, "v6.2 quote only (= v4)")
    r_both = measure(s_both, projects, "v6.3 BOTH (corrections + quote)")

    print(f"\n{'condition':50s} {'n':>3s} {'tot_wmape':>10s} {'mat_proj':>10s} {'mat_cell':>10s} {'hit':>6s}")
    for r in (r_base, r_corr, r_quote, r_both):
        print(f"  {r['label']:48s} {r['n']:>3} {r['total_wmape']:>9.1f}% {r['mat_proj_sum']:>9.1f}% {r['mat_cell']:>9.1f}% {r['total_within_20']:>6}")

    # Deltas vs baseline
    print(f"\n=== Delta vs baseline (v6.0) ===")
    print(f"{'condition':50s} {'mat_proj Δ':>10s} {'mat_cell Δ':>10s} {'tot_wmape Δ':>11s}")
    for r in (r_corr, r_quote, r_both):
        dpsm = r['mat_proj_sum'] - r_base['mat_proj_sum']
        dcell = r['mat_cell'] - r_base['mat_cell']
        dtot = r['total_wmape'] - r_base['total_wmape']
        print(f"  {r['label']:48s} {dpsm:>+9.1f}pp {dcell:>+9.1f}pp {dtot:>+10.1f}pp")

    # Save
    out = {
        "model_version": "v10.0-notion-v6-combined",
        "data_source": "operational cost_analysis.db (PR-1) + sidecar corrections + sidecar quote_lines",
        "v6_0_baseline": r_base,
        "v6_1_corrections_only": r_corr,
        "v6_2_quote_only": r_quote,
        "v6_3_both": r_both,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
