# 자재별/노무비 기반 예측 전환 계획

작성일: 2026-05-05

대상 레포: `C:\Users\PC\unitlab-cost-analysis`

## 1. 판단

자재별로 예측을 쪼개는 방향이 맞다.

현재 총액 예측은 면적/모듈/과거 평균을 기준으로 빠진 공종까지 같이 추정할 가능성이 있다. 이 문제를 줄이려면 예측 단위를 다음처럼 바꿔야 한다.

```text
프로젝트 예측 총액
= 자재별 직접비
+ 자재에 종속된 노무비
+ 공종 단위 노무/시공비
+ 운반/양중/장비비
+ 현장비
+ 예외비
```

즉, 없는 자재는 0 또는 미확정으로 두고, 없는 공종을 평균값으로 자동 보정하지 않는 구조가 필요하다.

## 2. 현재 데이터로 확인한 사실

분석 리포트:

`C:\Users\PC\cost-analysis-program-plan\harness\reports\material_labor_feasibility.json`

현재 `actual_costs` 상태:

| 항목 | 값 |
|---|---:|
| 전체 actual cost | 931건 |
| `material_id` 연결 | 0건 |
| `actual_quantity` 입력 | 0건 |
| `unit_price` 입력 | 0건 |

즉, 현재 Notion 실원가 DB만으로는 "자재별 실제 단가"를 바로 계산할 수 없다.

하지만 `source_ref`에는 비용 성격이 들어 있다.

| 비용 성격 | 건수 | 금액 |
|---|---:|---:|
| 재료비 | 483 | 655,116,594원 |
| 노무비 | 142 | 497,342,975원 |
| 재료비+노무비 | 137 | 399,715,128원 |
| 경비 | 156 | 72,513,180원 |
| 기타 | 12 | 16,635,400원 |
| 제작+현장설치 비 | 1 | 1,405,000원 |

따라서 노무비 신호는 있다. 다만 "자재별 노무비"로 바로 연결되어 있지는 않다.

## 3. 발주 CSV의 역할

발주 CSV에는 자재 예측에 필요한 수량 정보가 있다.

CSV 파일:

`C:\Users\PC\unitlab-cost-analysis\유닛랩 시공 발주관리 - 발주리스트 (1).csv`

확인된 컬럼:

- 코드
- 자재명
- 자재 규격
- 상세규격
- 단위
- 수량
- 업체명
- 공정
- 사용위치
- 진행
- 발주일
- 납품일
- 프로젝트명
- 비고

CSV 상태:

| 항목 | 값 |
|---|---:|
| 전체 행 | 941 |
| 완료 행 | 562 |
| 자재명+수량이 있는 행 | 562 |
| 자재명 공란 | 379 |
| 프로젝트명 공란 | 393 |
| 금액 컬럼 | 없음 |

결론:

- CSV는 자재 수량/규격/업체/프로젝트 매핑 원천으로 쓸 수 있다.
- CSV만으로 실제 자재 금액은 계산할 수 없다.
- 금액은 Notion 결제 원가와 매칭하거나, 별도 결제/발주 금액 데이터가 필요하다.

## 4. 노무비도 자재별로 산출 가능한가

부분적으로 가능하다.

현재 데이터에서 가능한 수준:

1. 공종별 노무비
   - 가능
   - `actual_costs.source_ref = 노무비`
   - 예: 철골공사 노무비, 판넬공사 노무비, 창호공사 노무비

2. 자재군별 노무비
   - 조건부 가능
   - `raw_description`, `work_code`, 발주 CSV의 `자재명/공정/사용위치`를 매칭해야 함
   - 예: 판넬 설치 노무비를 판넬 m2 또는 장수에 배분

3. 개별 자재 1개당 노무비
   - 현재 상태로는 바로 불가능
   - 이유: 실제 원가 라인에 자재 ID/수량이 없음
   - 발주 CSV에도 금액이 없음

따라서 현재 현실적인 목표는 다음 순서다.

