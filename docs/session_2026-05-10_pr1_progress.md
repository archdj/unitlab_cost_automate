# Session 2026-05-09 ~ 2026-05-10 — PR-1 진행 + 진단 결과

다음 세션에서 이어갈 수 있도록 정리. 새 세션 시작 시 이 파일을 먼저 읽으면 컨텍스트 복원.

---

## 0. 사용자 요구 흐름 요약

1. (5/9) "자재 db 개선 방향으로 진행" — 자재 wMAPE < 15% 트리거 도달 목표
2. (5/9~10) 7개 가설 차례로 검증 (모두 미미/실패) — `material_outlier_audit_2026-05-09.md`
3. (5/10) "한 발 뒤로 본" 결과 — 데이터 한계 + trigger 메모리에 **이미 7/7 통과 기록** 발견
4. (5/10) 트리거 재협상 + RL 멀티 프로젝트 spec + 에너지 재분배 docs 작성
5. (5/10) 흡수 PR (PR-1) 진행 시작 — DB schema 변경 적용 완료

---

## 1. 결정적 발견 — trigger 이미 통과

`memory/project_merge_trigger.md` 에 기록된 7-condition trigger:

| # | 조건 | 한도 | 현재 | 통과 |
|---|---|---|---|---|
| 1 | N ≥ 12 | 12 | 15 | ✅ |
| 2 | 총액 ±20% hit-rate | 50% | 60% | ✅ |
| 3 | 총액 median APE | 18% | 17.5% | ✅ |
| 4 | **MAT bootstrap point** | **30%** | **21.8%** | **✅** |
| 5 | 안정성 변화 | 5pp | -3.1pp | ✅ |
| 6 | LAB ≤ 60% | 60% | 50.7% | ✅ |
| 7 | EXP ≤ 60% | 60% | 48.5% | ✅ |

→ **이미 흡수 PR 진입 가능 상태**. 우리는 v11.0 다른 모델로 9시간 deep dive 했으나 trigger 평가는 v2 bootstrap point 기준이고 이미 통과.

측정 차이:
- **v2 bootstrap MAT point (weighted) = 21.8%** ✅ (trigger 평가 기준)
  source: `unitlab-notion-cost/reports/bootstrap_ci.json`
- v11.0 (autocost-spec, N=8) project-sum 자재 = 26.3% (별 task)
- v2 by_cost_type cell-단위 = 32.9% (다른 측정)

---

## 2. PR-1 진행 상태

### 2.1 적용 완료 ✅

**A. 운영 repo in-flight 작업 commit** (`46c2652`)
- `web/backend/kg_builder.py`, `ontology.html`, `export_portable_ontology.py` (KG/ontology 신규)
- `web/backend/main.py` (KG endpoints + accuracy dashboard 파라미터화)
- `web/frontend/src/pages/Accuracy.jsx`, `ModelCompare.jsx` (모델 비교 페이지 개편)
- `v10.html` (v10 독립 견적 UI 리뉴얼, +1,065줄)
- `.gitignore` (SQLite WAL/SHM 추가)

**B. 운영 DB 백업**
- `C:\Users\PC\unitlab-cost-analysis\db\cost_analysis.before_pr1.20260510.db` (2.98MB)

**C. PR-1 SQL 적용** (`harness/sql/migration_pr1.sql`)
- ALTER TABLE actual_costs ADD COLUMN cost_type, package
- ALTER TABLE projects ADD COLUMN progress_stage, customer_type, permit_type, product_type, contract_stage, module_size_text
- UPDATE actual_costs SET cost_type = (정규화 매핑) — 931행
  - MAT 483, EXP 156, LAB 142, MIXED 138, ETC 12 (spec 기대치 일치 ✓)
- CREATE INDEX idx_actual_costs_cost_type, idx_actual_costs_proj_ct

**D. sidecar → 운영 메타 백필** (`harness/scripts/migrate_sidecar_to_op.py --apply`)
- projects 19건 업데이트 (notion_page_id + 6 메타 컬럼)
- progress_stage 백필 13건
- unmatched 3건:
  - `36794ad5-...` 남곡리 쇼룸 T-12
  - `6595c62c-...` 밀양 다랑협동조합 쉐어하우스 S-33
  - `6a27cb52-...` 제목 없음

