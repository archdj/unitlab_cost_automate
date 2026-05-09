# MASTER_DATA_SPEC — 원가 항목/공종 마스터 (F9)

자재/공종/단위/코드 등 기준 정보를 관리하고, 노션·엑셀의 원본 표기를 마스터에 매핑한다. F1 정제와 F2 예측의 정확도를 좌우하는 기반 데이터.

## 1. 마스터 테이블

### 1.1 work_codes

`unitlab-cost-analysis/db/migrations/002_seed_work_codes.sql`, `003_unitlab_work_codes.sql` 의 기존 트리를 재사용. 본 프로그램에서는 추가/비활성화만 한다.

| 컬럼 | 설명 |
|---|---|
| work_code | PK (예: `A1.01`) |
| name | 표기명 |
| parent_code | 트리 부모 |
| status | active / inactive |
| updated_at | |

### 1.2 materials

| 컬럼 | 설명 |
|---|---|
| material_id | PK |
| name | 표준 자재명 |
| spec | 규격 |
| unit | 표준 단위 |
| category | 자재 분류 |
| status | active / inactive |

### 1.3 units

| 컬럼 | 설명 |
|---|---|
| unit | PK (예: `m2`) |
| display | UI 표기 (예: `㎡`) |
| dimension | length / area / volume / weight / count |

## 2. F9.1 매핑 (동의어)

### 2.1 work_synonyms

`harness/mapping/work_synonym_template.csv` 와 동일 스키마:

| 컬럼 | 설명 |
|---|---|
| source_value | 원본 표기 (노션/엑셀) |
| target_work_code | 매핑 대상 마스터 PK |
| mapping_status | candidate / rule_matched / confirmed |
| confidence | 0.0 ~ 1.0 |
| reviewer | 사용자 ID |
| note | |

### 2.2 material_synonyms

| 컬럼 | 설명 |
|---|---|
| source_type | payment / bim / notion / excel |
| source_value | 원본 자재명 |
| target_material_id | 매핑 대상 |
| mapping_status, confidence, reviewer, note | (위와 동일) |

### 2.3 unit_synonyms

`harness/mapping/unit_conversion_template.csv` 와 동일 스키마.

## 3. F9 수용기준 → 구현 매핑

| 수용기준 | 구현 |
|---|---|
| 마스터 데이터 추가/수정/비활성화 | `src/web/admin/master_*` 페이지 + DB CRUD |
| 동의어 매핑 | F1.2.1 동의어 매핑 UI에서 함께 처리 |
| 매핑 누락 항목 목록 | `harness/scripts/report_unmapped.py` → `harness/reports/unmapped_items.json` |

## 4. 작업 항목

- [ ] `harness/sql/materials_schema.sql`, `units_schema.sql`
- [ ] `harness/sql/work_synonyms_schema.sql`, `material_synonyms_schema.sql`, `unit_synonyms_schema.sql`
- [ ] `harness/scripts/report_unmapped.py` — 매핑 누락 리스트
- [ ] `harness/scripts/seed_units.py` — `unit_synonyms` 초기 시드 (m³→m3, ㎡→m2 등)
- [ ] `src/web/admin/` — 마스터 CRUD + 매핑 UI

## 5. 가정·결정 사항

- 매핑 status가 `confirmed` 가 아닌 항목은 F2 예측에 자동 반영하지 않는다 (cost-analysis-program-plan harness 원칙 준수).
- 마스터 변경은 F10 감사 로그 기록 대상.
