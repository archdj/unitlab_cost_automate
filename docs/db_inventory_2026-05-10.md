# DB 구성 인벤토리 (2026-05-10)

_생성: 2026-05-10 05:15 · `harness/scripts/db_inventory.py` 자동 생성_

이 repo는 SQLite 두 개에 의존한다:

| 라벨 | 경로 | 역할 |
|---|---|---|
| **운영 DB** | `unitlab-cost-analysis/db/cost_analysis.db` (sister directory) | 진실 source. PR-1 schema 변경 적용 완료 (cost_type/package/projects 메타). |
| **sidecar enriched** | `autocost-spec-2026-05-07/harness/data/autocost_enriched.db` | 노션 zip 1차 재파싱. 운영 ETL 결손 회수 (931→1420 cost rows). 운영 DB 통합 후 폐기 예정. |

운영 DB binary는 git에서 제외(`.gitignore`의 `*.db`). schema/migration은 `unitlab-cost-analysis/db/migrations/`에서 관리.

---

## 운영 DB (cost_analysis.db)

- 경로: `C:\Users\PC\unitlab-cost-analysis\db\cost_analysis.db`
- 크기: 2.85 MB
- 테이블 수: 26

### 테이블 요약

| 테이블 | 행 수 | 컬럼 수 | 비고 |
|---|---:|---:|---|
| `actual_costs` | 931 | 23 |  |
| `audit_log` | 0 | 9 | (빈 테이블) |
| `bim_quantities` | 2,455 | 11 |  |
| `bim_unit_conversions` | 11 | 9 |  |
| `cost_predictions` | 181 | 14 |  |
| `curation_logs` | 0 | 7 | (빈 테이블) |
| `db_meta` | 5 | 2 |  |
| `ifc_files` | 9 | 12 |  |
| `ifc_jobs` | 3 | 12 |  |
| `ifc_project_link_reviews` | 9 | 13 |  |
| `kg_overrides` | 0 | 9 | (빈 테이블) |
| `kg_validation_issues` | 0 | 8 | (빈 테이블) |
| `loss_factors` | 6 | 12 |  |
| `material_aliases` | 250 | 7 |  |
| `materials` | 3,356 | 5 |  |
| `ml_model_info` | 8 | 10 |  |
| `module_types` | 17 | 10 |  |
| `notion_export_costs` | 1,209 | 18 |  |
| `partial_ifc_workcode_reviews` | 19 | 21 |  |
| `project_modules` | 9 | 6 |  |
| `projects` | 27 | 21 |  |
| `quote_module_catalog` | 49 | 11 |  |
| `quote_option_catalog` | 52 | 11 |  |
| `saved_estimates` | 0 | 9 | (빈 테이블) |
| `unit_prices` | 18 | 13 |  |
| `work_codes` | 147 | 9 |  |

### 컬럼 상세 (NULL률 ≥ 50%만)

#### `actual_costs` (931 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `material_id` | INTEGER | 100.0% |
| `actual_quantity` | REAL | 100.0% |
| `unit` | TEXT | 100.0% |
| `unit_price` | REAL | 100.0% |
| `invoice_no` | TEXT | 100.0% |
| `validated_by` | TEXT | 100.0% |
| `validated_at` | TEXT | 100.0% |
| `reject_reason` | TEXT | 100.0% |
| `package` | TEXT | 100.0% |

#### `cost_predictions` (181 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `module_type_id` | INTEGER | 56.4% |

#### `ifc_files` (9 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `file_hash` | TEXT | 100.0% |
| `revit_version` | TEXT | 100.0% |
| `file_size_mb` | REAL | 100.0% |
| `uploaded_by` | TEXT | 100.0% |

#### `ifc_jobs` (3 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `error_message` | TEXT | 100.0% |
| `created_by` | TEXT | 100.0% |

#### `ifc_project_link_reviews` (9 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `db_file_name` | TEXT | 100.0% |
| `candidate_file_name` | TEXT | 100.0% |
| `current_project_code` | TEXT | 100.0% |
| `approved_project_code` | TEXT | 100.0% |
| `current_module_code` | TEXT | 100.0% |
| `approved_module_code` | TEXT | 100.0% |
| `reviewed_at` | TEXT | 100.0% |

