"""Excel 견적서 sample 3개 dump."""
from __future__ import annotations

import io
import sys
import urllib.parse
from pathlib import Path

import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

EXPORT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v2")

samples = [
    ("나모바치", "가구"),
    ("삼보에스앤씨", "목자재"),
    ("태경", "난방"),
]

excel_files = list(EXPORT_DIR.glob("*.xls*"))
print(f"총 Excel 파일: {len(excel_files)}\n")

for vendor_kw, item_kw in samples:
    target = None
    for f in excel_files:
        name = urllib.parse.unquote(f.name)
        if vendor_kw in name and item_kw in name:
            target = f
            break
    if target is None:
        print(f"[{vendor_kw} × {item_kw}] 없음\n")
        continue
    decoded = urllib.parse.unquote(target.name)
    print(f"=== [{decoded}] ===")
    try:
        df = pd.read_excel(target, header=None)
        print(f"  shape: {df.shape}")
        # 처음 30행
        for i, row in df.head(30).iterrows():
            cells = [str(c)[:25] if pd.notna(c) else "" for c in row]
            print(f"  R{i:>2d}: {' | '.join(cells)}")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
