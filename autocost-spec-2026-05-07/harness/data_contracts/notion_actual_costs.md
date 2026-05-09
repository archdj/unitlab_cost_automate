# 데이터 계약서: notion_actual_costs

노션 → 운영 DB `actual_costs` 정규화 형태.
명세서 F4.1 의 가져오기 흐름이 출력해야 하는 표준 컬럼.

> 운영 DB `actual_costs` 는 read-only. 본 계약은 ETL(`unitlab-cost-analysis/agents/notion_etl.py`) 이 운영 DB 에 INSERT 할 때 따라야 하는 정규화 명세이며, 동시에 본 프로그램이 운영 DB 에서 읽을 때의 컬럼 기대치다.
> 운영 DB 실제 상태와 매핑은 [`docs/OPERATIONAL_DB_MAPPING.md`](../../docs/OPERATIONAL_DB_MAPPING.md) §3 참조.

## 1. 운영 DB `actual_costs` 컬럼 (정규)

| 컬럼 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `project_id` | INT FK→projects | ✅ | |
| `work_code_id` | INT FK→work_codes | ✅ | |
| `material_id` | INT FK→materials | ⚪ | 매칭 실패 허용 (raw_description 보존) |
| `actual_quantity` | REAL | ⚠️ | **현재 결측 다수** — F1 정제 대상 |
| `unit` | TEXT | ⚠️ | **현재 결측 다수** — `bim_unit_conversions` 로 정규화 |
| `unit_price` | REAL | ⚪ | `total_amount / actual_quantity` 로 역산 가능 |
| `total_amount` | INT | ✅ | 실집행액(원) |
| `settlement_date` | TEXT | ✅ | 결제일 |
| `vendor_name` | TEXT | ⚪ | **현재 노션 URL 혼입** — F1 정제 대상 |
| `invoice_no` | TEXT | ⚪ | |
| `payment_status` | TEXT | — | `PAID`/`PENDING` |
| `source_system` | TEXT | — | 본 ETL 은 `'NOTION'` 고정 |
| `source_ref` | TEXT | ✅ | **노션 page_id 또는 block_id** (현재 한글 텍스트 혼입 — 정규화 필요) |
| `raw_description` | TEXT | ✅ | 원본 품목 설명 (별칭 매칭 실패 추적) |
| `promotion_status` | TEXT | — | `candidate`/`validated`/`promoted`/`approved`/`rejected` (실제 값 `approved` 사용 중 — enum 통일 요청 별도) |

## 2. 노션 속성 → 운영 DB 컬럼 매핑

ETL 이 노션 DB 의 속성을 다음으로 매핑한다 (속성명은 워크스페이스에 따라 조정 — F4.1.2 매핑 UI 에서 사용자가 확정).

| 노션 속성 (예) | 운영 DB 컬럼 | 비고 |
|---|---|---|
| `프로젝트` (relation) | `project_id` | `projects.notion_page_id` 로 역참조 |
| `결제일` / `정산일` (date) | `settlement_date` | |
| `공종` (select) | `work_code_id` | `work_aliases` (신규) 로 매핑 후 변환 |
| `자재명` / `품목` (title/text) | `raw_description` + `material_id` | `material_aliases` 로 매핑 시도 |
| `수량` (number) | `actual_quantity` | |
| `단위` (select) | `unit` | `bim_unit_conversions` 로 정규화 |
| `금액` (number/formula) | `total_amount` | |
| `업체` (relation/text) | `vendor_name` | URL 분리 정제 필요 |
| `세금계산서 번호` (text) | `invoice_no` | |
| `로스율` (number, 0~1) | (별도 → `loss_factors` 입력) | actual_costs 컬럼 아님 |
| (노션 페이지 ID — 자동) | `source_ref` | 페이지 ID 그대로 |

## 3. 검증 규칙 (F4.2.3 / F1.3 적용)

| 규칙 | 분류 | 처리 |
|---|---|---|
| `project_id` 매칭 실패 | block | 행 reject |
| `total_amount <= 0` | block | 행 reject |
| `settlement_date` 없음 / 형식 오류 | block | 행 reject |
| `actual_quantity` 결측 | warn | 학습은 가능하지만 단가/항목 분해 정확도 저하 — 보강 후보로 표시 |
| `unit` 결측 또는 `bim_unit_conversions` 미매핑 | warn | `unmapped_unit` 카운트 |
| `material_id` 매칭 실패 (`material_aliases` 없음) | warn | `unmapped_material_alias` — 매핑 후보로 표시 |
| `vendor_name` 에 URL 포함 | warn | 자동 정제 후 별도 vendor 마스터 후보 |

## 4. 학습 입력 필터 (F2)

본 프로그램이 `actual_costs` 에서 학습 데이터로 받을 행:

```sql
SELECT *
FROM actual_costs
WHERE promotion_status IN ('approved','promoted','validated')
  AND total_amount > 0
  AND settlement_date IS NOT NULL
  -- actual_quantity / unit 결측은 허용 (총액 학습용)
```

> 항목별 분해 (F2.1.2) / 단가 분석 (F7.1.1) 은 `actual_quantity IS NOT NULL AND unit IS NOT NULL` 행만 사용.

## 5. 출처 추적 보장

모든 정제 결과는 다음 키로 운영 DB 원본 행에 역참조 가능해야 한다.

- `actual_costs.actual_cost_id` (PK)
- `actual_costs.receipt_id` (재현용 UUID)
- `actual_costs.source_ref` (노션 page_id)
