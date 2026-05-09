"""자재 row의 첨부 파일 매핑 가능성 점검."""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.db import connect_readonly

con = connect_readonly()

# receipt_id가 뭔지 확인 + non-NULL 비율
print("=== actual_costs receipt_id 통계 (자재만) ===")
total = con.execute("""
    SELECT COUNT(*), SUM(CASE WHEN receipt_id IS NOT NULL AND receipt_id != '' THEN 1 ELSE 0 END)
    FROM actual_costs
    WHERE source_ref = '재료비' AND total_amount > 0 AND promotion_status IN ('approved','promoted','validated')
""").fetchone()
print(f"  total: {total[0]}, with receipt_id: {total[1]}")

print()
print("=== receipt_id sample (5개) ===")
for r in con.execute("""
    SELECT receipt_id, raw_description, vendor_name
    FROM actual_costs
    WHERE source_ref = '재료비' AND receipt_id IS NOT NULL AND receipt_id != ''
    LIMIT 5
"""):
    print(f"  receipt='{r[0]}'")
    print(f"  desc='{(r[1] or '')[:50]}'  vendor='{(r[2] or '')[:30]}'")

print()
print("=== source_ref 외에 첨부 정보 컬럼 확인 ===")
for r in con.execute("PRAGMA table_info('actual_costs')"):
    print(f"  {r[1]:25s} {r[2]}")

print()
print("=== source_system 분포 ===")
for r in con.execute("SELECT source_system, COUNT(*) FROM actual_costs WHERE source_ref='재료비' GROUP BY source_system"):
    print(f"  {r[0]}: {r[1]}")

print()
print("=== Notion 페이지 title 매칭 가능성 ===")
print("  actual_costs.raw_description 이 노션 페이지 title 과 일치하는지 확인 (md 파일명)")
print("  raw_description sample 5개:")
for r in con.execute("""
    SELECT raw_description, total_amount FROM actual_costs
    WHERE source_ref='재료비' AND raw_description IS NOT NULL
    ORDER BY total_amount DESC LIMIT 5
"""):
    print(f"    '{r[0]}'  ₩{r[1]:,}")
