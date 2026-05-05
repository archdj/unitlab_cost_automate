# 원가 근거 엔진 설계

작성일: 2026-05-05

대상: 모듈러 하우스 평형/조합 선택 시 총원가와 산출 근거를 함께 제공하는 엔진

## 1. 목표

사용자가 원하는 최종 출력은 단순 예측값이 아니다.

```text
입력:
- 평형
- 모듈 조합
- 옵션
- 지역/현장 조건

출력:
- 총원가
- 공종별 금액
- 자재/노무/경비 분해
- 산출 근거
- 사용된 실제 사례
- 미확정/누락 항목
```

핵심 원칙:

```text
근거 없는 항목을 평균으로 자동 삽입하지 않는다.
근거가 약한 항목은 금액과 함께 근거 수준을 표시한다.
미확정 항목은 총액에 섞지 않고 별도 표시한다.
```

## 2. 엔진 구조

```text
Cost Evidence Engine

1. Input Normalizer
   평형/모듈/옵션/현장 조건을 표준 입력으로 변환

2. Case Selector
   실제 원가 사례 중 같은 모듈, 같은 평형, 유사 면적 사례 선택

3. Quantity Resolver
   BIM 수량, 발주 CSV 수량, 과거 수량을 선택

4. Cost Resolver
   실제 결제 원가, 단가, 공종별 노무비, 경비를 선택

5. Evidence Builder
   각 금액에 산출식, 원천, 사례, 신뢰도를 부여

6. Missing Detector
   필수 공종/자재인데 근거가 없는 항목을 누락 후보로 표시

7. Total Composer
   confirmed + estimated 금액만 합산하고 missing은 별도 표시
```

## 3. 입력 포맷

```json
{
  "modules": [
    {
      "module_code": "T-15-STD",
      "quantity": 1
    },
    {
      "module_code": "U-6-1-2025",
      "quantity": 1
    }
  ],
  "options": [
    {
      "option_name": "욕실 추가",
      "quantity": 1
    }
  ],
  "site": {
    "region": "경기",
    "distance_km": null,
    "crane_required": null,
    "foundation_type": null
  },
  "pricing_date": "2026-05-05"
}
```

## 4. 출력 포맷

```json
{
  "total": {
    "confirmed_amount": 0,
    "estimated_amount": 128500000,
    "missing_amount": null,
    "display_total": 128500000,
    "currency": "KRW"
  },
  "coverage": {
    "actual_case_count": 5,
    "bim_quantity_coverage": 0.62,
    "material_price_coverage": 0.41,
    "labor_basis_coverage": 0.74
  },
  "components": [
    {
      "component_type": "work_code",
      "work_code": "STR-ST",
      "work_name": "철골공사",
      "cost_type": "재료비",
      "amount": 18400000,
      "quantity": null,
      "unit": null,
      "unit_price": null,
      "basis": "similar_case_median_per_m2",
      "formula": "median(actual_amount / floor_area_m2) * requested_area_m2",
      "source_cases": ["N-01-T-15", "N-13-T-15-3"],
      "source_tables": ["actual_costs", "project_modules", "module_types"],
      "evidence_level": "case_based",
      "confidence": 0.6,
      "status": "estimated"
    }
  ],
  "missing": [
    {
      "work_code": "SITE-EARTH",
      "reason": "site condition required but no foundation/site input",
      "action": "require_site_input"
    }
  ],
  "warnings": [
    "PROCURE CSV has material quantities but no amount column.",
    "actual_costs has no material_id or actual_quantity links."
  ]
}
```

## 5. 금액 상태

| 상태 | 의미 | 총액 포함 |
|---|---|---|
| `confirmed` | 실제 견적/계약/결제 금액 | 포함 |
| `estimated` | 실제 사례 또는 BIM/수량 기반 산출 | 포함 |
| `range_only` | 구간만 산출 가능 | 별도 표시 |
| `missing` | 근거 부족 | 미포함 |
| `excluded` | 선택하지 않은 옵션/공종 | 미포함 |

## 6. 근거 수준

| 근거 수준 | 설명 |
|---|---|
| `actual_same_module` | 동일 모듈 실제 원가 |
| `actual_same_pyeong` | 동일 평형 실제 원가 |
| `actual_similar_area` | 유사 면적 실제 원가 |
| `bim_quantity_price` | BIM 수량 x 실제 단가 |
| `procure_quantity_price` | 발주 수량 x 실제 단가 |
| `allocated_labor` | 공종 노무비를 자재 driver에 배분 |
| `catalog_estimate` | 기존 견적 카탈로그 기반 |
| `missing` | 근거 없음 |

## 7. 현재 데이터로 가능한 산출

현재 바로 가능한 것:

- 모듈/평형별 유사 실제 사례 선택
- 공종별 실제 원가 median 산출
- 재료비/노무비/경비 분리
- 모듈 조합 면적에 따른 사례 기반 금액 산출
- 근거 사례 프로젝트 표시
- 누락/미확정 항목 표시

현재 바로 불가능한 것:

- 개별 자재별 실제 단가 산출
- 개별 자재별 노무비 직접 산출
- 발주 CSV 금액 기반 단가 산출

이유:

- `actual_costs.material_id`가 0건
- `actual_costs.actual_quantity`가 0건
- `actual_costs.unit_price`가 0건
- 발주 CSV에 금액 컬럼 없음

## 8. 1차 구현 전략

1차는 "실제 사례 기반 공종/비용성격별 엔진"으로 만든다.

```text
입력 모듈 조합
-> 총 면적 산출
-> 같은 모듈/평형/유사 면적 실제 사례 선택
-> 공종 x 비용성격별 원/m2 median 계산
-> 요청 면적에 곱해 component amount 생성
-> source_cases와 formula 저장
-> 총액 합산
```

2차에서 자재 수량을 붙인다.

```text
발주 CSV/BIM 수량
-> 자재 수량 마트
-> Notion 결제 raw_description과 매칭
-> 자재 단가 후보 생성
-> 승인된 항목만 자재 단가로 승격
```

3차에서 자재별 노무비를 붙인다.

```text
공종 노무비
-> driver quantity 계산
-> 자재군별 배분
-> 검토 승인
-> 자재별 노무 단가 생성
```

## 9. API 설계

### POST `/api/evidence/estimate`

입력:

```json
{
  "modules": [
    { "module_code": "T-15-STD", "quantity": 1 }
  ],
  "options": [],
  "site": {}
}
```

출력:

```json
{
  "request": {},
  "total": {},
  "coverage": {},
  "components": [],
  "missing": [],
  "source_cases": [],
  "warnings": []
}
```

### GET `/api/evidence/modules`

모듈 선택용 기준 데이터.

### GET `/api/evidence/cases?module_code=T-15-STD`

근거 사례 조회.

### GET `/api/evidence/component/{estimate_id}`

항목별 산출 근거 상세 조회.

## 10. UI 설계

첫 화면은 총액 카드 하나가 아니라 다음 구성이어야 한다.

```text
상단:
- 입력 모듈 조합
- 예상 총원가
- 실제 사례 수
- 근거 커버리지
- 미확정 항목 수

중단:
- 공종별 금액
- 재료비/노무비/경비 분해
- 자재 기반/사례 기반/미확정 분류

하단:
- 산출 근거 테이블
- 사용 사례 프로젝트
- 누락 검토 항목
```

각 금액 행에는 반드시 다음이 보여야 한다.

- 금액
- 산식
- 근거 사례
- 근거 수준
- confidence
- 실제 데이터인지 파생값인지