### 2.2 미적용 — 다음 세션에서 진행

**E. PR-1 commit + push + GitHub PR** (Grilling Q1~Q5 결정)

| 결정 | 답 |
|---|---|
| Q1 PR-1 마무리 | SQL script를 운영 repo에 commit |
| Q2 commit 범위 | SQL migration만 (Python backfill 미포함) |
| Q3 자동 범위 | commit + push + gh pr create 까지 |
| Q4 db 처리 | db/cost_analysis.db 도 PR-1 commit 에 포함 |
| Q5 branch | 새 branch `pr1-schema-cost-type`, base: `원가분석-프로그램` |
| Q6 메모리 | 미결정 (이 md 파일이 대체) |

구체 단계:
1. `git -C "C:\Users\PC\unitlab-cost-analysis" checkout -b pr1-schema-cost-type` (from 원가분석-프로그램)
2. `cp` migration_pr1.sql → 운영 repo `db/migrations/004_pr1_cost_type_meta.sql`
3. `git add db/migrations/004_pr1_cost_type_meta.sql db/cost_analysis.db`
4. `git commit -m "PR-1: schema migration — cost_type/package + projects 메타 6 컬럼"`
5. `git push -u origin pr1-schema-cost-type`
6. `gh pr create --base 원가분석-프로그램 --title "PR-1: schema migration (cost_type + projects 메타)" --body "..."`

PR body에 포함할 내용:
- 적용 결과 (931행 cost_type 정규화, 19건 메타 백필, unmatched 3건)
- spec 참조 (autocost-spec-2026-05-07/harness/sql/migration_pr1.sql + notion_etl_patch.md)
- ETL 패치는 PR-2 일부로 후속 처리 명시
- 백업 파일 위치 (`db/cost_analysis.before_pr1.20260510.db`)

**F. ETL 패치 — PR-2와 함께** (PR-1 미포함, 결정됨)
- `agents/notion_etl.py` 패치 (cost_type 직접 적재 + package + projects 메타 자동 동기화)
- `notion_etl_patch.md` 의 변경 1~6
- PR-2의 모델 코드 흡수와 같은 PR로 묶음 — source_ref 회복과 학습 query 동시 정리

**G. unmatched 3건 처리**
- 수동 검토 + 매핑 결정 후 `harness/scripts/migrate_sidecar_to_op.py:MANUAL_OVERRIDES` 추가 또는 직접 SQL UPDATE
- PR-1.5 또는 PR-2 단계에서.

### 2.3 후속 PR (분할 spec 메모리 §How to apply 참조)

| PR | 내용 | 시점 |
|---|---|---|
| PR-1 | schema/ETL (현 진행) | 다음 세션 마무리 |
| PR-1.5 | vendors 마스터 신설 + actual_costs.vendor_id FK | PR-1 머지 후 |
| PR-2 | 모델 코드 (`unitlab-notion-cost/src/`) → 운영 메인 + ETL 패치 | PR-1.5 후 |
| PR-3 | 프론트 통합 + `/api/refresh-data` | PR-2 후 |
| PR-4 | unitlab_autocost archive | PR-3 후 |

---

## 3. wMAPE 진단 결과 누적 (참고용 — 새로 시도하지 말 것)

7개 가설 모두 미미/실패. 자세한 사항은 `material_outlier_audit_2026-05-09.md` §1~9.

| 가설 | 효과 | 결론 |
|---|---|---|
| outlier 격리 | 한계 -0.1pp | 효과 없음 |
| raw_description 재분류 | -0.5pp | 미미 |
| quantity backfill | 데이터 source 자체 없음 | Notion 원본에 quantity 컬럼 없음 |
| OCR (PNG/JPG 견적서) | 한글 정확도 0.43~0.45 | 자동 적용 부적합 |
| 견적서 quote_sum 보정 | -4.6pp ✅ | 가장 큰 효과, 그러나 단순 대체 |
| actual work_code 재분류 | +0.2pp | 셀 단위 분포 흔들림 |

