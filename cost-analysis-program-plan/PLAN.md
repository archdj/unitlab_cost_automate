# 현실 데이터 기반 원가 분석 프로그램 계획서

## 1. 원칙

이 프로그램은 추정, 추천, 일반론이 아니라 실제 보유 데이터에 근거한 원가 분석 시스템으로 만든다.

분석 결과는 반드시 다음 중 하나 이상의 실제 데이터에 근거해야 한다.

- 실제 결제가 완료된 원가 데이터
- 결제 증빙 데이터
- 계약 데이터
- BIM 물량 데이터
- 자재 DB
- 업체 DB
- 프로젝트/현장 데이터

데이터로 확인되지 않는 값은 계산 결과로 사용하지 않는다. 데이터가 부족한 경우에는 임의 추천을 하지 않고 `근거 부족`, `매핑 불가`, `검증 필요`로 표시한다.

## 2. 목표

보유한 실제 결제 원가 데이터와 BIM 물량 데이터를 연결해 프로젝트별, 공종별, 자재별, 업체별 실적 원가를 분석한다.

핵심 목표:

- 실제 결제된 금액에서 실적 단가를 산출한다.
- BIM 물량과 실제 결제 원가를 연결한다.
- 자재 DB와 업체 DB를 기준으로 원가 데이터를 표준화한다.
- 신규 또는 진행 중 프로젝트의 BIM 물량에 실제 실적 단가를 적용한다.
- 모든 예상 원가 결과에 근거 데이터를 함께 표시한다.
- 근거가 부족한 항목은 계산에서 분리하고 별도 검토 대상으로 표시한다.

## 3. 분석 대상 데이터

### 실제 결제 원가 데이터

분석의 기준 데이터다. 실제 돈이 지급된 내역만 실적 원가로 인정한다.

필요 컬럼 예시:

- 프로젝트 ID
- 결제 ID
- 결제일
- 업체 ID
- 원본 품목명
- 수량
- 단위
- 공급가액
- 부가세
- 총 지급액
- 계약 ID
- 증빙 ID

### BIM 물량 데이터

원가를 적용할 물량 기준 데이터다.

필요 컬럼 예시:

- 프로젝트 ID
- BIM 객체 GUID
- 객체 카테고리
- 패밀리명
- 타입명
- 층/구역
- 물량
- 단위
- 원본 속성 JSON

### 자재 DB

결제 품목과 BIM 객체를 표준 자재 기준으로 묶기 위한 기준 데이터다.

필요 컬럼 예시:

- 자재 ID
- 표준 자재명
- 규격
- 단위
- 자재 분류
- 별칭
- 제조사 또는 브랜드

### 업체 DB

결제 원가를 업체 기준으로 분석하기 위한 기준 데이터다.

필요 컬럼 예시:

- 업체 ID
- 업체명
- 사업자번호
- 지역
- 취급 공종
- 취급 자재
- 계약 이력
- 내부 평가 정보가 있다면 해당 값

### 계약/증빙 데이터

결제 원가의 근거와 조건을 확인하기 위한 데이터다.

필요 컬럼 예시:

- 계약 ID
- 프로젝트 ID
- 업체 ID
- 계약일
- 계약 금액
- 계약 품목
- 계약 수량
- 계약 단위
- 증빙 파일 ID
- 세금계산서 번호

## 4. 데이터 연결 기준

이 시스템의 핵심은 계산 모델이 아니라 데이터 연결 기준이다.

연결해야 하는 항목:

- 결제 품목명과 자재 DB의 표준 자재
- BIM 객체와 공종/자재
- 결제건과 업체
- 결제건과 프로젝트
- 결제건과 계약/증빙
- BIM 물량과 실제 결제 물량

연결 결과는 반드시 신뢰도를 남긴다.

매핑 상태:

- `confirmed`: 사람이 확인했거나 명확한 코드로 연결됨
- `rule_matched`: 규칙으로 연결됨
- `candidate`: 후보로만 연결됨
- `unmatched`: 연결 불가

`candidate`와 `unmatched`는 원가 계산에 자동 반영하지 않는다.

