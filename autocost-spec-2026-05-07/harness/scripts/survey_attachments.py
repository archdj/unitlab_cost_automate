"""다운로드된 Notion export 첨부 파일 조사.

- URL-encoded 파일명 디코딩
- vendor / 프로젝트 / 자재 카테고리 추정
- Excel 1개 sample 내용 dump
- PDF 1개 텍스트 추출 시도
"""
from __future__ import annotations

import io
import re
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

EXPORT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v2")


def decode_filename(name: str) -> str:
    """Notion export 파일명 디코딩. URL-encoded → 한글, 또는 깨진 utf-8."""
    try:
        decoded = urllib.parse.unquote(name)
        if "%" not in decoded:
            return decoded
    except Exception:
        pass
    return name


def classify(decoded_name: str) -> dict:
    """파일명에서 vendor / project / 카테고리 키워드 추출 시도."""
    n = decoded_name.lower()
    out = {"category": [], "is_quote": False, "is_invoice": False}
    # 카테고리 키워드
    keywords = {
        "견적": "QUOTE", "거래명세": "STATEMENT", "계산서": "INVOICE",
        "영수": "RECEIPT", "수량": "QUANTITY", "사진": "PHOTO",
        "통장": "BANKBOOK", "사업자": "BIZREG", "도면": "DRAWING",
    }
    for k, v in keywords.items():
        if k in decoded_name:
            out["category"].append(v)
    out["is_quote"] = "QUOTE" in out["category"] or "QUANTITY" in out["category"] or "STATEMENT" in out["category"]
    out["is_invoice"] = "INVOICE" in out["category"]
    return out


def main():
    if not EXPORT_DIR.exists():
        print(f"{EXPORT_DIR} 없음")
        return

    all_files = list(EXPORT_DIR.rglob("*"))
    files = [p for p in all_files if p.is_file()]

    by_ext = Counter(p.suffix.lower() for p in files)
    print(f"=== 파일 타입 분포 ({len(files)}개) ===")
    for ext, n in sorted(by_ext.items(), key=lambda x: -x[1]):
        print(f"  {ext or '<no_ext>':10s}: {n}")
    print()

    # 첨부 파일만 (md/csv/zip 제외)
    attach_exts = {".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xls", ".hwp", ".html"}
    attachments = [p for p in files if p.suffix.lower() in attach_exts]
    print(f"=== 첨부 파일 ({len(attachments)}개) ===\n")

    by_category = defaultdict(int)
    is_quote_count = 0
    sample_quotes = []
    for p in attachments:
        decoded = decode_filename(p.name)
        cls = classify(decoded)
        if cls["is_quote"]:
            is_quote_count += 1
            if len(sample_quotes) < 30:
                sample_quotes.append((p, decoded))
        for c in cls["category"]:
            by_category[c] += 1

    print("카테고리 분포:")
    for c, n in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {c:15s}: {n}")
    print(f"\n견적/수량/거래명세 의심: {is_quote_count}개")

    print("\n=== 견적/수량 sample (30개) ===")
    for p, d in sample_quotes:
        print(f"  [{p.suffix.lower():6s}] {d[:70]}")

    # Excel sample 1개 dump
    excel_files = [p for p in attachments if p.suffix.lower() in {".xlsx", ".xls"}]
    if excel_files:
        print(f"\n=== Excel 파일 ({len(excel_files)}개) ===")
        for p in excel_files[:5]:
            decoded = decode_filename(p.name)
            print(f"  {decoded[:80]}")


if __name__ == "__main__":
    main()
