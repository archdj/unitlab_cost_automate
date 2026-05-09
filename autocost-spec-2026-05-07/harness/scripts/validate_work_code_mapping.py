"""work_code 매핑 사전 검증.

3개 source 비교:
1. 우리 parse_excel_quotes.CATEGORY_KEYWORDS
2. cost-analysis/agents/notion_etl.WORK_MAP (운영 ETL)
3. cost_analysis.db work_codes 테이블 (실제 등록된 코드)

불일치 또는 존재하지 않는 코드 dump.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness" / "scripts"))

from src.config import OPERATIONAL_DB
from parse_excel_quotes import CATEGORY_KEYWORDS, PROJ_KEYWORDS

LOG: list[str] = []
def log(s=""): LOG.append(str(s))


# 운영 ETL WORK_MAP — notion_etl.py 에서 복사
ETL_WORK_MAP = {
    "01. 골조":       "STR-ST",
    "02. 판넬":       "FIN-PANEL",
    "03. 창호":       "EXT-WIN",
    "04. 폴딩도어":    "EXT-WIN",
    "05. 전기":       "MEP-ELEC",
    "06. 설비":       "MEP-PLMB",
    "07. 환기/공조":  "MEP-HVAC",
    "08. 현관문":     "FUR-DOOR",
    "09. 징크후레싱": "EXT-ROOF-003",
    "10. 외장":       "EXT-CLAD",
    "11. 바닥난방":   "MEP-PLMB-004",
    "12. 마루":       "FIN-FLOOR",
    "13. 경량":       "FIN-LGS",
    "14. 수장/도어":  "FIN-CARP",
    "15. 타일":       "FIN-TILE",
    "16. 도기":       "FUR-BATH",
    "17. 돔천장":     "FIN-CEIL",
    "18. 패키지":     "FUR",
    "19. 스크린":     "FUR-SOFT",
    "20. 가구":       "FUR",
    "21. 도배":       "FIN-WALL-003",
    "22. 마감실리콘": "FIN",
    "24. 보일러":     "MEP-HVAC-004",
    "25. 상차크레인": "SITE-MOD-001",
    "25. 입주청소":   "SITE-MISC-003",
    "26. 운반":       "SITE-MISC-002",
    "28. 하차크레인": "SITE-MOD-001",
    "29. 현장설치":   "SITE-MOD-002",
    "29.데크":        "EXT-DECK",
    "30. 소모품":     "SITE-MISC",
    "31. 폐기물":     "SITE-MISC-003",
    "32. 기타":       "SITE-MISC",
    "32. 에어컨":     "MEP-HVAC-001",
    "33. 냉장고":     "FUR",
    "34. 세탁기":     "FUR",
    "ALC":            "STR-ALC",
    "CS":             "FIN-LGS",
    "기초":           "STR-FND",
    "목공":           "FIN-CARP",
    "어닝":           "EXT-CAN",
    "잡철":           "STR-MISC",
    "재설치":         "SITE-MOD-002",
    "처마":           "EXT-ROOF",
    "커튼":           "FUR-SOFT",
    "토목":           "SITE-EARTH",
}


def main():
    con = sqlite3.connect(f"file:{OPERATIONAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    # 1) work_codes 테이블에 등록된 모든 코드 (level=2 우선)
    all_codes = {r["work_code"] for r in con.execute("SELECT work_code FROM work_codes")}
    level2_codes = {r["work_code"] for r in con.execute("SELECT work_code FROM work_codes WHERE level=2")}

    log(f"=== 우리 CATEGORY_KEYWORDS 검증 ===")
    log(f"keyword → work_code (work_codes 테이블 존재 여부)")
    issues = []
    for kw, wc in CATEGORY_KEYWORDS.items():
        in_db = wc in all_codes
        in_level2 = wc in level2_codes
        if not in_db:
            log(f"  ❌ {kw:10s} → {wc} (DB에 없음)")
            issues.append((kw, wc, "not_in_db"))
        elif not in_level2:
            log(f"  ⚠️  {kw:10s} → {wc} (level3, normalize 필요)")
            issues.append((kw, wc, "level3"))

    log()
    log(f"=== 우리 vs 운영 ETL WORK_MAP 비교 ===")
    log("같은 키워드인데 다른 work_code 매핑")
    diff_count = 0
    for our_kw, our_wc in CATEGORY_KEYWORDS.items():
        # ETL의 키 중 our_kw 가 substring 인 것
        for etl_kw, etl_wc in ETL_WORK_MAP.items():
            if our_kw in etl_kw and our_wc != etl_wc:
                log(f"  '{our_kw}' → 우리 {our_wc:15s}  vs ETL '{etl_kw}' → {etl_wc}")
                diff_count += 1
                break
    log(f"불일치 키워드: {diff_count}")
    log()

    # 2) PROJ_KEYWORDS 검증 — projects 테이블에 project_code 존재 여부
    log(f"=== PROJ_KEYWORDS 검증 ===")
    proj_codes_in_db = {r["project_code"] for r in con.execute("SELECT project_code FROM projects")}
    proj_issues = []
    for kw, code in PROJ_KEYWORDS.items():
        if code == "N-UNMATCHED":
            continue
        if code not in proj_codes_in_db:
            log(f"  ❌ '{kw}' → {code} (projects 테이블에 없음)")
            proj_issues.append((kw, code))

    log()
    log(f"=== ETL WORK_MAP 의 unique work_codes 중 work_codes 테이블 매칭 ===")
    for etl_kw, etl_wc in ETL_WORK_MAP.items():
        in_db = etl_wc in all_codes
        in_level2 = etl_wc in level2_codes
        if not in_db:
            # parent 추측
            parent = "-".join(etl_wc.split("-")[:2]) if "-" in etl_wc else etl_wc
            parent_in = parent in level2_codes
            log(f"  ⚠️  '{etl_kw}' → {etl_wc} (없음) → parent {parent} {'✓' if parent_in else '✗'}")

    log()
    log(f"=== work_codes 테이블 level=2 코드 전체 ({len(level2_codes)}개) ===")
    for r in con.execute("""
        SELECT work_code, work_name_ko, category FROM work_codes WHERE level=2 ORDER BY category, work_code
    """):
        log(f"  {r[0]:12s} {(r[1] or ''):20s}  ({r[2]})")

    out = ROOT / "harness" / "reports" / "_work_code_mapping_validation.txt"
    out.write_text("\n".join(LOG), encoding="utf-8")
    con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"ERROR: {e}\n{traceback.format_exc()}")
        out = ROOT / "harness" / "reports" / "_work_code_mapping_validation.txt"
        out.write_text("\n".join(LOG), encoding="utf-8")