## 5. 데이터 모델

### 주요 엔티티

- `Project`: 프로젝트/현장
- `BimElement`: BIM 객체
- `WorkItem`: 공종 또는 내역 항목
- `Material`: 자재
- `Vendor`: 업체
- `Payment`: 결제건
- `Invoice`: 세금계산서/청구서/증빙
- `Contract`: 계약
- `CostRecord`: 실적 원가 기록
- `UnitPrice`: 실제 단가
- `MappingRule`: 매핑 규칙
- `MappingReview`: 매핑 검토 이력

### 주요 관계

- `Project` contains `BimElement`
- `BimElement` maps_to `WorkItem`
- `BimElement` maps_to `Material`
- `Payment` belongs_to `Project`
- `Payment` paid_to `Vendor`
- `Payment` references `Contract`
- `Payment` has_evidence `Invoice`
- `Payment` creates `CostRecord`
- `CostRecord` uses `Material`
- `CostRecord` has_unit_price `UnitPrice`
- `Vendor` supplied `Material`

## 6. DB 테이블 초안

### projects

| 컬럼 | 설명 |
|---|---|
| id | 프로젝트 ID |
| name | 프로젝트명 |
| location | 지역 |
| start_date | 착공일 |
| end_date | 준공일 |
| building_type | 건물 유형 |

### bim_elements

| 컬럼 | 설명 |
|---|---|
| id | 내부 ID |
| project_id | 프로젝트 ID |
| element_guid | BIM GUID |
| category | BIM 카테고리 |
| family_name | 패밀리명 |
| type_name | 타입명 |
| level | 층/레벨 |
| zone | 구역 |
| quantity | 물량 |
| unit | 단위 |
| raw_properties | 원본 속성 JSON |

### materials

| 컬럼 | 설명 |
|---|---|
| id | 자재 ID |
| standard_code | 표준 자재 코드 |
| name | 표준 자재명 |
| spec | 규격 |
| unit | 표준 단위 |
| category | 자재 분류 |
| aliases | 별칭 목록 |

### vendors

| 컬럼 | 설명 |
|---|---|
| id | 업체 ID |
| name | 업체명 |
| business_no | 사업자번호 |
| region | 지역 |
| trade_types | 취급 공종/자재 |
| source_system | 원본 시스템 |

### payments

| 컬럼 | 설명 |
|---|---|
| id | 결제 ID |
| project_id | 프로젝트 ID |
| vendor_id | 업체 ID |
| payment_date | 결제일 |
| item_name_raw | 원본 품목명 |
| quantity | 수량 |
| unit | 단위 |
| supply_amount | 공급가액 |
| vat | 부가세 |
| total_amount | 총 지급액 |
| contract_id | 계약 ID |
| invoice_id | 증빙 ID |
| raw_data | 원본 행 JSON |

### cost_records

| 컬럼 | 설명 |
|---|---|
| id | 원가 기록 ID |
| payment_id | 결제 ID |
| project_id | 프로젝트 ID |
| material_id | 자재 ID |
| work_item_id | 공종 ID |
| vendor_id | 업체 ID |
| quantity | 표준화 수량 |
| unit | 표준화 단위 |
| amount_basis | 단가 계산에 사용한 금액 기준 |
| unit_price | 실적 단가 |
| mapping_status | 매핑 상태 |
| confidence | 매핑 신뢰도 |

### mapping_reviews

| 컬럼 | 설명 |
|---|---|
| id | 검토 ID |
| source_type | payment, bim_element 등 |
| source_id | 원본 데이터 ID |
| target_type | material, work_item 등 |
| target_id | 연결 대상 ID |
| status | confirmed, rejected |
| reviewer | 검토자 |
| reviewed_at | 검토 시각 |
| note | 검토 메모 |

## 7. 원가 계산 원칙

### 실적 단가

실적 단가는 실제 결제 데이터를 기준으로 계산한다.

```text
실적 단가 = 단가 계산 기준 금액 / 표준화 수량
```

단가 계산 기준 금액은 데이터 상태에 따라 명확히 구분한다.

