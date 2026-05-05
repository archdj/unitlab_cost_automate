# 작업 절차

## 1. 데이터 접수

원본 데이터는 가능한 한 변경하지 않고 `data_inbox/`에 둔다.

권장 파일명:

```text
payments.csv
bim_quantities.csv
materials.csv
vendors.csv
contracts.csv
invoices.csv
```

Excel 파일이면 `.xlsx`도 가능하지만, 1차 검증은 CSV가 가장 단순하다.

## 2. 데이터 구조 확인

각 파일에서 확인할 것:

- 컬럼명
- 행 수
- 빈 값 비율
- 중복 키
- 금액/수량/단위 컬럼 존재 여부
- 날짜 컬럼 파싱 가능 여부
- 프로젝트/업체/자재를 식별할 키 존재 여부

## 3. 필수 컬럼 검증

각 데이터는 `data_contracts/*.md`의 필수 컬럼과 비교한다.

필수 컬럼이 없으면 해당 데이터는 계산에 바로 사용할 수 없다.

## 4. 표준화

표준화 대상:

- 업체명
- 자재명
- 자재 규격
- 단위
- 프로젝트명/현장명
- 결제 금액 기준

표준화 결과는 원본을 덮어쓰지 않고 별도 컬럼으로 둔다.

예시:

```text
item_name_raw      = 레미콘 25-24-150 현장도착
material_id        = mat-0001
mapping_status     = confirmed
mapping_confidence = 1.0
```

## 5. 매핑 검토

매핑 상태:

- `confirmed`: 사람이 확인한 확정 매핑
- `rule_matched`: 규칙으로 확정 가능한 매핑
- `candidate`: 후보 매핑
- `unmatched`: 매핑 실패

`candidate`와 `unmatched`는 계산에서 제외한다.

## 6. 실적 단가 계산

계산 대상 조건:

- 결제 금액 존재
- 수량 존재
- 단위 존재
- 자재 또는 공종 매핑 확정
- 업체 식별 가능
- 프로젝트 식별 가능

기본 계산:

```text
unit_price = amount_basis / standardized_quantity
```

`amount_basis`는 반드시 명시한다.

예:

- `supply_amount`
- `total_amount`
- `actual_paid_amount`
- `contract_amount`

## 7. BIM 물량 적용

BIM 객체와 자재/공종 매핑이 확정된 항목만 적용한다.

```text
applied_cost = bim_quantity_standardized * unit_price
```

근거 결제건 수와 계산 기준을 함께 표시한다.

## 8. 리포트

필수 리포트:

- 데이터 품질 리포트
- 필수 컬럼 누락 리포트
- 매핑 상태 리포트
- 계산 제외 항목 리포트
- 실적 단가 리포트
- BIM 적용 원가 리포트

