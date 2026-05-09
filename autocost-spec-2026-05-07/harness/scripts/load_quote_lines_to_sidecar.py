"""Excel + PDF 견적서 line items 를 sidecar enriched.db 에 적재.

새 테이블: material_quote_lines (자재 견적서 line items)
- 같은 (vendor, project, work_code) 키로 그룹핑 가능
- 단가 분포 분석 + actual_cost 매칭 cross-check 의 source
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ENRICHED_DB = ROOT / "harness" / "data" / "autocost_enriched.db"
EXCEL_REPORT = ROOT / "harness" / "reports" / "excel_quote_parsing.json"
PDF_REPORT   = ROOT / "harness" / "reports" / "pdf_quote_parsing.json"

LOG: list[str] = []
def log(s=""): LOG.append(str(s))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS material_quote_lines (
  line_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source           TEXT NOT NULL,         -- 'excel' / 'pdf'
  source_file      TEXT NOT NULL,         -- 견적서 파일명 (decoded)
  vendor           TEXT,                  -- 파일명에서 추정한 vendor
  project_code     TEXT,                  -- 파일명에서 추정한 project (PROJ_KEYWORDS)
  work_code        TEXT,                  -- 파일명에서 추정한 work_code (CATEGORY_KEYWORDS)
  item_name        TEXT,                  -- 자재 line item 이름
  spec             TEXT,
  unit             TEXT,
  qty              REAL,
  unit_price       REAL,
  amount           REAL,
  extraction_method TEXT,                 -- 'excel:table' / 'pdf:table' / 'pdf:text_fallback'
  loaded_at        TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_mql_proj  ON material_quote_lines(project_code);
CREATE INDEX IF NOT EXISTS idx_mql_wc    ON material_quote_lines(work_code);
CREATE INDEX IF NOT EXISTS idx_mql_vend  ON material_quote_lines(vendor);
"""


