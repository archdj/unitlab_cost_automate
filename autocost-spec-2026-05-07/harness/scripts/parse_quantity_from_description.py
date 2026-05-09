"""raw_description 정규식 파싱.

자재(재료비) row의 raw_description 에서 (quantity, unit) 추출.
패턴 라이브러리 + 커버리지 측정 + work_code별 단가 분포 분석.
"""
from __future__ import annotations

import io
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.config import HARNESS_REPORTS
from src.db import connect_readonly, workcode_normalize_map

REPORT_PATH = HARNESS_REPORTS / "quantity_parsing_audit.json"


# ─────────────────────────────────────────────────────────────────────────────
# 패턴 라이브러리
# ─────────────────────────────────────────────────────────────────────────────

NUM = r"(\d+(?:\.\d+)?)"

# 한글/영문 단위 → 표준 unit
UNIT_MAP = {
    # 면적
    "m2": "m2", "㎡": "m2", "M2": "m2", "m²": "m2",
    # 길이
    "m": "m", "M": "m", "mm": "mm", "MM": "mm", "T": "T", "t": "T",
    # 개수
    "장": "장", "개": "EA", "EA": "EA", "ea": "EA", "세트": "SET", "SET": "SET",
    "회": "회", "식": "식", "통": "통", "박스": "BOX", "BOX": "BOX",
    "롤": "롤", "벌": "벌", "조": "조", "팩": "팩", "권": "권",
    "롤지": "롤", "포대": "포대",
    # 무게/부피
    "kg": "kg", "KG": "kg", "L": "L", "ml": "ml",
}


# 패턴 정의 — 가장 구체적인 것부터 일반적인 것 순
PATTERNS = [
    # "150T 35장, 100T 22개" → 두께+장수 + 두께+장수 (압축)
    {
        "name":  "thickness_count_pair",
        "regex": re.compile(rf"{NUM}T\s*{NUM}\s*장"),
        "type":  "panel",
        "unit":  "장",
    },
    # "150T 6.5장"
    {
        "name":  "thickness_count_single",
        "regex": re.compile(rf"{NUM}T\s*{NUM}\s*장"),
        "type":  "panel",
        "unit":  "장",
    },
    # "EPS 180m2 / 28장"
    {
        "name":  "area_with_count",
        "regex": re.compile(rf"{NUM}\s*m2\s*/\s*{NUM}\s*장"),
        "type":  "area_count",
        "unit":  "m2",
    },
    # "2400 4m2, 3000 2m2" — 길이+면적
    {
        "name":  "length_area",
        "regex": re.compile(rf"{NUM}\s*m2"),
        "type":  "area",
        "unit":  "m2",
    },
    # "스카이비바 600EA"
    {
        "name":  "ea_count",
        "regex": re.compile(rf"{NUM}\s*EA", re.IGNORECASE),
        "type":  "count",
        "unit":  "EA",
    },
    # "외부벽등 8" — 단위 없는 끝자리 정수 (조명 등)
    {
        "name":  "trailing_int",
        "regex": re.compile(rf"\b{NUM}\b\s*$"),
        "type":  "count",
        "unit":  "EA",
    },
    # "스터드 190, 러너 70"
    {
        "name":  "stud_runner",
        "regex": re.compile(rf"스터드\s*{NUM}"),
        "type":  "count",
        "unit":  "EA",
    },
    # "장수만" — "28장"
    {
        "name":  "count_with_jang",
        "regex": re.compile(rf"{NUM}\s*장"),
        "type":  "count",
        "unit":  "장",
    },
    # "20개"
    {
        "name":  "count_with_gae",
        "regex": re.compile(rf"{NUM}\s*개"),
        "type":  "count",
        "unit":  "EA",
    },
    # "6m" / "6.5m"
    {
        "name":  "length_m",
        "regex": re.compile(rf"{NUM}\s*m\b"),
        "type":  "length",
        "unit":  "m",
    },
    # "330" 단독 (스카이비바 330) — 숫자만 떠있는 경우
    {
        "name":  "skyviva_size",
        "regex": re.compile(r"스카이비바\s*(\d+)"),
        "type":  "panel_size",
        "unit":  "단위미상",
    },
]


def parse_description(desc: str) -> dict | None:
    """raw_description 에서 가장 구체적인 패턴 1개 추출."""
    if not desc:
        return None
    desc = desc.strip()
    for p in PATTERNS:
        m = p["regex"].search(desc)
        if m:
            try:
                quantity = float(m.group(1))
            except (ValueError, IndexError):
                continue
            if quantity <= 0 or quantity > 100000:  # 비정상 제외
                continue
            return {
                "pattern": p["name"],
                "quantity": quantity,
                "unit":     p["unit"],
                "type":     p["type"],
                "matched":  m.group(0),
            }
    return None


