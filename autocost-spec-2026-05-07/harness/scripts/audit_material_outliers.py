"""자재(재료비) outlier 진단.

각 (work_code, project) 셀의 rate_per_m2 분포를 work_code 그룹 내에서 비교.
median 기준 deviation이 큰 셀을 outlier 후보로 식별하고, 구성 raw row를
추적하여 4가지 패턴(unit/scale, bulk, asymmetric-zero, miscategorized)으로
분류 가능한 단서를 같이 추출한다.

Usage:
    python harness/scripts/audit_material_outliers.py
"""
from __future__ import annotations

import io
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.config import HARNESS_REPORTS, OPERATIONAL_DB
from src.db import connect_readonly, workcode_normalize_map

REPORT_PATH = HARNESS_REPORTS / "material_outlier_audit.json"

# 자재 cost_type만
COST_TYPE_TARGET = "재료비"
LEARNABLE = ("approved", "promoted", "validated")

# 셀 outlier 임계: rate_per_m2 가 그룹 median 의 K배 이상/이하
RATE_HI = 3.0
RATE_LO = 1 / 3.0
# 단일 row 가 셀 합의 N% 이상이면 dominant
DOMINANT_SHARE = 0.5


def load_cells():
    con = connect_readonly()
    norm = workcode_normalize_map(con)

    placeholders = ",".join("?" * len(LEARNABLE))
    rows = list(con.execute(f"""
        SELECT
          ac.actual_cost_id,
          ac.project_id,
          p.project_code,
          ac.work_code_id,
          ac.actual_quantity,
          ac.unit,
          ac.unit_price,
          ac.total_amount,
          ac.vendor_name,
          ac.raw_description,
          ac.material_id,
          mt.floor_area_m2
        FROM actual_costs ac
        JOIN projects p              ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ({placeholders})
          AND ac.source_ref = ?
    """, [*LEARNABLE, COST_TYPE_TARGET]))

    cells: dict[tuple, dict] = {}
    for r in rows:
        nwc = norm.get(r["work_code_id"])
        if not nwc:
            continue
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            continue
        wc = nwc["normalized_code"]
        key = (r["project_code"], wc)
        cell = cells.setdefault(key, {
            "project_code":         r["project_code"],
            "work_code":            wc,
            "work_name":            nwc["normalized_name"],
            "category":             nwc["category"],
            "floor_area_m2":        area,
            "amount_total":         0,
            "row_count":            0,
            "rows":                 [],
        })
        cell["amount_total"] += int(r["total_amount"])
        cell["row_count"] += 1
        cell["rows"].append({
            "actual_cost_id":   r["actual_cost_id"],
            "qty":              r["actual_quantity"],
            "unit":             r["unit"],
            "unit_price":       r["unit_price"],
            "amount":           int(r["total_amount"]),
            "vendor":           r["vendor_name"],
            "raw_description":  r["raw_description"],
            "material_id":      r["material_id"],
        })

    for c in cells.values():
        c["rate_per_m2"] = c["amount_total"] / c["floor_area_m2"]

    con.close()
    return list(cells.values())


