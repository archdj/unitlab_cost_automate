"""actual_costs 결측·이상치 정량화. M0 quality gate.

Usage:
    python -m harness.scripts.profile_actual_costs
    # 또는 (스크립트 직접):
    python harness/scripts/profile_actual_costs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import db                        # noqa: E402
from src.config import HARNESS_REPORTS    # noqa: E402


def main() -> None:
    HARNESS_REPORTS.mkdir(parents=True, exist_ok=True)
    con = db.connect_readonly()
    try:
        report = db.profile_actual_costs(con)
    finally:
        con.close()

    out = HARNESS_REPORTS / "actual_costs_profile.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[profile_actual_costs] {out}")
    print(f"  total_rows = {report['total_rows']:,}")
    for col, rate in report["missing_rate"].items():
        print(f"  missing[{col:<18s}] = {rate*100:5.1f}%")
    print(f"  vendor_polluted = {report['vendor_polluted_rows']:,} "
          f"({report['vendor_polluted_rate']*100:.1f}%)")
    print(f"  promotion_status: {report['by_promotion_status']}")


if __name__ == "__main__":
    main()