def main():
    con = connect_readonly()
    norm = workcode_normalize_map(con)

    rows = list(con.execute("""
        SELECT
          ac.actual_cost_id, ac.project_id, p.project_code,
          ac.work_code_id, ac.raw_description, ac.total_amount
        FROM actual_costs ac
        JOIN projects p ON ac.project_id = p.project_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ('approved','promoted','validated')
          AND ac.source_ref = '재료비'
    """))

    parsed = []
    unparsed = []
    by_wc: dict[str, dict] = defaultdict(lambda: {"n_total": 0, "n_parsed": 0, "amount_total": 0, "amount_parsed": 0})

    for r in rows:
        nwc = norm.get(r["work_code_id"])
        wc = nwc["normalized_code"] if nwc else "?"
        amt = r["total_amount"]
        by_wc[wc]["n_total"] += 1
        by_wc[wc]["amount_total"] += amt

        result = parse_description(r["raw_description"] or "")
        if result:
            unit_price = amt / result["quantity"] if result["quantity"] > 0 else None
            parsed.append({
                "actual_cost_id":   r["actual_cost_id"],
                "project_code":     r["project_code"],
                "work_code":        wc,
                "raw_description":  r["raw_description"],
                "quantity":         result["quantity"],
                "unit":             result["unit"],
                "type":             result["type"],
                "pattern":          result["pattern"],
                "matched":          result["matched"],
                "amount":           amt,
                "unit_price":       round(unit_price, 0) if unit_price else None,
            })
            by_wc[wc]["n_parsed"] += 1
            by_wc[wc]["amount_parsed"] += amt
        else:
            unparsed.append({
                "actual_cost_id":   r["actual_cost_id"],
                "project_code":     r["project_code"],
                "work_code":        wc,
                "raw_description":  r["raw_description"],
                "amount":           amt,
            })

    # 커버리지 통계
    n_total = len(rows)
    n_parsed = len(parsed)
    amt_total = sum(r["total_amount"] for r in rows)
    amt_parsed = sum(p["amount"] for p in parsed)

    print(f"=== 자재 raw_description 파싱 커버리지 ===")
    print(f"  rows: {n_parsed}/{n_total} ({n_parsed/n_total*100:.1f}%)")
    print(f"  amount: {amt_parsed/1e6:.1f}M / {amt_total/1e6:.1f}M ({amt_parsed/amt_total*100:.1f}%)")
    print()
    print(f"{'wc':12s} {'n_parsed':>9s} {'n_total':>8s} {'cov':>6s} {'amt_parsed':>11s} {'amt_total':>10s} {'amt_cov':>8s}")
    for wc, st in sorted(by_wc.items(), key=lambda x: -x[1]["amount_total"]):
        if st["n_total"] == 0:
            continue
        n_cov = st["n_parsed"] / st["n_total"] * 100
        a_cov = st["amount_parsed"] / st["amount_total"] * 100 if st["amount_total"] else 0
        print(f"  {wc:10s} {st['n_parsed']:>7d}  {st['n_total']:>7d} {n_cov:>5.0f}%  "
              f"{st['amount_parsed']/1e6:>9.1f}M {st['amount_total']/1e6:>9.1f}M {a_cov:>7.0f}%")
    print()

    # 패턴별 분포
    by_pattern = defaultdict(lambda: {"n": 0, "amount": 0})
    for p in parsed:
        by_pattern[p["pattern"]]["n"] += 1
        by_pattern[p["pattern"]]["amount"] += p["amount"]
    print("=== 매칭 패턴 분포 ===")
    for pat, st in sorted(by_pattern.items(), key=lambda x: -x[1]["n"]):
        print(f"  {pat:25s} n={st['n']:>3d}  amt={st['amount']/1e6:>5.1f}M")
    print()

    # work_code × unit 단가 분포
    by_wc_unit: dict[tuple, list[float]] = defaultdict(list)
    for p in parsed:
        if p["unit_price"]:
            by_wc_unit[(p["work_code"], p["unit"])].append(p["unit_price"])

    print("=== work_code × unit 단가 분포 ===")
    print(f"  {'wc':10s} {'unit':6s} {'n':>3s} {'min':>10s} {'p25':>10s} {'median':>10s} {'p75':>10s} {'max':>10s}  {'CV':>5s}")
    for (wc, unit), prices in sorted(by_wc_unit.items()):
        if len(prices) < 2:
            continue
        prices_sorted = sorted(prices)
        n = len(prices_sorted)
        med = statistics.median(prices_sorted)
        p25 = prices_sorted[n // 4] if n >= 4 else prices_sorted[0]
        p75 = prices_sorted[3 * n // 4] if n >= 4 else prices_sorted[-1]
        cv = statistics.stdev(prices) / statistics.mean(prices) if len(prices) >= 2 and statistics.mean(prices) else 0
        print(f"  {wc:10s} {unit:6s} {n:>3d} "
              f"{prices_sorted[0]:>10.0f} {p25:>10.0f} {med:>10.0f} {p75:>10.0f} {prices_sorted[-1]:>10.0f}  {cv:>4.2f}")
    print()

    print("=== 미파싱 row 샘플 (top 20 by amount) ===")
    unparsed.sort(key=lambda x: -x["amount"])
    for u in unparsed[:20]:
        print(f"  [{u['work_code']:10s}] {u['amount']/1e3:>6.0f}K  '{(u['raw_description'] or '')[:60]}'")

    out = {
        "n_total":          n_total,
        "n_parsed":         n_parsed,
        "coverage_pct":     round(n_parsed / n_total * 100, 1) if n_total else 0,
        "amount_total":     amt_total,
        "amount_parsed":    amt_parsed,
        "amount_coverage_pct": round(amt_parsed / amt_total * 100, 1) if amt_total else 0,
        "by_workcode":      dict(by_wc),
        "by_pattern":       {k: dict(v) for k, v in by_pattern.items()},
        "by_wc_unit_distribution": {f"{wc}|{u}": prices for (wc, u), prices in by_wc_unit.items()},
        "parsed_sample":    parsed[:50],
        "unparsed_sample":  unparsed[:50],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")
    con.close()


if __name__ == "__main__":
    main()
