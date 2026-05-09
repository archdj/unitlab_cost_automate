# DATA_INGEST_SPEC — 데이터 정제 (F1) + 업로드 (F4)

원본(노션·엑셀) → 정제 → 예측 입력으로 가는 파이프라인. 이 문서는 M0의 종료 조건을 책임진다.

## 1. F4.1 — 노션 원가 데이터 연결/가져오기

### 1.1 F4.1.1 워크스페이스 연결

- 입력: 사용자(Admin)가 입력한 노션 통합 토큰.
- 보관: 암호화 후 DB. `.env` 파일 직접 보관은 개발 환경 전용 (`.env.example` 만 git).
- 상태 확인: `GET /notion/connection` → `{connected, workspace_name, last_synced_at}`.

### 1.2 F4.1.2 DB 선택 + 필드 매핑

명세서 4.1.2 매핑 대상 → 시스템 표준 컬럼:

| 노션 필드 (원본) | 시스템 필드 | 필수 |
|---|---|---|
| (project) | project_id | ✅ |
| (date) | payment_date | ✅ |
| (item / 자재명) | item_name_raw | ✅ |
| (수량) | quantity | ✅ |
| (단위) | unit | ✅ |
| (금액) | amount_basis | ✅ |
| (공종) | work_code_raw | ✅ |
| (로스율) | loss_rate | 권장 |
| (실제 시공 원가 여부) | is_actual_construction | 권장 |

매핑 결과는 `harness/data_contracts/notion_actual_costs.md` 표준에 맞춰 정규화.

### 1.3 F4.1.3 가져오기 범위 + 미리보기

- 범위: `project IN (...)` AND `date BETWEEN ?, ?`.
- 미리보기: 최대 50행 + 컬럼별 누락률.

## 2. F4.2 — 엑셀 시공/자재 데이터 업로드

### 2.1 F4.2.1 업로드 + 시트 선택

- 지원 형식: `.xlsx`, `.xls`. 최대 50MB.
- 업로드 후: 시트 목록 + 첫 행 헤더 여부 토글.

### 2.2 F4.2.2 열 자동 인식 + 수동 매핑

자동 인식 우선순위 (헤더 텍스트 매칭 → 동의어 사전):

| 표준 컬럼 | 자동 인식 키워드 |
|---|---|
| item_name_raw | 자재, 품목, item, name |
| quantity | 수량, qty, 물량 |
| unit | 단위, unit, EA, m2, m3 |
| unit_price | 단가, price, unit_price |
| amount_basis | 금액, 공급가, supply |
| work_code_raw | 공종, work, category |

수동 재매핑 UI는 F4.2.2 수용기준에 따라 미인식 컬럼 강조.

### 2.3 F4.2.3 유효성 검사 + 오류 리포트

검증 규칙 (`harness/scripts/validate_upload.py` 출력):

- 필수 열 누락 → block
- 숫자 형식 오류 (`quantity`, `unit_price`) → 행 단위 reject + 사유 표시
- 단위 불일치 (`m²` vs `m2`) → 자동 normalize 시도 → 실패 시 매핑 후보 제시
- 음수/0 금액 → warn

## 3. F1.1 — 자재 원가 추출 + 공종별 옵션 생성

### 3.1 F1.1.1 추출 규칙

설정 가능 항목:

- 자재 단가 산정: `amount_basis / quantity` (기본) 또는 별도 `unit_price` 컬럼 사용.
- 간접비 포함 여부: include / exclude / 별도 카테고리.
- 로스율 적용 방식: `quantity * (1 + loss_rate)`(기본) / 단가에 가산 / 미적용.

규칙은 DB `cost_extraction_rules` 테이블에 저장.

### 3.2 F1.1.2 옵션 미리보기 + 수정

자동 생성 옵션 = `(work_code, item_name, unit)` 튜플의 distinct.
사용자가 항목명/단위/분류를 수정 → `master_options` 에 저장 (F9 마스터와 연결).

### 3.3 F1.1.3 예측 입력으로 연결

확정된 옵션은 F6 프로젝트 조건 입력 폼의 셀렉트 박스 source로 사용.

## 4. F1.2 — 공종/자재 매핑 + 단위 표준화

### 4.1 F1.2.1 동의어 매핑

- 템플릿: `harness/mapping/work_synonym_template.csv`.
- 컬럼: `source_value, target_work_code, mapping_status, confidence, reviewer, note`.
- `mapping_status ∈ {candidate, rule_matched, confirmed}`. **`confirmed`만 자동 적용** (cost-analysis-program-plan harness 원칙 준용).

### 4.2 F1.2.2 단위 변환

- 템플릿: `harness/mapping/unit_conversion_template.csv`.
- 컬럼: `source_unit, target_unit, multiplier, status, note`.
- 기존 표준 (`m³`→`m3`, `㎡`→`m2`) 은 `confirmed` 시드.

## 5. F1.3 — 정제 결과 검토 + 예외 처리

### 5.1 F1.3.1 누락/이상치 탐지

스크립트 `harness/scripts/profile_ingested_data.py` 출력:

- `null_rate_by_column`
- `outliers_by_unit_price` (IQR × 1.5 또는 z-score > 3)
- `unit_price_volatility` (자재별 시계열 변동 계수 > 임계값)

결과는 `harness/reports/ingest_profile.json`.

### 5.2 F1.3.2 정제 규칙 편집 + 재처리

- 규칙 편집 UI → `cost_extraction_rules.version` 증가.
- 재처리 = 해당 데이터셋에 새 규칙 재적용 후 `actual_costs_normalized` 갱신.

## 6. 작업 항목

- [ ] `src/notion_client.py` — 노션 연결/조회 (F4.1)
- [ ] `src/excel_loader.py` — 엑셀 파싱 + 시트/열 인식 (F4.2)
- [ ] `harness/scripts/validate_upload.py` — F4.2.3
- [ ] `harness/scripts/profile_ingested_data.py` — F1.3.1
- [ ] `harness/scripts/normalize_units.py` — F1.2.2 (`unit_conversion_template.csv` 적용)
- [ ] `harness/sql/cost_extraction_rules_schema.sql` — F1.1.1
- [ ] `harness/sql/master_options_schema.sql` — F1.1.2

## 7. 가정·결정 사항

- 노션 ETL은 기존 `unitlab-cost-analysis/agents/notion_etl.py`를 베이스로 재사용 (덮지 않고 import).
- 미매핑 항목은 **계산에서 제외**하고 `근거 부족`으로 표시 (cost-analysis-program-plan/PLAN.md 원칙).