def main():
    if not ENRICHED_DB.exists():
        log(f"sidecar 없음: {ENRICHED_DB}")
        return
    con = sqlite3.connect(ENRICHED_DB)
    con.executescript(SCHEMA_SQL)
    con.execute("DELETE FROM material_quote_lines")  # idempotent
    con.commit()

    excel_data = json.loads(EXCEL_REPORT.read_text(encoding="utf-8"))
    pdf_data   = json.loads(PDF_REPORT.read_text(encoding="utf-8"))

    inserted = 0
    skipped_no_item = 0

    def insert_lines(data, source_label):
        nonlocal inserted, skipped_no_item
        for r in data:
            if r.get("error") or r.get("extraction") == "fail":
                continue
            vendor = (r["vendors"][0] if r.get("vendors") else None)
            for line in r.get("rows", []):
                item = (line.get("item") or "").strip()
                if not item:
                    skipped_no_item += 1
                    continue
                con.execute("""
                    INSERT INTO material_quote_lines
                      (source, source_file, vendor, project_code, work_code,
                       item_name, spec, unit, qty, unit_price, amount, extraction_method)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    source_label,
                    r["file"],
                    vendor,
                    r.get("project_code"),
                    r.get("work_code"),
                    item,
                    line.get("spec") or None,
                    line.get("unit") or None,
                    line.get("qty"),
                    line.get("price"),
                    line.get("amount"),
                    f"{source_label}:{r.get('extraction', 'table')}",
                ))
                inserted += 1

    insert_lines(excel_data, "excel")
    insert_lines(pdf_data, "pdf")
    con.commit()

    log(f"=== sidecar 적재 ===")
    log(f"  inserted: {inserted}")
    log(f"  skipped (no item_name): {skipped_no_item}")
    log()

    # 분석 1: source × work_code 분포
    log("=== source × work_code line 분포 ===")
    rows = con.execute("""
        SELECT source, work_code, COUNT(*) n, SUM(amount) amt_sum
        FROM material_quote_lines
        GROUP BY source, work_code
        ORDER BY amt_sum DESC NULLS LAST
    """).fetchall()
    for r in rows:
        amt = r[3] or 0
        log(f"  {r[0]:6s} {(r[1] or '?'):12s} n={r[2]:>3d}  amt={amt/1e6:>5.1f}M")
    log()

    # 분석 2: project_code 별 cover
    log("=== project별 line 합 ===")
    for r in con.execute("""
        SELECT project_code, COUNT(*) n, SUM(amount) amt
        FROM material_quote_lines
        GROUP BY project_code
        ORDER BY amt DESC NULLS LAST
    """):
        amt = r[2] or 0
        log(f"  {(r[0] or '?'):30s}  n={r[1]:>3d}  amt={amt/1e6:>5.1f}M")
    log()

    # 분석 3: 단가 분포 (work_code × unit) — n>=3 한정
    log("=== 단가 분포 (work_code × unit, n>=3) ===")
    log(f"  {'wc':12s} {'unit':6s} {'n':>3s} {'min':>10s} {'median':>10s} {'max':>10s}  CV")
    groups = list(con.execute("""
        SELECT COALESCE(work_code, '?') wc, COALESCE(unit, '') unit, COUNT(*) n,
               MIN(unit_price) mn, MAX(unit_price) mx
        FROM material_quote_lines
        WHERE unit_price IS NOT NULL AND unit_price > 0
        GROUP BY COALESCE(work_code, '?'), COALESCE(unit, '')
        HAVING COUNT(*) >= 3
        ORDER BY wc, unit
    """))
    import statistics
    for r in groups:
        prices = [x[0] for x in con.execute("""
            SELECT unit_price FROM material_quote_lines
            WHERE COALESCE(work_code,'?')=? AND COALESCE(unit,'')=?
              AND unit_price IS NOT NULL AND unit_price > 0
        """, (r[0], r[1]))]
        if not prices:
            continue
        prices.sort()
        med = prices[len(prices) // 2]
        mean = statistics.mean(prices)
        cv = statistics.stdev(prices) / mean if len(prices) >= 2 and mean else 0
        log(f"  {r[0]:12s} {(r[1] or '-'):6s} {r[2]:>3d} "
            f"{r[3]:>10.0f} {med:>10.0f} {r[4]:>10.0f}  {cv:.2f}")
    log()

    # 분석 4: 견적서 amount 합 vs actual_cost 비교 (project, work_code)
    log("=== 견적서 vs actual_cost amount 비교 (project × wc) ===")
    log("  견적서 line item amount sum vs 운영 DB actual_costs 재료비 sum")
    # 운영 DB attach
    op_db = ROOT.parent.parent / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
    if op_db.exists():
        con.execute(f"ATTACH DATABASE '{op_db.as_posix()}' AS op")
        # actual_costs 자재 합 (project_code × normalized work_code 기준)
        # 근데 project_code 매칭 필요 — project.project_code 와 일치
        for r in con.execute("""
            WITH q AS (
              SELECT project_code, work_code,
                     SUM(amount) AS quote_sum,
                     COUNT(*) AS quote_lines
              FROM main.material_quote_lines
              WHERE project_code IS NOT NULL AND work_code IS NOT NULL AND amount IS NOT NULL
              GROUP BY project_code, work_code
            ),
            a AS (
              SELECT p.project_code,
                     wc_norm.normalized_code AS work_code,
                     SUM(ac.total_amount) AS actual_sum
              FROM op.actual_costs ac
              JOIN op.projects p ON ac.project_id = p.project_id
              JOIN (
                SELECT w.work_code_id,
                       COALESCE(parent.work_code, w.work_code) AS normalized_code
                FROM op.work_codes w
                LEFT JOIN op.work_codes parent
                  ON w.parent_code_id = parent.work_code_id AND w.level > 2
              ) wc_norm ON ac.work_code_id = wc_norm.work_code_id
              WHERE ac.source_ref = '재료비'
                AND ac.promotion_status IN ('approved','promoted','validated')
                AND ac.total_amount > 0
              GROUP BY p.project_code, wc_norm.normalized_code
            )
            SELECT q.project_code, q.work_code,
                   q.quote_sum, q.quote_lines,
                   a.actual_sum,
                   ROUND(q.quote_sum * 1.0 / a.actual_sum, 2) AS ratio
            FROM q LEFT JOIN a ON q.project_code = a.project_code AND q.work_code = a.work_code
            ORDER BY q.quote_sum DESC
        """):
            ratio_str = f"{r[5]:.2f}" if r[5] is not None else "-"
            actual_str = f"{r[4]/1e6:.1f}M" if r[4] is not None else "?"
            log(f"  {(r[0] or '')[:24]:24s} {r[1]:10s} "
                f"quote={r[2]/1e6:>5.1f}M ({r[3]:>2d}line) actual={actual_str:>7s}  ratio={ratio_str}")

    out_path = ROOT / "harness" / "reports" / "_quote_loading_log.txt"
    out_path.write_text("\n".join(LOG), encoding="utf-8")

    con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"ERROR: {e}")
        log(traceback.format_exc())
        out_path = ROOT / "harness" / "reports" / "_quote_loading_log.txt"
        out_path.write_text("\n".join(LOG), encoding="utf-8")