- 공급가액 기준
- 부가세 포함 총액 기준
- 운반비 포함 기준
- 노무비 포함 기준
- 계약 단가 기준
- 실제 지급액 기준

서로 다른 기준의 단가는 섞어서 평균 내지 않는다.

### BIM 원가 적용

BIM 원가 적용은 confirmed 또는 rule_matched 상태의 매핑만 사용한다.

```text
BIM 적용 원가 = BIM 표준화 물량 x 실제 실적 단가
```

단가 근거가 여러 개일 경우 다음 값을 함께 표시한다.

- 결제건 수
- 최소 단가
- 최대 단가
- 평균 단가
- 중앙값
- 최근 결제일
- 적용한 금액 기준
- 적용한 단위 기준

어떤 값을 대표 단가로 사용할지는 데이터 검토 후 확정한다. 문서에서는 특정 방식의 우선순위를 정하지 않는다.

## 8. 데이터 품질 검증

계산 전 반드시 검증한다.

검증 항목:

- 수량이 비어 있는 결제건
- 단위가 없는 결제건
- 금액이 0이거나 음수인 결제건
- 같은 결제 ID의 중복
- 같은 증빙 번호의 중복
- 업체 ID가 없는 결제건
- 자재 매핑이 안 된 결제건
- BIM 물량 단위가 자재 표준 단위와 다른 항목
- BIM 물량은 있으나 결제 근거가 없는 항목
- 결제 근거는 있으나 BIM 물량과 연결되지 않는 항목

검증 결과는 계산 결과와 분리해 별도 리포트로 제공한다.

## 9. 분석 결과 화면

화면은 추천이 아니라 근거 확인 중심으로 구성한다.

필수 화면:

1. 데이터 업로드/연결 상태
2. 프로젝트별 BIM 물량 목록
3. 결제 원가 목록
4. 자재/공종 매핑 현황
5. 실적 단가 산출 결과
6. BIM 원가 적용 결과
7. 결제 근거 상세
8. 업체별 실제 결제 단가 비교
9. 데이터 품질 오류 목록
10. 매핑 검토 화면

결과 예시:

```text
프로젝트: 현장 A
BIM 객체: GUID-001
자재 매핑: 레미콘 25-24-150
매핑 상태: confirmed
BIM 물량: 320 m3
적용 단가 기준: 실제 지급액 / m3
근거 결제건 수: 17건
실적 단가 평균: 92,000원/m3
실적 단가 중앙값: 90,500원/m3
최소/최대: 88,500원/m3 / 97,200원/m3
적용 원가: 29,440,000원
검토 필요: 없음
```

근거 부족 예시:

```text
BIM 객체: GUID-018
원본 타입명: Concrete_C25
물량: 42 m3
매핑 상태: candidate
계산 상태: 제외
사유: 자재 DB의 표준 자재와 자동 확정 불가
필요 조치: 매핑 검토
```

## 10. OpenCrab 활용 계획

OpenCrab은 분석 결과를 임의로 만들어내는 용도가 아니라 근거 추적과 관계 검색 용도로 사용한다.

사용 목적:

- 결제건, 자재, 업체, BIM 객체 사이의 관계 저장
- 특정 원가 결과의 근거 결제건 추적
- 매핑 검토 이력 검색
- 자연어로 데이터 근거 조회

예상 질문:

- "이 BIM 객체에 적용된 단가의 근거 결제건을 보여줘."
- "이 자재와 연결된 실제 결제 데이터를 모두 보여줘."
- "이 업체가 공급한 자재와 결제 단가 이력을 보여줘."
- "매핑 불가로 제외된 BIM 객체를 보여줘."
- "BIM 물량은 있는데 결제 근거가 없는 항목을 보여줘."

OpenCrab 노드 예시:

```json
{
  "space": "resource",
  "node_type": "CostRecord",
  "node_id": "costrecord-001",
  "properties": {
    "project_id": "project-a",
    "payment_id": "payment-001",
    "material_id": "mat-remicon-25-24-150",
    "vendor_id": "vendor-a",
    "quantity": 320,
    "unit": "m3",
    "unit_price": 92000,
    "amount_basis": "actual_paid_amount",
    "mapping_status": "confirmed",
    "payment_date": "2025-11-18"
  }
}
```