```text
1단계: 공종별 노무비
2단계: 자재군별 노무비
3단계: 승인된 매핑이 쌓이면 개별 자재별 노무비
```

## 5. 예측 구조

### 5.1 자재 직접비

자재 직접비는 다음 방식으로 계산한다.

```text
자재 직접비 = 예상 수량 x 자재 단가
```

수량 출처 우선순위:

1. BIM 수량
2. 발주 CSV 수량
3. 과거 동일 모듈 자재 수량 median
4. 없으면 예측하지 않음

단가 출처 우선순위:

1. 실제 결제 단가
2. 동일 업체 최근 단가
3. 동일 자재 최근 median 단가
4. 동일 자재군 median 단가
5. 없으면 미확정

중요:

단가가 없으면 평균으로 강제 추정하지 말고 `missing_price`로 남겨야 한다.

### 5.2 자재 종속 노무비

자재별 노무비는 다음 단위로 계산한다.

```text
자재 종속 노무비 = 자재 수량 x 자재군별 설치 노무 단가
```

예:

| 자재군 | 노무비 driver |
|---|---|
| 철골 | kg, ton, m, 부재 수 |
| 판넬 | m2, 장수 |
| 창호 | EA, m2 |
| 도어 | EA |
| 타일 | m2, 박스 |
| 도장/코킹 | m, m2 |
| 전기 | 포인트 수, EA |

현재는 자재별 노무비 단가가 없으므로, 먼저 공종별 노무비를 driver에 배분한다.

예:

```text
판넬 노무비 총액 / 판넬 총 m2 = 판넬 설치 노무비 원/m2
철골 노무비 총액 / 철골 총 m 또는 kg = 철골 설치 노무비 원/m 또는 원/kg
창호 노무비 총액 / 창호 EA = 창호 설치 노무비 원/EA
```

### 5.3 공종 단위 노무/시공비

자재로 환원하기 어려운 노무비는 공종 단위로 남긴다.

예:

- 현장 설치공사비
- 접합
- 목공 시공
- 전기 시공
- 청소
- 토공
- 기초
- 장비 작업

이 항목을 억지로 자재별로 배부하면 오히려 예측이 왜곡된다.

### 5.4 운반/양중/경비

운반/양중/경비는 자재비나 면적보다 현장 조건 영향을 받는다.

별도 모델로 둔다.

```text
운반/양중/경비 = 지역 + 거리 + 모듈 수 + 중량 + 크레인 여부 + 현장 조건
```

현재 데이터에는 `source_ref = 경비`가 있으므로 분리 가능하다.

## 6. 필요한 예측 마트

### 6.1 `project_material_quantity_features`

자재 수량 마트.

| 컬럼 | 설명 |
|---|---|
| `project_id` | 프로젝트 |
| `material_key` | 표준 자재 키 |
| `material_name_raw` | 원본 자재명 |
| `spec_raw` | 원본 규격 |
| `work_code_id` | 공종 |
| `quantity` | 수량 |
| `unit` | 단위 |
| `vendor_name` | 업체 |
| `source_system` | BIM/PROCURE/MANUAL |
| `mapping_status` | mapped/unmapped/review |

### 6.2 `project_material_cost_features`

자재 금액 마트.

| 컬럼 | 설명 |
|---|---|
| `project_id` | 프로젝트 |
| `material_key` | 표준 자재 키 |
| `actual_quantity` | 실제 수량 |
| `actual_material_amount` | 실제 자재 금액 |
| `unit_price` | 실제 단가 |
| `vendor_name` | 업체 |
| `settlement_date` | 결제일 |
| `price_basis` | actual/matched/median/missing |

### 6.3 `project_work_labor_features`

공종 노무비 마트.

| 컬럼 | 설명 |
|---|---|
| `project_id` | 프로젝트 |
| `work_code_id` | 공종 |
| `labor_amount` | 실제 노무비 |
| `mixed_amount` | 재료비+노무비 |
| `driver_type` | m2/EA/m/kg/point |
| `driver_quantity` | 배분 기준 수량 |
| `labor_unit_price` | driver 단위당 노무비 |
| `allocation_status` | direct/allocated/unallocated |

