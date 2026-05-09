# 데이터 계약서: excel_construction

엑셀 시공/자재 데이터 → 운영 DB `actual_costs` 정규화 형태.
명세서 F4.2 가 출력해야 하는 표준 컬럼.

> 출력 정규형은 `notion_actual_costs.md` 와 동일 (`actual_costs` 한 테이블에 합치기 위함).
> 차이는 입력 엑셀의 컬럼 자동 인식 단계에서만 발생.

## 1. 출력 정규 컬럼

[`notion_actual_costs.md`](notion_actual_costs.md) §1 과 동일. ETL 분기만 다르다 (`source_system = 'EXCEL'`).

## 2. 엑셀 헤더 → 정규 컬럼 자동 인식

F4.2.2 자동 인식 키워드. 매칭 실패는 F4.2.2 수동 매핑 UI 로 보낸다.

| 정규 컬럼 | 한글 키워드 | 영문 키워드 |
|---|---|---|
| `raw_description` | 자재, 품목, 품명, 자재명 | item, name, material |
| `actual_quantity` | 수량, 물량 | qty, quantity |
| `unit` | 단위 | unit |
| `unit_price` | 단가 | price, unit_price |
| `total_amount` | 금액, 공급가, 합계 | amount, supply, total |
| `work_code_raw` | 공종, 분류 | work, category |
| `vendor_name` | 업체, 거래처 | vendor, supplier |
| `settlement_date` | 결제일, 정산일, 일자 | date, payment_date |
| `invoice_no` | 세금계산서, 청구서 | invoice |
| (자유 컬럼) | 규격, 비고 | spec, note |

## 3. 검증 규칙 (F4.2.3)

| 규칙 | 분류 | 처리 |
|---|---|---|
| 필수 컬럼 (`raw_description`, 그리고 `total_amount` 또는 (`unit_price` ∧ `actual_quantity`)) 누락 | block | 업로드 reject |
| 숫자 컬럼이 숫자 아님 | row reject | 사유 표시 |
| `unit_price * actual_quantity ≠ total_amount` (오차 1% 초과) | warn | 사용자 확인 |
| `unit` 미매핑 (`bim_unit_conversions` 없음) | warn | `unmapped_unit` |
| `total_amount < 0` | warn | |
| `project_id` 추론 불가 | row reject + 업로드 시 사용자가 명시 |

## 4. 출처 추적

- `source_system = 'EXCEL'`
- `source_ref = '{원본 파일명}#{시트명}!{행번호}'`
- 원본 파일은 `harness/data_inbox/` (gitignore) 에 보관 + 해시 기록.

## 5. 운영 DB INSERT 정책

엑셀 업로드는 노션과 동일하게 `actual_costs` 한 테이블에 통합 INSERT.
구분이 필요할 때는 `source_system` 컬럼으로 필터.

학습 입력 필터는 `notion_actual_costs.md` §4 와 동일.
