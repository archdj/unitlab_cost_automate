"""PDF 견적/명세 53개 자동 line item 추출.

pdfplumber로 표를 우선 추출. 표가 없거나 헤더 못 찾으면 텍스트 라인 기반 fallback.
출력은 Excel parser 와 같은 형식.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import urllib.parse
import warnings
from collections import defaultdict
from pathlib import Path

# pdfplumber FontBBox warning 억제
logging.getLogger("pdfminer").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore")

import pdfplumber

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# stdout/stderr 대신 log 누적 (콘솔 인코딩 회피)
LOG_LINES: list[str] = []
def log(s: str = ""):
    LOG_LINES.append(s)

# Excel parser 의 매핑 재사용
sys.path.insert(0, str(ROOT / "harness" / "scripts"))
from parse_excel_quotes import classify_filename, _norm, to_number

EXPORT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v3")
REPORT_PATH = ROOT / "harness" / "reports" / "pdf_quote_parsing.json"


def find_pdfs() -> list[tuple[Path, str]]:
    out = []
    for p in EXPORT_DIR.glob("*.pdf"):
        decoded = urllib.parse.unquote(p.name)
        if any(k in decoded for k in ["견적", "거래명세", "명세서", "수량"]):
            out.append((p, decoded))
    return out


def find_header_in_table(table: list[list]) -> dict | None:
    """pdfplumber 표 1개에서 헤더 행 탐지."""
    for i, row in enumerate(table[:8]):
        if not row:
            continue
        normed = [_norm(c) if c else "" for c in row]
        joined = " ".join(normed)
        has_item = any(k in joined for k in ["품명", "품목", "적요", "내역", "내용", "제품명"])
        has_qty = "수량" in joined
        has_price = "단가" in joined or "금액" in joined or "공급" in joined
        if has_item and has_qty and has_price:
            col_map = {}
            for j, cs in enumerate(normed):
                if any(k in cs for k in ["품명", "품목", "적요", "내역", "내용", "제품명"]):
                    col_map.setdefault("item", j)
                elif "규격" in cs:
                    col_map.setdefault("spec", j)
                elif "단위" in cs:
                    col_map.setdefault("unit", j)
                elif "수량" in cs:
                    col_map.setdefault("qty", j)
                elif "단가" in cs:
                    col_map.setdefault("price", j)
                elif "금액" in cs or "공급" in cs:
                    col_map.setdefault("amount", j)
            if "item" in col_map and ("qty" in col_map or "price" in col_map):
                return {"row": i, "cols": col_map}
    return None


def parse_pdf_table(p: Path) -> list[dict]:
    """PDF 표 추출 → line items."""
    out = []
    try:
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    h = find_header_in_table(table)
                    if h is None:
                        continue
                    cols = h["cols"]
                    for r in table[h["row"] + 1:]:
                        if not r or len(r) <= max(cols.values()):
                            continue
                        item = (r[cols["item"]] or "").strip() if "item" in cols else ""
                        if not item or "합계" in item or "vat" in item.lower() or "공급가" in item:
                            continue
                        qty = to_number(r[cols["qty"]]) if "qty" in cols and r[cols["qty"]] else None
                        price = to_number(r[cols["price"]]) if "price" in cols and r[cols["price"]] else None
                        amount = to_number(r[cols["amount"]]) if "amount" in cols and r[cols["amount"]] else None
                        unit = (r[cols["unit"]] or "").strip() if "unit" in cols and r[cols["unit"]] else ""
                        spec = (r[cols["spec"]] or "").strip() if "spec" in cols and r[cols["spec"]] else ""
                        if not (qty or price or amount):
                            continue
                        out.append({
                            "item":   item,
                            "spec":   spec,
                            "unit":   unit,
                            "qty":    qty,
                            "price":  price,
                            "amount": amount,
                        })
    except Exception:
        pass
    return out


# 텍스트 라인 fallback — "품명 단가" 패턴 추출
LINE_PATTERNS = [
    # "창 호 단 가 5,351,000"
    re.compile(r"^([가-힣A-Za-z0-9 ()\-/+\.]{2,20}?)\s*단\s*가\s*([\d,]{4,})"),
    # "창호수량 8 총길이 45.39 자평 220.06"
    re.compile(r"^([가-힣A-Za-z0-9 ()\-/+\.]{2,20}?)\s*수\s*량\s*(\d+(?:\.\d+)?)"),
]


def parse_pdf_text_fallback(p: Path) -> list[dict]:
    """텍스트에서 line item 추정 fallback (간단)."""
    out = []
    try:
        with pdfplumber.open(p) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                for line in t.splitlines():
                    line = line.strip()
                    if not line or len(line) < 5:
                        continue
                    for pat in LINE_PATTERNS:
                        m = pat.match(line)
                        if m:
                            try:
                                num = float(m.group(2).replace(",", ""))
                            except ValueError:
                                continue
                            if num <= 0:
                                continue
                            kind = "price" if "단" in pat.pattern[: pat.pattern.find(r"\s*([\d,]")] or "단가" in pat.pattern else "qty"
                            out.append({
                                "item": m.group(1).strip(),
                                kind:   num,
                                "fallback": "text_line",
                            })
                            break
    except Exception:
        pass
    return out


def main():
    pdfs = find_pdfs()
    log(f"견적/명세 PDF: {len(pdfs)}개\n")

    results = []
    table_success = 0
    fallback_success = 0
    fail = 0
    total_lines = 0
    total_amount = 0
    by_wc: dict[str, int] = defaultdict(int)

    for p, decoded in pdfs:
        cls = classify_filename(decoded)
        rec = {
            "file":         decoded,
            "vendors":      cls["vendors"],
            "project_code": cls["project_code"],
            "work_code":    cls["work_code"],
            "tags":         cls["tags"],
            "rows":         [],
            "extraction":   None,
        }
        rows = parse_pdf_table(p)
        if rows:
            rec["rows"] = rows
            rec["extraction"] = "table"
            table_success += 1
        else:
            rows = parse_pdf_text_fallback(p)
            if rows:
                rec["rows"] = rows
                rec["extraction"] = "text_fallback"
                fallback_success += 1
            else:
                rec["extraction"] = "fail"
                fail += 1
        rec["n_extracted"] = len(rec["rows"])
        rec["amount_total"] = sum(r.get("amount") or 0 for r in rec["rows"])
        results.append(rec)
        total_lines += rec["n_extracted"]
        total_amount += rec["amount_total"]
        if rec["work_code"] and rec["n_extracted"]:
            by_wc[rec["work_code"]] += rec["n_extracted"]

    log(f"=== 추출 결과 ===")
    log(f"  표 추출 성공: {table_success}")
    log(f"  텍스트 fallback: {fallback_success}")
    log(f"  실패: {fail}")
    log(f"  총 line: {total_lines}")
    log(f"  총 amount: {total_amount/1e6:.1f}M")
    log()

    log("=== work_code별 line ===")
    for wc, n in sorted(by_wc.items(), key=lambda x: -x[1]):
        log(f"  {wc:12s}: {n}")
    log()

    log("=== sample 추출 (5개 PDF, 각 6 line) ===")
    sampled = 0
    for r in results:
        if r["extraction"] == "fail" or not r["rows"]:
            continue
        if sampled >= 5:
            break
        sampled += 1
        log(f"\n[{r['file'][:65]}] (proj={r['project_code']}, wc={r['work_code']}, ext={r['extraction']})")
        for line in r["rows"][:6]:
            it = (line.get("item") or "")[:25]
            spec = (line.get("spec") or "")[:15]
            unit = (line.get("unit") or "")[:6]
            log(f"  {it:25s} | {spec:15s} | {unit:6s} | qty={line.get('qty')} | price={line.get('price')} | amt={line.get('amount')}")

    # fail list
    log("\n=== 실패한 PDF ===")
    for r in results:
        if r["extraction"] == "fail":
            log(f"  {r['file'][:80]}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log(f"\n저장: {REPORT_PATH}")

    # log 통합 출력 — utf-8 file 로 dump
    log_path = ROOT / "harness" / "reports" / "_pdf_parse_log.txt"
    log_path.write_text("\n".join(LOG_LINES), encoding="utf-8")


if __name__ == "__main__":
    main()
