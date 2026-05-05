# 데이터 계약서: payments

실제 결제가 이루어진 원가 데이터다.

## 필수 컬럼

| 표준 컬럼 | 설명 |
|---|---|
| payment_id | 결제 고유 ID |
| project_id | 프로젝트/현장 ID |
| vendor_id | 업체 ID |
| payment_date | 결제일 |
| item_name_raw | 원본 품목명 |
| quantity | 수량 |
| unit | 단위 |
| amount_basis | 단가 계산 기준 금액 |

## 권장 컬럼

| 표준 컬럼 | 설명 |
|---|---|
| supply_amount | 공급가액 |
| vat | 부가세 |
| total_amount | 총 지급액 |
| contract_id | 계약 ID |
| invoice_id | 증빙 ID |
| source_file | 원본 파일명 |
| source_row | 원본 행 번호 |

## 검증 규칙

- `payment_id`는 중복되면 안 된다.
- `amount_basis`는 0보다 커야 한다.
- `quantity`는 0보다 커야 한다.
- `unit`이 없으면 단가 계산에서 제외한다.
- `vendor_id`가 없으면 업체별 분석에서 제외한다.

