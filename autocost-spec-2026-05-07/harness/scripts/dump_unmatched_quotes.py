"""work_code/project_code 매칭 안된 line item의 source_file 목록 dump."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENRICHED_DB = ROOT / "harness" / "data" / "autocost_enriched.db"

LOG: list[str] = []
def log(s=""): LOG.append(str(s))

con = sqlite3.connect(ENRICHED_DB)
log("=== work_code 미매칭 견적서 (unique source_file) ===")
for r in con.execute("""
    SELECT DISTINCT source_file, source, COUNT(*) n, SUM(amount) amt
    FROM material_quote_lines
    WHERE work_code IS NULL
    GROUP BY source_file
    ORDER BY amt DESC NULLS LAST
"""):
    log(f"  [{r[1]:5s}] {r[0][:75]:75s}  n={r[2]:>3d}  amt={(r[3] or 0)/1e6:>5.1f}M")

log()
log("=== project_code 미매칭 견적서 ===")
for r in con.execute("""
    SELECT DISTINCT source_file, source, COUNT(*) n, SUM(amount) amt
    FROM material_quote_lines
    WHERE project_code IS NULL
    GROUP BY source_file
    ORDER BY amt DESC NULLS LAST
"""):
    log(f"  [{r[1]:5s}] {r[0][:75]:75s}  n={r[2]:>3d}  amt={(r[3] or 0)/1e6:>5.1f}M")

(ROOT / "harness" / "reports" / "_unmatched_quotes.txt").write_text("\n".join(LOG), encoding="utf-8")
con.close()
