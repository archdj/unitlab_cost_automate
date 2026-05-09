"""vendor_name URL 분리 미리보기 (read-only).

운영 DB는 read-only로 참조. 본 스크립트는 정제 후보만 리포트로 저장하고
실제 운영 DB UPDATE는 운영 메인 repo가 담당한다.

Usage:
    python harness/scripts/clean_vendor_names.py
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
        sample = db.clean_vendor_sample(con, limit=200)
    finally:
        con.close()

    polluted = [s for s in sample if s["url_count"] > 0]
    multi = [s for s in sample if len(s["vendors"]) > 1]
    out = HARNESS_REPORTS / "vendor_cleanup.json"
    out.write_text(json.dumps({
        "sampled": len(sample),
        "polluted_url": len(polluted),
        "multi_vendor": len(multi),
        "preview": sample[:50],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[clean_vendor_names] {out}")
    print(f"  표본 {len(sample)}행 → URL 혼입 {len(polluted)} · 다업체 {len(multi)}")
    print("  처음 5건:")
    for s in sample[:5]:
        print(f"    raw    : {s['raw'][:80]}")
        print(f"    vendors: {s['vendors']}")
        print()


if __name__ == "__main__":
    main()
