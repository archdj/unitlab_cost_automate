"""자재(재료비) row 전체의 work_code × raw_description 분포 dump.

오분류 후보 식별을 위해:
- 각 normalized work_code 그룹별 raw_description 모두 출력
- material_id 부여 여부, vendor 도메인 등도 함께
"""
from __future__ import annotations

import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.config import HARNESS_REPORTS
from src.db import connect_readonly, workcode_normalize_map

REPORT_PATH = HARNESS_REPORTS / "material_descriptions_dump.json"
NOTION_URL_RE = re.compile(r"\(https?://(www\.)?notion\.so/[^\s)]+\)")


def main():
    con = connect_readonly()
    norm = workcode_normalize_map(con)

    rows = list(con.execute("""
        SELECT
          ac.actual_cost_id, ac.project_id, p.project_code,
          ac.work_code_id, ac.raw_description, ac.material_id,
          ac.total_amount, ac.vendor_name
        FROM actual_costs ac
        JOIN projects p ON ac.project_id = p.project_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ('approved','promoted','validated')
          AND ac.source_ref = '재료비'
    """))

    # work_code → list of raw_description with amount
    by_wc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        nwc = norm.get(r["work_code_id"])
        if not nwc:
            continue
        wc = nwc["normalized_code"]
        vendor_clean = NOTION_URL_RE.sub("", r["vendor_name"] or "").strip(" ,;()")
        by_wc[wc].append({
            "actual_cost_id":   r["actual_cost_id"],
            "project_code":     r["project_code"],
            "raw_description":  r["raw_description"],
            "material_id":      r["material_id"],
            "amount":           r["total_amount"],
            "vendor":           vendor_clean,
        })

    # work_code별 통계
    summary = {}
    for wc, items in sorted(by_wc.items()):
        summary[wc] = {
            "n_rows":       len(items),
            "total_amount": sum(i["amount"] for i in items),
            "n_with_mat_id": sum(1 for i in items if i["material_id"]),
        }

    print("=== work_code별 자재 row 통계 ===")
    print(f"  {'wc':12s} {'rows':>5s} {'amount':>10s} {'mat_id':>7s}")
    for wc, st in sorted(summary.items(), key=lambda x: -x[1]["total_amount"]):
        print(f"  {wc:12s} {st['n_rows']:>5d}  {st['total_amount']/1e6:>7.1f}M  {st['n_with_mat_id']:>5d}")
    print()

    # FUR / EXT-CLAD / EXT-WIN / FIN-LGS 의 모든 raw_description
    focus_wc = ["FUR", "EXT-CLAD", "EXT-WIN", "FIN-LGS", "FIN-PANEL", "FUR-DOOR", "MEP-ELEC", "MEP-HVAC", "FIN-CARP"]
    for wc in focus_wc:
        items = sorted(by_wc.get(wc, []), key=lambda x: -x["amount"])
        print(f"\n=== [{wc}] raw_description 전체 ({len(items)}건) ===")
        for i in items:
            desc = (i["raw_description"] or "")[:55]
            vendor = (i["vendor"] or "")[:25]
            mat = i["material_id"] or "-"
            print(f"  {i['project_code'][:22]:22s} {i['amount']/1e3:>7.0f}K  mat={mat}  desc='{desc}'  vendor='{vendor}'")

    out = {"summary": summary, "by_work_code": dict(by_wc)}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