**핵심**: 데이터 스케일 (8 프로젝트 × 38 work_code × 6 cost_type / 셀당 1.7 sample) 이
근본 한계. 어떤 알고리즘으로도 wMAPE < 15% 도달 불가. RL은 더 sample 필요로 부적합.

**해결**: 데이터 자연 누적 (8 → 20+ 프로젝트). 6개월 후 재평가.

---

## 4. 새로 작성된 docs

| 파일 | 내용 |
|---|---|
| `docs/material_outlier_audit_2026-05-09.md` | §1~9 진단 누적 |
| `docs/rl_resource_recommendation_spec.md` | RL 멀티 프로젝트 추천 spec (별 task) |
| `docs/energy_reallocation_options_2026-05-10.md` | wMAPE 깎기 외 후보 작업 (F. 비교 대시보드, C. 영업 견적, E. 분류대기함 등) |
| `docs/session_2026-05-10_pr1_progress.md` | 본 파일 |
| `harness/mapping/work_code_keywords.py` | 통합 매핑 사전 (100+ keyword → 38 level=2 work_code) |
| `harness/mapping/material_reclassification.csv` | 12개 키워드 매핑 룰 |

새로 작성된 scripts (모두 `harness/scripts/`):
- `audit_material_outliers.py`, `audit_loo_cell_errors.py`, `inspect_top_outlier_rows.py`
- `dump_material_descriptions.py`, `simulate_reclassification.py`
- `parse_quantity_from_description.py`, `inspect_attachment_links.py`
- `survey_attachments.py`, `inspect_excel_sample.py`
- `parse_excel_quotes.py`, `parse_pdf_quotes.py`, `probe_pdf_quotes.py`
- `ocr_sample_test.py`, `fix_export_filenames.py`
- `load_quote_lines_to_sidecar.py`, `dump_unmatched_quotes.py`
- `simulate_quote_corrected_wmape.py`, `correct_actual_work_codes.py`
- `validate_work_code_mapping.py`, `baseline_metrics_consolidated.py`
- `inspect_outlier_schema.py`

---

## 5. RL 멀티 프로젝트 리소스 추천 (별 task spec)

`docs/rl_resource_recommendation_spec.md` 참조. 핵심:
- sandbox doc §리소스 추천 기반
- State/Action/Reward 정의 + gym.Env 인터페이스
- 5~7주 작업 (시뮬레이션 환경 + Imitation + PPO)
- 잠재 절감액 ~2,700만원/년 (P05 창호 + P15 계단 + P24 가구 묶음)
- wMAPE와 무관한 별 task

**다음 세션에서 RL 진행 의사 시**: spec §5 의 Phase 1 (시뮬레이션 환경) 부터.

---

## 6. 다음 세션 시작 시 첫 5분 작업

1. **이 파일 읽기** (`docs/session_2026-05-10_pr1_progress.md`)
2. `memory/project_pr1_status.md` 읽기 (저장 예정)
3. `memory/project_merge_trigger.md` 읽기 (이미 trigger 7/7 통과)
4. 사용자 의향 확인:
   - PR-1 마무리 (commit + push + gh pr create) 진행?
   - 또는 다른 작업 우선?
5. PR-1 완료 시 PR-1.5 / PR-2 진행 분기

**금기 사항** (반복 실수 방지):
- ❌ v11.0 모델로 자재 wMAPE 개선 시도 — 데이터 한계로 효과 없음 입증
- ❌ "트리거 < 15% 미달" 가정으로 시작 — 이미 trigger 7/7 통과 (MAT bootstrap point 21.8%)
- ❌ 메모리 안 보고 deep dive 시작
- ✅ 메모리 끝까지 읽고 시작

---

## 7. 운영 repo 상태

```
branch: 원가분석-프로그램
last commit: 46c2652 (KG/ontology + 정확도 + v10 UI)
modified: db/cost_analysis.db (PR-1 schema 변경 + active session)
backup: db/cost_analysis.before_pr1.20260510.db (2.98MB)
remote: origin = https://github.com/archdj/unitlab.git
target branch for PR: 원가분석-프로그램 (long-lived feature branch)
PR base 후보: main (long-lived feature branch가 main으로 머지될 때)
```
