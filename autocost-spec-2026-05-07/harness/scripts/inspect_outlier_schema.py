"""DB 스키마 + outlier 진단용 사전 조사."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import sqlite3
from src.config import OPERATIONAL_DB

con = sqlite3.connect(f"file:{OPERATIONAL_DB.as_posix()}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("=== actual_costs columns ===")
for r in con.execute("PRAGMA table_info('actual_costs')"):
    print(f"  {r['name']:30s} {r['type']}")
print()
print("=== work_codes columns ===")
for r in con.execute("PRAGMA table_info('work_codes')"):
    print(f"  {r['name']:30s} {r['type']}")
print()
print("=== promotion_status distribution ===")
for r in con.execute("SELECT promotion_status, COUNT(*) n, SUM(total_amount)/1e6 sum_M FROM actual_costs GROUP BY promotion_status"):
    print(f"  {r['promotion_status']:15s} n={r['n']:5d}  sum={r['sum_M']:.1f}M")
print()
print("=== source_ref (cost_type) distribution - only learnable rows ===")
for r in con.execute("""
    SELECT source_ref, COUNT(*) n, SUM(total_amount)/1e6 sum_M
    FROM actual_costs
    WHERE total_amount > 0 AND promotion_status IN ('approved','promoted','validated')
    GROUP BY source_ref ORDER BY sum_M DESC
"""):
    print(f"  {r['source_ref'] or 'NULL':20s} n={r['n']:5d}  sum={r['sum_M']:.1f}M")
print()
print("=== top-level work_codes (level=2) ===")
for r in con.execute("SELECT work_code, work_name_ko, category FROM work_codes WHERE level=2 ORDER BY work_code"):
    print(f"  {r['work_code']:15s} {r['work_name_ko'] or '':20s}  {r['category'] or ''}")