def group_distribution(cells):
    by_wc: dict[str, list[float]] = defaultdict(list)
    for c in cells:
        by_wc[c["work_code"]].append(c["rate_per_m2"])
    summary = {}
    for wc, rates in by_wc.items():
        rates_sorted = sorted(rates)
        n = len(rates_sorted)
        summary[wc] = {
            "n_cells":  n,
            "median":   statistics.median(rates_sorted),
            "p25":      rates_sorted[n // 4] if n >= 4 else rates_sorted[0],
            "p75":      rates_sorted[3 * n // 4] if n >= 4 else rates_sorted[-1],
            "min":      rates_sorted[0],
            "max":      rates_sorted[-1],
        }
    return summary


def classify_pattern(cell, summary):
    """outlier 패턴 분류: hi/lo + dominant/bulk/multi-vendor/zero-qty."""
    s = summary[cell["work_code"]]
    r = cell["rate_per_m2"]
    flags = []

    if r > s["median"] * RATE_HI:
        flags.append("rate_hi")
    if r < s["median"] * RATE_LO:
        flags.append("rate_lo")

    if cell["amount_total"] > 0:
        max_row = max(cell["rows"], key=lambda x: x["amount"])
        if max_row["amount"] / cell["amount_total"] >= DOMINANT_SHARE:
            flags.append("dominant_row")
            cell["_dominant_row"] = max_row

    multi_vendor_rows = [
        x for x in cell["rows"]
        if x["vendor"] and any(sep in (x["vendor"] or "") for sep in [",", ";", "/", "외"])
    ]
    if multi_vendor_rows:
        flags.append("multi_vendor")
        cell["_multi_vendor_count"] = len(multi_vendor_rows)

    zero_qty_rows = [x for x in cell["rows"] if not x["qty"] or x["qty"] <= 0]
    if zero_qty_rows:
        flags.append("zero_qty")
        cell["_zero_qty_count"] = len(zero_qty_rows)

    no_unit_rows = [x for x in cell["rows"] if not (x["unit"] or "").strip()]
    if no_unit_rows:
        flags.append("no_unit")
        cell["_no_unit_count"] = len(no_unit_rows)

    return flags


def main():
    cells = load_cells()
    summary = group_distribution(cells)

    print(f"loaded {len(cells)} cells across {len(summary)} work_codes\n")

    flagged = []
    for cell in cells:
        flags = classify_pattern(cell, summary)
        if not flags:
            continue
        s = summary[cell["work_code"]]
        flagged.append({
            "project_code":     cell["project_code"],
            "work_code":        cell["work_code"],
            "work_name":        cell["work_name"],
            "category":         cell["category"],
            "amount_total":     cell["amount_total"],
            "row_count":        cell["row_count"],
            "rate_per_m2":      round(cell["rate_per_m2"], 0),
            "wc_median_rate":   round(s["median"], 0),
            "rate_ratio":       round(cell["rate_per_m2"] / s["median"], 2) if s["median"] else None,
            "flags":            flags,
            "dominant_row":     cell.get("_dominant_row"),
            "multi_vendor_count": cell.get("_multi_vendor_count"),
            "zero_qty_count":   cell.get("_zero_qty_count"),
            "no_unit_count":    cell.get("_no_unit_count"),
            "rows":             cell["rows"],
        })

    # 영향 큰 순으로 정렬 (amount_total)
    flagged.sort(key=lambda x: -x["amount_total"])

    # 패턴 통계
    pattern_stats: dict[str, dict] = {}
    for f in flagged:
        for tag in f["flags"]:
            ps = pattern_stats.setdefault(tag, {"cells": 0, "amount": 0})
            ps["cells"] += 1
            ps["amount"] += f["amount_total"]

    # workcode별 flag 통계
    by_wc_pattern: dict[str, dict] = {}
    by_wc_total: dict[str, dict] = defaultdict(lambda: {"cells": 0, "amount": 0})
    for c in cells:
        by_wc_total[c["work_code"]]["cells"] += 1
        by_wc_total[c["work_code"]]["amount"] += c["amount_total"]
    for f in flagged:
        wc = f["work_code"]
        rec = by_wc_pattern.setdefault(wc, {
            "wc_total_cells":   by_wc_total[wc]["cells"],
            "wc_total_amount":  by_wc_total[wc]["amount"],
            "flagged_cells":    0,
            "flagged_amount":   0,
            "flag_breakdown":   defaultdict(int),
        })
        rec["flagged_cells"] += 1
        rec["flagged_amount"] += f["amount_total"]
        for tag in f["flags"]:
            rec["flag_breakdown"][tag] += 1
    for rec in by_wc_pattern.values():
        rec["flag_breakdown"] = dict(rec["flag_breakdown"])
        rec["flagged_share"] = round(rec["flagged_amount"] / rec["wc_total_amount"], 3) if rec["wc_total_amount"] else 0

    print("=== pattern stats ===")
    for tag, ps in sorted(pattern_stats.items(), key=lambda x: -x[1]["amount"]):
        print(f"  {tag:14s} cells={ps['cells']:3d}  amount={ps['amount']/1e6:>7.1f}M")
    print()
    print("=== work_code별 flagged share top 10 ===")
    for wc, rec in sorted(by_wc_pattern.items(), key=lambda x: -x[1]["flagged_amount"])[:10]:
        flag_summary = ",".join(f"{k}={v}" for k, v in rec["flag_breakdown"].items())
        print(f"  {wc:12s} flagged={rec['flagged_amount']/1e6:>6.1f}M / total={rec['wc_total_amount']/1e6:>6.1f}M "
              f"({rec['flagged_share']*100:.0f}%)  [{flag_summary}]")
    print()
    print("=== top 15 flagged cells (amount 기준) ===")
    for f in flagged[:15]:
        print(f"  {f['project_code'][:24]:24s} {f['work_code']:10s} "
              f"{f['amount_total']/1e6:>6.1f}M  ratio={f['rate_ratio']}  rows={f['row_count']}  "
              f"[{','.join(f['flags'])}]")

    out = {
        "cost_type_target":     COST_TYPE_TARGET,
        "thresholds": {
            "rate_hi":          RATE_HI,
            "rate_lo":          RATE_LO,
            "dominant_share":   DOMINANT_SHARE,
        },
        "operational_db":       str(OPERATIONAL_DB),
        "n_cells_loaded":       len(cells),
        "n_workcodes":          len(summary),
        "n_flagged":            len(flagged),
        "pattern_stats":        pattern_stats,
        "by_workcode":          by_wc_pattern,
        "wc_distribution":      {wc: {**v, "median": round(v["median"], 0), "p25": round(v["p25"], 0), "p75": round(v["p75"], 0), "min": round(v["min"], 0), "max": round(v["max"], 0)} for wc, v in summary.items()},
        "flagged_cells":        flagged,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
