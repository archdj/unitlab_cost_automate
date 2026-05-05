# 미승인 IFC 부분 공종 검토

작성일: 2026-05-05

## 목적

전체 IFC 연결이 아직 승인되지 않았더라도, 일부 공종은 BIM 수량과 Notion 실제원가가 같은 정규화 공종에서 만날 수 있다.

단, 이 데이터는 총액 예측에 바로 섞으면 안 된다. `partial_ifc_workcode_reviews`에서 공종 단위로 검토 후 승인된 것만 별도 근거로 승격해야 한다.

## 하네스

후보 생성:

```powershell
python cost-analysis-program-plan\harness\scripts\report_partial_ifc_workcode_candidates.py
```

후보 리포트:

`cost-analysis-program-plan/harness/reports/partial_ifc_workcode_candidates.json`

DB review 테이블 생성/적재:

```powershell
python cost-analysis-program-plan\harness\scripts\seed_partial_ifc_workcode_reviews.py
```

스키마:

`cost-analysis-program-plan/harness/sql/partial_ifc_workcode_reviews_schema.sql`

## 현재 결과

```text
unapproved_ifc_records: 11
ifc_with_partial_candidates: 8
candidate: 22
review: 0
blocked: 88
min_actual_amount: 1,000,000원
```

공종별 후보:

```text
STR: 8건 / 136,757,074원
FIN: 4건 / 90,089,051원
EXT: 4건 / 77,317,560원
FUR: 4건 / 46,596,521원
MEP: 2건 / 8,196,510원
```

## 후보가 있는 IFC

```text
N-02-T-12-1 / 용인 남곡리 10평 쇼룸_2511126_창호수정.ifc
N-09-H-30 / 제주 안덕면 서광리 80-5 H-30_심의.ifc
N-18-T-12 / 충남 추부면_251022.ifc
N-19-T-12 / 경기도 성남시 수정구 상적동 2-1 근생 12평 _ 260226.ifc
N-20-경기-화성시-쌍학리-667 / 경기 화성시 비봉면 쌍학리 667-5_주택_S-18_박공_251106.ifc
N-21-서산-부석면-강수리-277 / 충남 서산시 강수리 277_260212.ifc
N-22-S-18 / 양평군_원덕리346-34_근생_s-18_260325.ifc
N-10-S-18 / 루떼르 포레_모델하우스_S-18_241229.ifc
```

## 막힌 IFC

source IFC 파일이 검증되지 않아 공종 부분 사용도 막음:

```text
N-02-T-12-1 / 용인 남곡리 10평 쇼룸_수정_250817(Recovery).ifc
N-22-S-18 / 양평군_원덕리346-34_근생_s-18_260319.ifc
N-IFC--------------------- / Unit Lab Template T Haus_2_240213.ifc
```

## 사용 규칙

`candidate`라도 바로 총액 예측에 넣지 않는다.

승격 조건:

```text
1. IFC 파일 원본 확인
2. 프로젝트 연결 확인
3. 모듈/평형 충돌이 있으면 공종 단위 사용 가능 범위 명시
4. 정규화 공종이 실제 업무상 같은 공종인지 검토
5. partial_ifc_workcode_reviews.approval_status = 'approved'
```

승격 후 사용 범위:

```text
공종 단가 참고: 가능
자재/수량 단가 후보: 가능
프로젝트 총액 산출 직접 반영: 신중
현장비/SITE 자동 보정: 금지
```