## 11. 개발 단계

### Phase 1. 실제 데이터 구조 확인

목표:

- 보유 데이터의 컬럼과 원본 형식을 확인한다.
- 어떤 데이터가 실제 결제 근거인지 구분한다.
- 계산에 사용할 수 없는 데이터를 분리한다.

산출물:

- 데이터 소스 목록
- 컬럼 정의서
- 샘플 데이터
- 데이터 품질 이슈 목록

### Phase 2. 표준화 기준 작성

목표:

- 자재 표준명과 단위를 확정한다.
- 업체 식별 기준을 확정한다.
- 결제 금액 기준을 확정한다.
- BIM 물량 단위와 결제 단위를 연결한다.

산출물:

- `materials_master.csv`
- `vendors_master.csv`
- `unit_conversion_rules.csv`
- `mapping_rules.csv`

### Phase 3. 결제 기반 실적 단가 생성

목표:

- 실제 결제건에서 실적 단가를 계산한다.
- 계산 불가 결제건은 제외 사유를 남긴다.
- 단가 근거와 계산 기준을 저장한다.

산출물:

- `cost_records`
- 실적 단가 리포트
- 계산 제외 목록

### Phase 4. BIM 물량 연결

목표:

- BIM 객체와 자재/공종을 연결한다.
- 확정 매핑과 검토 필요 매핑을 분리한다.
- BIM 물량에 실적 단가를 적용한다.

산출물:

- BIM 매핑 테이블
- BIM 원가 적용 결과
- 매핑 검토 목록

### Phase 5. 근거 추적 그래프 구축

목표:

- 프로젝트, BIM 객체, 자재, 업체, 결제건, 원가 기록을 그래프로 연결한다.
- 모든 원가 결과에서 근거 결제건까지 추적 가능하게 한다.

산출물:

- OpenCrab ingest 데이터
- 관계 그래프
- 근거 조회 질의 예시

### Phase 6. 웹앱 MVP

목표:

- 실제 데이터를 업로드하거나 연결한다.
- 매핑 상태를 확인한다.
- 실적 단가와 BIM 적용 원가를 조회한다.
- 근거 결제건을 확인한다.

산출물:

- 로컬 실행 가능한 MVP
- 데이터 품질 리포트
- 원가 분석 리포트

## 12. 기술 스택

기술 선택도 실제 데이터 처리와 검증 가능성을 기준으로 한다.

기본 구성:

- Python
- Pandas
- PostgreSQL
- FastAPI
- SQLAlchemy
- Streamlit 또는 React
- OpenCrab MCP

BIM 데이터가 IFC일 경우:

- IfcOpenShell

문서와 PDF 증빙 분석이 필요한 경우:

- RAG-Anything
- Langent

## 13. 다음 액션

다음 정보가 필요하다.

1. 실제 결제 원가 데이터 컬럼
2. BIM 물량 데이터 컬럼
3. 자재 DB 컬럼
4. 업체 DB 컬럼
5. 계약/증빙 데이터 컬럼
6. 각 데이터의 원본 형식: Excel, CSV, DB, ERP export, IFC 등
7. 실제 결제 기준 금액이 무엇인지: 공급가액, 총액, 실지급액 등

원본 데이터를 공유하기 어렵다면 실제 값은 익명화하고 컬럼명과 샘플 5행만 사용한다.

## 14. 성공 기준

MVP 성공 기준:

- 실제 결제 데이터에서 실적 단가가 계산된다.
- 계산에 사용된 금액 기준과 수량 기준이 명확히 표시된다.
- BIM 물량과 실적 단가가 근거 기반으로 연결된다.
- 매핑 불가 항목이 계산에서 제외되고 별도 표시된다.
- 원가 결과에서 실제 결제건까지 추적 가능하다.
- 업체별, 자재별, 프로젝트별 실제 단가 비교가 가능하다.

이 기준을 만족한 뒤에만 예측, 자동 추천, 대체 자재 제안 같은 기능을 검토한다.
