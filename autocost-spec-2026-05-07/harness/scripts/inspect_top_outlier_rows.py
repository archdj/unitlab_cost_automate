"""LOO 셀 오차 top 10 의 raw row 자세히 dump."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPORT = ROOT / "harness" / "reports" / "loo_cell_error_audit.json"
data = json.loads(REPORT.read_text(encoding="utf-8"))

print("=== TOP 10 outlier 셀의 raw row 상세 ===\n")
for c in data["top_cells"][:10]:
    print(f"[{c['project_code']}] {c['work_code']} ({c['cost_type']})")
    print(f"  actual={c['actual']/1e6:.2f}M  predicted={c['predicted']/1e6:.2f}M  err={c['err_pct']}%  appl={c['applicability']}")
    print(f"  rate_per_m2: actual={c['rate_per_m2_actual']}  pred={c['rate_per_m2_pred']}  (학습 셀 {c['sample_count']}개)")
    for r in c["raw_rows"]:
        amt = r["total_amount"]
        qty = r["actual_quantity"]
        unit = r["unit"] or "-"
        up = r["unit_price"]
        vendor = (r["vendor_name"] or "")[:30]
        desc = (r["raw_description"] or "")[:60]
        mat = r["material_id"]
        print(f"    - {amt/1000:>7.0f}K  q={qty} {unit:6s} up={up}  mat_id={mat}")
        print(f"      vendor: {vendor}")
        print(f"      desc:   {desc}")
    print()

print("\n=== work_code별 wMAPE 영향도 ===\n")
for w in data["by_work_code"][:10]:
    print(f"  {w['work_code']:12s} cells={w['n_cells']:>2d}  wMAPE={w['weighted_mape']:>5.1f}%  "
          f"abs_diff={w['abs_diff']/1e6:>5.1f}M  actual={w['actual_sum']/1e6:>5.1f}M  "
          f"over/under={w['n_overpred']}/{w['n_underpred']}")

# 격리 시뮬레이션
print("\n=== outlier 격리 시 wMAPE 시뮬레이션 ===\n")
all_cells = []
for c in data["top_cells"]:
    all_cells.append(c)

# 모든 cell 다시 합산
all_abs = 0
all_actual = 0
for proj_code, cells in data["by_project"].items():
    for c in cells:
        if c.get("err_pct") is None:
            continue
        all_abs += c["abs_diff"]
        all_actual += c["actual"]

baseline_wmape = all_abs / all_actual * 100 if all_actual else 0
print(f"  현재 자재 wMAPE (top10 per project, 단순 합산): {baseline_wmape:.1f}%")

# 시나리오: err > N% 인 셀 제외
for thr in [500, 300, 200, 150, 100]:
    abs_diff_thr = 0
    actual_thr = 0
    excluded = 0
    excl_amt = 0
    for proj_code, cells in data["by_project"].items():
        for c in cells:
            if c.get("err_pct") is None:
                continue
            if c["err_pct"] > thr:
                excluded += 1
                excl_amt += c["abs_diff"]
                continue
            abs_diff_thr += c["abs_diff"]
            actual_thr += c["actual"]
    new_wmape = abs_diff_thr / actual_thr * 100 if actual_thr else 0
    print(f"  err > {thr}% 셀({excluded}개, abs_diff={excl_amt/1e6:.1f}M) 격리 → wMAPE = {new_wmape:.1f}%")