### 6.4 `project_material_labor_bridge`

자재와 노무비를 연결하는 브릿지.

| 컬럼 | 설명 |
|---|---|
| `project_id` | 프로젝트 |
| `work_code_id` | 공종 |
| `material_key` | 표준 자재 키 |
| `labor_amount_allocated` | 배분된 노무비 |
| `allocation_method` | direct/vendor/work_ratio/quantity_ratio |
| `confidence` | 매칭 신뢰도 |
| `review_required` | 검토 필요 여부 |

## 7. 빠진 공종을 자동 예측하지 않는 규칙

기존 총액 모델의 가장 큰 문제는 누락 공종까지 평균값으로 채우는 것이다.

새 모델에서는 다음 규칙을 둔다.

```text
자재 수량 없음 + BIM 근거 없음 + 발주 근거 없음
= 예측 0 또는 미확정
```

단, 필수 공종인데 근거가 없으면 자동 금액을 넣지 말고 누락 리포트로 보낸다.

예:

| 상태 | 처리 |
|---|---|
| BIM/발주 수량 있음 | 예측 가능 |
| 과거 동일 모듈 필수 자재인데 현재 없음 | 누락 의심 |
| 선택 옵션성 자재 없음 | 0 |
| 공종 자체가 현장 조건 의존 | 별도 모델 |
| 단가 없음 | 금액 미확정 |

## 8. 구현 시작점

이번에 추가한 하네스:

`cost-analysis-program-plan/harness/scripts/profile_material_labor_feasibility.py`

실행:

```powershell
python cost-analysis-program-plan\harness\scripts\profile_material_labor_feasibility.py
```

출력:

`cost-analysis-program-plan/harness/reports/material_labor_feasibility.json`

이 스크립트는 다음을 확인한다.

- actual cost가 자재/수량/단가와 연결되어 있는지
- 비용 성격별 금액이 얼마인지
- 노무비가 공종별로 얼마나 있는지
- 발주 CSV에 자재 수량 데이터가 얼마나 있는지
- CSV에 금액 컬럼이 있는지

## 9. 다음 구현 작업

1. 발주 CSV dry-run import 리포트 작성
   - 프로젝트 매핑률
   - 공정 매핑률
   - 자재명 표준화율
   - 수량/단위 변환 가능률

2. `actual_costs.raw_description` 기반 자재명 후보 매칭
   - Notion 결제 라인과 발주 CSV 자재명을 연결
   - 자동 확정 금지
   - confidence와 review flag 부여

3. 공종별 노무비 driver 산출
   - 판넬: 판넬 수량
   - 철골: 철골 길이/중량
   - 창호: 창호 EA
   - 도어: 도어 EA
   - 타일: 타일 수량

4. 자재별 예측 마트 생성
   - 실제 금액이 있는 것만 actual로 표시
   - 금액이 없는 것은 quantity-only로 표시

5. 예측 API 변경
   - 총액 하나를 바로 반환하지 않음
   - `confirmed`, `estimated`, `missing`, `excluded`를 분리 반환

## 10. 결론

자재별 예측으로 바꾸는 것은 맞다.

하지만 현재 데이터에서 "자재별 노무비"는 바로 존재하지 않는다. 존재하는 것은 다음이다.

- 공종별 노무비
- 공종별 재료비
- 재료비+노무비 혼합 라인
- 발주 CSV의 자재별 수량
- BIM의 공종별 수량

따라서 현실적인 구현은 다음 순서가 맞다.

```text
공종별 노무비 분리
-> 자재 수량 마트 생성
-> 공종 노무비를 자재군 driver로 배분
-> 검토 승인된 항목만 자재별 노무비 단가로 승격
-> 총액은 자재별/공종별/현장비 합산으로 계산
```

이 방식이면 빠진 공종을 자동으로 예측하지 않고, 실제로 근거가 있는 자재와 공종만 금액화할 수 있다.
