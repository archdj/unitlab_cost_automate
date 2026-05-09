"""work_code 매핑 사전 — 단일 진실원.

운영 ETL WORK_MAP + 우리 견적서 카테고리 + raw_description 키워드를 통합.
모두 level=2 work_code 로 정규화.

검증: validate_work_code_mapping.py 의 결과 + work_codes 테이블 38개 level2 코드 기준.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# 견적서 파일명 → work_code (level=2)
# ─────────────────────────────────────────────────────────────────────────────
# 가장 구체적인 키워드부터 일반적 키워드 순. 첫 매칭 채택.
FILENAME_TO_WC: list[tuple[str, str, str]] = [
    # === 외부 마감 ===
    ("폴딩도어",       "EXT-WIN",   "high"),   # 폴딩도어는 외부 창호
    ("폴딩",          "EXT-WIN",   "high"),
    ("창호",          "EXT-WIN",   "high"),
    ("외장재",        "EXT-CLAD",  "high"),
    ("외장",          "EXT-CLAD",  "high"),
    ("징크",          "EXT-ROOF",  "high"),
    ("후레싱",        "EXT-ROOF",  "high"),
    ("후레쉬",        "EXT-ROOF",  "high"),
    ("처마",          "EXT-ROOF",  "high"),
    ("지붕",          "EXT-ROOF",  "high"),
    ("어닝",          "EXT-CAN",   "high"),
    ("캐노피",        "EXT-CAN",   "high"),
    ("데크",          "EXT-DECK",  "high"),
    ("베리어프리",    "EXT-ACC",   "medium"),
    ("배리어프리",    "EXT-ACC",   "medium"),
    # === 내부 마감 ===
    ("판넬",          "FIN-PANEL", "high"),
    ("패널",          "FIN-PANEL", "high"),
    ("샌드위치",      "FIN-PANEL", "high"),
    ("바닥난방",      "MEP-HVAC",  "high"),   # 운영 ETL은 MEP-PLMB-004 이지만 난방 의미상 HVAC가 더 가까움
    ("난방",          "MEP-HVAC",  "high"),
    ("바닥",          "FIN-FLOOR", "high"),   # 바닥난방 보다 후순위에 있어야
    ("마루",          "FIN-FLOOR", "high"),
    ("리모델링월",    "FIN-FLOOR", "high"),   # 강마루 브랜드
    ("리모델",        "FIN-FLOOR", "high"),
    ("장판",          "FIN-FLOOR", "high"),
    ("타일",          "FIN-TILE",  "high"),
    ("도배",          "FIN-WALL",  "high"),
    ("천장",          "FIN-CEIL",  "high"),
    ("돔천장",        "FIN-CEIL",  "high"),
    ("도장",          "FIN-PAINT", "high"),
    ("페인트",        "FIN-PAINT", "high"),
    ("방수",          "FIN-WTP",   "high"),
    ("실리콘",        "FIN-WTP",   "medium"),
    ("단열",          "FIN-INS",   "high"),
    ("경량",          "FIN-LGS",   "high"),
    ("스카이비바",    "FIN-LGS",   "high"),
    ("스터드",        "FIN-LGS",   "high"),
    ("석고",          "FIN-LGS",   "medium"),
    ("목자재",        "FIN-CARP",  "high"),
    ("목공",          "FIN-CARP",  "high"),
    ("수장",          "FIN-CARP",  "high"),
    ("CS",            "FIN-LGS",   "high"),
    ("미네랄울",      "FIN-LGS",   "high"),
    # === 가구 / 욕실 / 가전 ===
    ("욕실",          "FUR-BATH",  "high"),
    ("도기",          "FUR-BATH",  "high"),
    ("수전",          "FUR-BATH",  "high"),
    ("주방가구",      "FUR-KITCH", "high"),
    ("주방",          "FUR-KITCH", "high"),
    ("냉장고",        "FUR-KITCH", "high"),    # 빌트인 가전
    ("세탁기",        "FUR-KITCH", "high"),
    ("인덕션",        "FUR-KITCH", "high"),
    ("후드",          "FUR-KITCH", "medium"),
    ("붙박이",        "FUR-BUILT", "high"),
    ("선반",          "FUR-BUILT", "high"),
    ("커튼",          "FUR-SOFT",  "high"),
    ("스크린",        "FUR-SOFT",  "high"),
    ("블라인드",      "FUR-SOFT",  "high"),
    # === 도어 ===
    ("현관문",        "FUR-DOOR",  "high"),
    ("실내문",        "FUR-DOOR",  "high"),
    ("도어락",        "FUR-DOOR",  "high"),
    ("문틀",          "FUR-DOOR",  "high"),
    ("방화문",        "FUR-DOOR",  "high"),
    ("도어",          "FUR-DOOR",  "medium"), # generic, 후순위
    # === MEP ===
    ("전기",          "MEP-ELEC",  "high"),
    ("조명",          "MEP-ELEC",  "high"),
    ("콘센트",        "MEP-ELEC",  "high"),
    ("스위치",        "MEP-ELEC",  "high"),
    ("외부등",        "MEP-ELEC",  "high"),
    ("외부벽등",      "MEP-ELEC",  "high"),
    ("간접조명",      "MEP-ELEC",  "high"),
    ("등기구",        "MEP-ELEC",  "high"),
    ("사이니지",      "MEP-SIGN",  "high"),
    ("배관",          "MEP-PLMB",  "high"),
    ("설비",          "MEP-PLMB",  "high"),
    ("스텐홈통",      "MEP-PLMB",  "high"),
    ("선홈통",        "MEP-PLMB",  "high"),
    ("환풍기",        "MEP-HVAC",  "high"),
    ("환기",          "MEP-HVAC",  "high"),
    ("공조",          "MEP-HVAC",  "high"),
    ("에어컨",        "MEP-HVAC",  "high"),
    ("보일러",        "MEP-HVAC",  "high"),
    ("스마트홈",      "MEP-IOT",   "high"),
    ("IoT",           "MEP-IOT",   "high"),
    ("소방",          "MEP-FIRE",  "high"),
    # === 구조 ===
    ("골조",          "STR-ST",    "high"),
    ("철강",          "STR-ST",    "high"),
    ("H형강",         "STR-ST",    "high"),
    ("ALC",           "STR-ALC",   "high"),
    ("CLT",           "STR-CLT",   "high"),
    ("기초",          "STR-FND",   "high"),
    ("잡철",          "STR-MISC",  "high"),
    ("잡자재",        "STR-MISC",  "medium"), # 잡종 자재
    ("인양고리",      "STR-MISC",  "high"),
    ("화스너",        "STR-MISC",  "medium"),
    # === SITE ===
    ("운반",          "SITE-MISC", "high"),
    ("운송",          "SITE-MISC", "high"),
    ("입주청소",      "SITE-MISC", "high"),
    ("청소",          "SITE-MISC", "high"),
    ("폐기",          "SITE-MISC", "high"),
    ("소모품",        "SITE-MISC", "high"),
    ("상차",          "SITE-MOD",  "high"),
    ("하차",          "SITE-MOD",  "high"),
    ("크레인",        "SITE-MOD",  "high"),
    ("지게차",        "SITE-MOD",  "high"),
    ("양중",          "SITE-MOD",  "high"),
    ("현장설치",      "SITE-MOD",  "high"),
    ("재설치",        "SITE-MOD",  "high"),
    ("토목",          "SITE-EARTH","high"),
    ("토공",          "SITE-EARTH","high"),
    ("철거",          "SITE-DEMO", "high"),
    ("조경",          "SITE-LAND", "high"),
    # === 가구(generic, 마지막) ===
    ("가구",          "FUR-KITCH", "low"),    # 단독 "가구" 키워드는 보통 주방가구
]


# ─────────────────────────────────────────────────────────────────────────────
# 프로젝트 키워드 → project_code
# ─────────────────────────────────────────────────────────────────────────────
PROJ_KEYWORDS: list[tuple[str, str]] = [
    # 가장 구체적인 것부터
    ("남기동길에스테라고", "N-13-T-15-3"),    # 견적서 파일명에 두 프로젝트 합쳐있는 케이스
    ("제주서광리홍천청주", "N-09-H-30"),       # multi-project 견적서 — 가장 큰 1개로 매핑
    ("다랑논에스테라고",   "N-04-S-30"),
    ("남기동길",          "N-13-T-15-3"),
    ("에스테라고",        "N-07-U-6-1"),       # 또는 N-08-U-6-1 (1동/2동)
    ("다랑논",           "N-04-S-30"),
    ("다랑협동",         "N-04-S-30"),
    ("밀양",             "N-04-S-30"),
    ("노천리",           "N-01-T-15"),
    ("홍천",             "N-01-T-15"),
    ("제주",             "N-09-H-30"),
    ("서광리",           "N-09-H-30"),
    ("수지",             "N-07-U-6-1"),
    ("용인",             "N-16-T-12"),
    ("남곡리",           "N-16-T-12"),
    ("기흥",             "N-16-T-12"),         # 기흥쇼룸 = 용인
    ("쇼룸",             "N-02-T-12-1"),
    ("미원면",           "N-11-T-12"),
    ("청주미원면",        "N-11-T-12"),
    ("남이면",           "N-15-청주-남이면-가마리-산6-1"),
    ("가마리",           "N-15-청주-남이면-가마리-산6-1"),
    ("청주",             "N-11-T-12"),         # generic, 후순위
    ("성남",             "N-19-T-12"),
    ("상적동",           "N-19-T-12"),
    ("금산",             "N-18-T-12"),
    ("마전리",           "N-18-T-12"),
    ("화성",             "N-20-경기-화성시-쌍학리-667"),
    ("쌍학리",           "N-20-경기-화성시-쌍학리-667"),
    ("서산",             "N-21-서산-부석면-강수리-277"),
    ("강수리",           "N-21-서산-부석면-강수리-277"),
    ("농어촌",           "N-03-농어촌-공사"),
    ("루떼르",           "N-10-S-18"),
    ("루뗴르",           "N-10-S-18"),
    ("루떼",             "N-10-S-18"),
    ("포레",             "N-10-S-18"),
    ("롯데아울렛",        "N-17-롯데아울렛-팝업스토어"),
    ("팝업",             "N-17-롯데아울렛-팝업스토어"),
    ("테스트베드",        "N-UNMATCHED"),
    ("쇼룸하우스",        "N-02-T-12-1"),
    ("기존부지",          "N-UNMATCHED"),
    ("산6-1",            "N-15-청주-남이면-가마리-산6-1"),
]


def classify_filename_v2(decoded_name: str) -> dict:
    """파일명 → vendor / project_code / work_code (가장 구체적 매칭)."""
    name = decoded_name
    out = {"vendor": None, "project_code": None, "work_code": None,
           "wc_confidence": None, "tags": []}
    # vendor — 첫 _ 앞
    import re
    parts = re.split(r"[_\-]", name)
    if parts:
        out["vendor"] = parts[0].strip()
    # project — 첫 매칭
    for kw, code in PROJ_KEYWORDS:
        if kw in name:
            out["project_code"] = code
            out["tags"].append(f"proj:{kw}")
            break
    # work_code — 첫 매칭 (FILENAME_TO_WC 는 이미 구체적 → 일반적 순)
    for kw, wc, conf in FILENAME_TO_WC:
        if kw in name:
            out["work_code"] = wc
            out["wc_confidence"] = conf
            out["tags"].append(f"cat:{kw}")
            break
    return out


def classify_raw_description(desc: str) -> dict:
    """actual_cost.raw_description (자재명) → work_code 후보.

    파일명 분류와 같은 키워드 사전을 사용. raw_description 은 길이 짧고
    프로젝트명 prefix 가 흔히 붙어서 (예: '홍천_외장재') 동일하게 동작.
    """
    return classify_filename_v2(desc or "")
