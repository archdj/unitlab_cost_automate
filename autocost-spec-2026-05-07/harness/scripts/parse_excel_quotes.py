"""47개 Excel 견적서 자동 파싱.

각 Excel에서:
- 표 헤더 행 자동 탐지 (품명/규격/단위/수량/단가/금액 키워드)
- 자재 line item 추출 (item, spec, unit, qty, unit_price, amount)
- 파일명에서 vendor / project / 카테고리 키워드 추출
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

EXPORT_DIR = Path(r"C:\Users\PC\Downloads\notion_export_v3")
REPORT_PATH = ROOT / "harness" / "reports" / "excel_quote_parsing.json"

HEADER_KEYWORDS = ["품명", "품  명", "품   명", "품      명", "품      목", "품   목", "적요", "내       역"]
QTY_KEYWORDS = ["수량", "수    량", "수   량"]
PRICE_KEYWORDS = ["단가", "단    가", "단   가", "단       가"]
AMOUNT_KEYWORDS = ["금액", "공급가", "공급 가액", "공  급  가  액", "금   액", "금       액"]
UNIT_KEYWORDS = ["단위"]
SPEC_KEYWORDS = ["규격"]


# 프로젝트 키워드 → project_code (등재된 프로젝트 매핑)
PROJ_KEYWORDS = {
    "다랑논":     "N-04-S-30",
    "다랑협동":   "N-04-S-30",
    "밀양":       "N-04-S-30",
    "남기동길":   "N-13-T-15-3",
    "노천리":     "N-01-T-15",
    "홍천":       "N-01-T-15",
    "제주":       "N-09-H-30",
    "서광리":     "N-09-H-30",
    "에스테라고": "N-07-U-6-1",
    "수지":       "N-07-U-6-1",
    "용인":       "N-16-T-12",
    "남곡리":     "N-16-T-12",
    "쇼룸":       "N-02-T-12-1",
    "청주":       "N-11-T-12",
    "미원면":     "N-11-T-12",
    "남이면":     "N-15-청주-남이면-가마리-산6-1",
    "가마리":     "N-15-청주-남이면-가마리-산6-1",
    "성남":       "N-19-T-12",
    "상적동":     "N-19-T-12",
    "금산":       "N-18-T-12",
    "마전리":     "N-18-T-12",
    "화성":       "N-20-경기-화성시-쌍학리-667",
    "쌍학리":     "N-20-경기-화성시-쌍학리-667",
    "서산":       "N-21-서산-부석면-강수리-277",
    "강수리":     "N-21-서산-부석면-강수리-277",
    "농어촌":     "N-03-농어촌-공사",
    "루떼르":     "N-10-S-18",
    "루뗴르":     "N-10-S-18",
    "포레":       "N-10-S-18",
    "롯데아울렛": "N-17-롯데아울렛-팝업스토어",
    "테스트베드": "N-UNMATCHED",
}

# 자재 카테고리 키워드 → work_code
CATEGORY_KEYWORDS = {
    "골조":       "STR-ST",
    "철강":       "STR-ST",
    "H형강":      "STR-ST",
    "판넬":       "FIN-PANEL",
    "외장":       "EXT-CLAD",
    "창호":       "EXT-WIN",
    "폴딩":       "EXT-WIN",
    "현관문":     "FUR-DOOR",
    "도어":       "FUR-DOOR",
    "전기":       "MEP-ELEC",
    "조명":       "MEP-ELEC",
    "콘센트":     "MEP-ELEC",
    "스위치":     "MEP-ELEC",
    "사이니지":   "MEP-ELEC",
    "설비":       "MEP-PLMB",
    "배관":       "MEP-PLMB",
    "보일러":     "MEP-HVAC",
    "환기":       "MEP-HVAC",
    "에어컨":     "MEP-HVAC",
    "공조":       "MEP-HVAC",
    "징크":       "EXT-ROOF",
    "후레싱":     "EXT-ROOF",
    "지붕":       "EXT-ROOF",
    "처마":       "EXT-ROOF",
    "데크":       "EXT-DECK",
    "바닥":       "FIN-FLOOR",
    "마루":       "FIN-FLOOR",
    "장판":       "FIN-FLOOR",
    "경량":       "FIN-LGS",
    "수장":       "FIN-CARP",
    "목공":       "FIN-CARP",
    "목자재":     "FIN-CARP",
    "타일":       "FIN-TILE",
    "도기":       "FUR-BATH",
    "수전":       "FUR-BATH",
    "욕실":       "FUR-BATH",
    "천장":       "FIN-CEIL",
    "도배":       "FIN-WALL",
    "스크린":     "FUR-SOFT",
    "커튼":       "FUR-SOFT",
    "가구":       "FUR",
    "주방":       "FUR-KITCH",
    "냉장고":     "FUR-KITCH",
    "세탁기":     "FUR-KITCH",
    "난방":       "MEP-HVAC",  # 또는 FIN-FLOOR (바닥난방)
    "도장":       "FIN-PAINT",
    "방수":       "FIN-WTP",
    "운반":       "SITE-MISC",
    "철거":       "SITE-DEMO",
    "조경":       "SITE-LAND",
    "토목":       "SITE-EARTH",
}


def classify_filename(decoded: str) -> dict:
    """파일명에서 vendor / project / 카테고리 추출."""
    out = {"vendors": [], "project_code": None, "work_code": None, "tags": []}
    name = decoded
    # vendor 추정 — 첫 번째 _ 앞부분
    parts = re.split(r"[_\-\.]", name)
    if parts:
        out["vendors"] = [parts[0]]
    # project
    for kw, code in PROJ_KEYWORDS.items():
        if kw in name:
            out["project_code"] = code
            out["tags"].append(f"proj:{kw}")
            break
    # work_code
    for kw, code in CATEGORY_KEYWORDS.items():
        if kw in name:
            out["work_code"] = code
            out["tags"].append(f"cat:{kw}")
            break
    return out


def _norm(s: str) -> str:
    """셀 내부 모든 공백 제거 후 비교용 normalize."""
    return re.sub(r"\s+", "", str(s))


def find_header(df: pd.DataFrame) -> dict | None:
    """표 헤더 행 자동 탐지. 품명+수량+단가 같은 줄에 있는 행을 찾음.
    셀 내부 공백 패딩 처리 (예: "품      명")."""
    for i in range(min(len(df), 30)):
        row = df.iloc[i].astype(str).tolist()
        normed = [_norm(c) for c in row]
        joined = " ".join(normed)
        has_item = any(k in joined for k in ["품명", "품목", "적요", "내역"])
        has_qty = "수량" in joined
        has_price = "단가" in joined or "금액" in joined or "공급" in joined
        if has_item and has_qty and has_price:
            col_map = {}
            for j, cs in enumerate(normed):
                if not cs or cs.lower() == "nan":
                    continue
                if any(k in cs for k in ["품명", "품목", "적요", "내역"]):
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


def to_number(v) -> float | None:
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v != 0 else None
    s = str(v).strip().replace(",", "").replace("₩", "").replace(" ", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_excel(p: Path) -> dict:
    decoded = urllib.parse.unquote(p.name)
    cls = classify_filename(decoded)
    out = {
        "file":         decoded,
        "raw_path":     str(p),
        "vendors":      cls["vendors"],
        "project_code": cls["project_code"],
        "work_code":    cls["work_code"],
        "tags":         cls["tags"],
        "rows":         [],
        "header_row":   None,
        "n_extracted":  0,
        "amount_total": 0,
        "error":        None,
    }
    try:
        df = pd.read_excel(p, header=None, sheet_name=0)
    except Exception as e:
        out["error"] = f"read_error: {e}"
        return out
    h = find_header(df)
    if h is None:
        out["error"] = "header_not_found"
        return out
    out["header_row"] = h["row"]
    out["header_cols"] = h["cols"]
    cols = h["cols"]
    for i in range(h["row"] + 1, len(df)):
        row = df.iloc[i]
        item = str(row.iloc[cols["item"]]).strip() if "item" in cols else ""
        if not item or item.lower() == "nan" or "합계" in item or "vat" in item.lower():
            continue
        qty = to_number(row.iloc[cols["qty"]]) if "qty" in cols else None
        price = to_number(row.iloc[cols["price"]]) if "price" in cols else None
        amount = to_number(row.iloc[cols["amount"]]) if "amount" in cols else None
        unit = str(row.iloc[cols["unit"]]).strip() if "unit" in cols else ""
        spec = str(row.iloc[cols["spec"]]).strip() if "spec" in cols else ""
        if not (qty or price or amount):
            continue
        line = {
            "item":     item,
            "spec":     spec if spec.lower() != "nan" else "",
            "unit":     unit if unit.lower() != "nan" else "",
            "qty":      qty,
            "price":    price,
            "amount":   amount,
        }
        out["rows"].append(line)
        if amount:
            out["amount_total"] += amount
    out["n_extracted"] = len(out["rows"])
    return out


def main():
    excel_files = list(EXPORT_DIR.glob("*.xls*"))
    print(f"Excel 파일: {len(excel_files)}\n")

    results = []
    cat_stats: dict[str, int] = defaultdict(int)
    proj_stats: dict[str, int] = defaultdict(int)
    success = 0
    no_header = 0
    error = 0
    total_rows = 0
    total_amount = 0

    for p in excel_files:
        r = parse_excel(p)
        results.append(r)
        if r["error"] == "header_not_found":
            no_header += 1
        elif r["error"]:
            error += 1
        else:
            success += 1
            total_rows += r["n_extracted"]
            total_amount += r["amount_total"]
            if r["work_code"]:
                cat_stats[r["work_code"]] += r["n_extracted"]
            if r["project_code"]:
                proj_stats[r["project_code"]] += r["n_extracted"]

    print(f"=== 파싱 결과 ===")
    print(f"  성공: {success} / {len(excel_files)}")
    print(f"  헤더 못찾음: {no_header}")
    print(f"  기타 에러: {error}")
    print(f"  추출 line: {total_rows}")
    print(f"  추출 금액 합: {total_amount/1e6:.1f}M")
    print()

    print("=== work_code별 추출 line ===")
    for wc, n in sorted(cat_stats.items(), key=lambda x: -x[1]):
        print(f"  {wc:12s}: {n}")
    print()

    print("=== project별 추출 line ===")
    for proj, n in sorted(proj_stats.items(), key=lambda x: -x[1]):
        print(f"  {proj:30s}: {n}")
    print()

    print("=== sample 추출 line (top 30) ===")
    for r in results[:5]:
        if r["error"]:
            continue
        print(f"\n[{r['file'][:60]}] (proj={r['project_code']}, wc={r['work_code']})")
        for line in r["rows"][:6]:
            print(f"  {line['item'][:25]:25s} | {(line.get('spec') or '')[:15]:15s} | "
                  f"{(line.get('unit') or '')[:6]:6s} | qty={line['qty']} | price={line['price']} | amt={line['amount']}")

    # 헤더 못찾은 파일 list
    print("\n=== 헤더 못찾은 파일 ===")
    for r in results:
        if r["error"] == "header_not_found":
            print(f"  {r['file'][:80]}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
