"""easyocr PNG sample 1개 한글 OCR 정확도 시험.

처음 실행 시 모델 다운로드 (~100MB). 그 후 캐시.
"""
from __future__ import annotations

import json
import logging
import sys
import urllib.parse
import warnings
from pathlib import Path

logging.getLogger("easyocr").setLevel(logging.WARNING)
warnings.filterwarnings("ignore")

import easyocr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LOG: list[str] = []
def log(s=""): LOG.append(str(s))

EXPORT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v2")


def main():
    # 견적/명세 PNG 또는 JPG sample 1개
    candidates = []
    for p in EXPORT_DIR.glob("*.png"):
        decoded = urllib.parse.unquote(p.name)
        if any(k in decoded for k in ["견적", "거래명세", "명세서"]):
            candidates.append((p, decoded))
    log(f"PNG 견적: {len(candidates)}개")

    # JPG 도 추가
    for p in EXPORT_DIR.glob("*.jpg"):
        decoded = urllib.parse.unquote(p.name)
        if any(k in decoded for k in ["견적", "거래명세", "명세서"]):
            candidates.append((p, decoded))
    log(f"PNG+JPG 견적 후보: {len(candidates)}개")

    if not candidates:
        return

    log("\n--- easyocr Reader 초기화 (한글+영문) ---")
    reader = easyocr.Reader(['ko', 'en'], gpu=False, verbose=False)
    log("  OK")

    # 처음 3개 sample
    for idx, (target, decoded) in enumerate(candidates[:3]):
        log(f"\n========== Sample #{idx+1}: {decoded[:60]} ==========")
        log(f"  size: {target.stat().st_size / 1024:.0f}KB")
        result = reader.readtext(str(target), detail=1, paragraph=False)
        log(f"  텍스트 {len(result)}개 detected")
        # confidence 분포
        confs = [r[2] for r in result]
        if confs:
            log(f"  conf: min={min(confs):.2f}, mean={sum(confs)/len(confs):.2f}, max={max(confs):.2f}")
            log(f"  high_conf (>0.8): {sum(1 for c in confs if c > 0.8)}")
        log(f"\n  --- 처음 30개 ---")
        for r in result[:30]:
            bbox, txt, conf = r
            log(f"  [{conf:.2f}] '{txt}'")

    out_path = ROOT / "harness" / "reports" / "_ocr_sample_log.txt"
    out_path.write_text("\n".join(LOG), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        LOG.append(f"ERROR: {e}")
        import traceback
        LOG.append(traceback.format_exc())
        out_path = ROOT / "harness" / "reports" / "_ocr_sample_log.txt"
        out_path.write_text("\n".join(LOG), encoding="utf-8")
