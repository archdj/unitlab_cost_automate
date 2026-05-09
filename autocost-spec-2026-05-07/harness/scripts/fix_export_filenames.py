"""Notion export zip을 Python zipfile로 다시 풀면서 한글 파일명 복원.

zipfile 의 ZipInfo.filename 은 기본적으로 cp437로 디코딩되어 깨짐.
flag_bits 의 utf-8 flag 가 없으면 cp437 raw bytes를 다시 cp949 또는 utf-8로 디코딩 시도.
또한 Windows MAX_PATH 회피를 위해 \\?\ prefix 사용.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

LOG: list[str] = []
def log(s=""): LOG.append(str(s))

INNER_ZIP = Path(r"C:\Users\PC\Downloads\notion_export_v2\ExportBlock-a7e5b9b6-ab8a-40a1-a0ec-68b2c5a74df9-Part-1.zip")
OUT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v3")  # 새 디렉토리에 풀기


def decode_name(raw_name: str, info_flags: int) -> str:
    """ZipInfo.filename → 한글 복원."""
    # zipfile이 utf-8 flag 없으면 cp437로 디코딩한다 → 다시 raw bytes 복원
    if info_flags & 0x800:
        return raw_name  # 이미 utf-8
    try:
        raw_bytes = raw_name.encode("cp437")
    except UnicodeEncodeError:
        return raw_name
    # cp949 우선 (Windows 한글), 실패 시 utf-8
    for enc in ("cp949", "utf-8", "euc-kr"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_name


def safe_truncate(name: str, max_len: int = 200) -> str:
    """파일명이 너무 길면 truncate (확장자 보존)."""
    if len(name) <= max_len:
        return name
    p = Path(name)
    stem = p.stem
    suffix = p.suffix
    keep = max_len - len(suffix) - 5  # 5자 여유
    if keep <= 20:
        return name[:max_len]
    return stem[:keep] + suffix


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    extracted = 0
    skipped_long = 0
    skipped_dir = 0
    failed = 0
    by_ext: dict[str, int] = {}

    with zipfile.ZipFile(INNER_ZIP) as z:
        for info in z.infolist():
            if info.is_dir():
                skipped_dir += 1
                continue
            decoded_name = decode_name(info.filename, info.flag_bits)
            # 파일명만 사용 (path는 평탄화 — 이미 export는 거의 평탄)
            base = Path(decoded_name).name
            base = safe_truncate(base, max_len=180)
            target = OUT_DIR / base
            try:
                with z.open(info) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                extracted += 1
                ext = Path(base).suffix.lower()
                by_ext[ext] = by_ext.get(ext, 0) + 1
            except OSError as e:
                if "too long" in str(e).lower() or e.errno == 36 or "[WinError 206]" in str(e):
                    skipped_long += 1
                else:
                    failed += 1
                    log(f"FAIL: {base[:60]} - {e}")

    log(f"=== 추출 결과 ===")
    log(f"  extracted: {extracted}")
    log(f"  skipped (dir): {skipped_dir}")
    log(f"  skipped (path too long): {skipped_long}")
    log(f"  failed: {failed}")
    log()
    log(f"=== 파일 타입 ===")
    for ext, n in sorted(by_ext.items(), key=lambda x: -x[1]):
        log(f"  {ext or '<no_ext>':10s}: {n}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"ERROR: {e}")
        log(traceback.format_exc())
    out = Path(__file__).resolve().parents[2] / "harness" / "reports" / "_fix_filenames_log.txt"
    out.write_text("\n".join(LOG), encoding="utf-8")