#### `loss_factors` (6 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `module_type_id` | INTEGER | 100.0% |
| `confidence_lower` | REAL | 100.0% |
| `confidence_upper` | REAL | 100.0% |
| `valid_to` | TEXT | 100.0% |

#### `material_aliases` (250 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `approved_by` | TEXT | 100.0% |
| `approved_at` | TEXT | 100.0% |

#### `materials` (3,356 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `spec` | TEXT | 89.8% |

#### `ml_model_info` (8 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `mae_loo` | REAL | 87.5% |
| `mae_train` | REAL | 87.5% |
| `intercept` | REAL | 87.5% |

#### `module_types` (17 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `description` | TEXT | 100.0% |

#### `notion_export_costs` (1,209 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `skip_reason` | TEXT | 73.9% |

#### `partial_ifc_workcode_reviews` (19 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `estimated_target_unit` | TEXT | 89.5% |
| `estimated_quantity` | REAL | 89.5% |
| `estimated_amount_per_unit` | REAL | 89.5% |
| `estimation_source` | TEXT | 89.5% |

#### `project_modules` (9 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `floor_position` | TEXT | 100.0% |
| `notes` | TEXT | 100.0% |

#### `projects` (27 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `site_address` | TEXT | 100.0% |
| `region` | TEXT | 100.0% |
| `start_date` | TEXT | 100.0% |
| `end_date` | TEXT | 100.0% |
| `total_floor_area` | REAL | 100.0% |
| `total_modules` | INTEGER | 100.0% |
| `contract_amount` | INTEGER | 100.0% |
| `final_cost` | INTEGER | 100.0% |
| `product_type` | TEXT | 55.6% |
| `progress_stage` | TEXT | 51.8% |
| `customer_type` | TEXT | 51.8% |
| `permit_type` | TEXT | 51.8% |
| `contract_stage` | TEXT | 51.8% |
| `module_size_text` | TEXT | 51.8% |

#### `unit_prices` (18 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `material_id` | INTEGER | 100.0% |
| `region` | TEXT | 100.0% |
| `effective_to` | TEXT | 100.0% |
| `estimation_source` | TEXT | 94.4% |

#### `work_codes` (147 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `work_name_en` | TEXT | 50.3% |

---

## sidecar enriched (autocost_enriched.db)

- 경로: `C:\Users\PC\unitlab_autocost\autocost-spec-2026-05-07\harness\data\autocost_enriched.db`
- 크기: 1.28 MB
- 테이블 수: 7

### 테이블 요약

| 테이블 | 행 수 | 컬럼 수 | 비고 |
|---|---:|---:|---|
| `actual_cost_corrections` | 483 | 11 |  |
| `actual_costs_enriched` | 1,420 | 19 |  |
| `etl_runs` | 0 | 12 | (빈 테이블) |
| `material_quote_lines` | 588 | 14 |  |
| `model_versions` | 0 | 9 | (빈 테이블) |
| `projects_master` | 23 | 13 |  |
| `vendors_master` | 429 | 9 |  |

### 컬럼 상세 (NULL률 ≥ 50%만)

#### `actual_costs_enriched` (1,420 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `parent_notion_id` | TEXT | 100.0% |
| `remark` | TEXT | 99.9% |
| `vendor_notion_id` | TEXT | 99.7% |
| `package` | TEXT | 98.0% |

#### `material_quote_lines` (588 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `unit` | TEXT | 86.9% |
| `spec` | TEXT | 70.1% |

#### `projects_master` (23 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `address` | TEXT | 87.0% |

#### `vendors_master` (429 행)

| 컬럼 | 타입 | NULL률 |
|---|---|---:|
| `bank_name` | TEXT | 100.0% |
| `account_holder` | TEXT | 100.0% |

---

## CSV (테이블 × 컬럼 평면)

같은 데이터를 `db_inventory_2026-05-10.csv`에 저장. 컬럼:

`db, table, rows, col_idx, col_name, col_type, notnull, pk, null_rate`
