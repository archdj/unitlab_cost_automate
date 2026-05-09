"""raw_description ↔ material_aliases 매칭 커버리지 측정. M0 quality gate.

Usage:
    python harness/scripts/measure_alias_coverage.py
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
        report = db.measure_alias_coverage(con)
    finally:
        con.close()

    out = HARNESS_REPORTS / "alias_coverage.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[measure_alias_coverage] {out}")
    print(f"  description 보유:    {report['actual_costs_with_description']:,}")
    print(f"  material_id 매칭:    {report['matched_by_material_id']:,} "
          f"({report['material_id_coverage_rate']*100:.1f}%)")
    print(f"  alias 정확 매칭:     {report['matched_exact']:,} "
          f"({report['alias_coverage_rate_exact']*100:.1f}%)")
    print(f"  alias 토큰 매칭:     {report['matched_token']:,} (정확 + 토큰 합계 "
          f"{report['alias_coverage_rate_token']*100:.1f}%)")
    print(f"  material_aliases:    {report['material_aliases_total']:,}")
    print()
    print("  토큰 매칭 샘플:")
    for h in report["sample_token_hits"][:8]:
        print(f"    {h['raw_description'][:30]:30s} → {h['matched_alias'][:20]:20s} "
              f"score={h['score']}  mid={h['material_id']}")
    print()
    print("  미매핑 상위:")
    for x in report["top_unmapped_descriptions"][:10]:
        print(f"    {x['raw_description'][:30]:30s} {x['n']:>4}회")


if __name__ == "__main__":
    main()
