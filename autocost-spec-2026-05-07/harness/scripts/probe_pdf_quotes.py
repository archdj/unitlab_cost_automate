"""PDF 견적서 텍스트 추출 가능성 점검.

pdfplumber로 PDF text/table 추출 시도.
- 텍스트 PDF (생성형) → 표 추출 가능
- 스캔 이미지 PDF → text 0자 → OCR 필요
"""
from __future__ import annotations

import io
import sys
import urllib.parse
from pathlib import Path

import pdfplumber

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

EXPORT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v2")


def find_pdfs() -> list[Path]:
    out = []
    for p in EXPORT_DIR.glob("*.pdf"):
        decoded = urllib.parse.unquote(p.name)
        # 견적서/명세서 카테고리만
        if any(k in decoded for k in ["견적", "거래명세", "명세서", "수량"]):
            out.append((p, decoded))
    return out


def probe(p: Path, decoded: str) -> dict:
    out = {"file": decoded, "pages": 0, "text_chars": 0, "tables": 0, "first_text_sample": "", "first_table_sample": []}
    try:
        with pdfplumber.open(p) as pdf:
            out["pages"] = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                t = page.extract_text() or ""
                out["text_chars"] += len(t)
                if i == 0:
                    out["first_text_sample"] = t[:400]
                tables = page.extract_tables()
                out["tables"] += len(tables)
                if i == 0 and tables:
                    out["first_table_sample"] = tables[0][:8]
    except Exception as e:
        out["error"] = str(e)
    return out


def main():
    pdfs = find_pdfs()
    print(f"견적/명세 PDF: {len(pdfs)}개\n")

    # 5개 sample
    for p, decoded in pdfs[:5]:
        r = probe(p, decoded)
        print(f"=== {decoded[:70]} ===")
        print(f"  pages={r['pages']}  text_chars={r['text_chars']}  tables={r['tables']}")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
        if r["first_text_sample"]:
            print(f"  first_text_sample (400자):")
            print(f"  {r['first_text_sample'][:300]}")
        if r["first_table_sample"]:
            print(f"  first_table (8 rows):")
            for row in r["first_table_sample"]:
                print(f"    {row}")
        print()

    # 전체 통계: text 있음 vs 없음
    text_yes = 0
    text_no = 0
    for p, decoded in pdfs:
        try:
            with pdfplumber.open(p) as pdf:
                t = ""
                for page in pdf.pages[:1]:
                    t += page.extract_text() or ""
                if len(t.strip()) > 20:
                    text_yes += 1
                else:
                    text_no += 1
        except Exception:
            text_no += 1
    print(f"\n=== 전체 견적/명세 PDF 텍스트 추출 가능성 ===")
    print(f"  text_yes (텍스트 PDF): {text_yes}")
    print(f"  text_no (스캔/이미지 PDF, OCR 필요): {text_no}")


if __name__ == "__main__":
    main()
