# ROADMAP — 10개 기능 → 마일스톤

명세서의 10개 기능 모듈을 4개 마일스톤(M0~M3)에 배치한다. 각 줄의 ⭕/🟡/🔴는 명세서의 중요도, `→` 뒤는 SPEC 문서.

> **Phase 1 = unitlab 내부 도구** 결정에 따라 ROADMAP 재배치 (PLAN.md §5/§9/§10 참조). 주요 변경:
> - **M0**: sidecar 보강 DB(`autocost_enriched.db`) 빌드 작업 추가. 운영 메인 ETL 수정 의존성 제거.
> - **M1**: 1회 부트스트랩 재학습 + 항목별(자재/노무/장비/간접비) MAPE 측정 추가.
> - **M2**: F5(인증) / F10(감사 로그) 작업 제거 — 흡수 후 운영 메인 측에서 구현. 이 repo의 M2는 "흡수 PR 준비"로 변경.
> - **M3**: 운영 메인 `원가분석-프로그램` branch 안에서 진행 (이 repo는 흡수 후 archive).

## M0 — 데이터 진입 가능 상태 (4주 가정)

데이터를 가져오고 정제해서 *예측 가능한 형태*까지 만든다. 모델은 아직 안 짠다.

> **M0 진행 메모 (2026-05-09)**: 운영 DB 인벤토리 + 노션 source 검증 완료 → [`docs/OPERATIONAL_DB_MAPPING.md`](docs/OPERATIONAL_DB_MAPPING.md) §1~6.
> - 운영 DB `actual_costs` 931행 vs 노션 1415행 — 운영 ETL ~1/3 손실. sidecar로 회수.
> - 16개 프로젝트 확정 (n=8 → n=16+ 표본 확장).
> - cost_type 분류는 운영 DB·노션 모두 부재 → `work_code_cost_types` 매핑 필수.
> - 수량/단위/단가는 노션에도 부재 (첨부 파일 안에) → Phase 1은 단가 추정 없이 진행.

| F# | 기능 | 우선순위 | SPEC |
|---|---|---|---|
| ~~F4.1~~ | ~~노션 워크스페이스 연결 UI~~ — Phase 1 미포함 (Q13). `notion_etl.py` 백엔드 사용. | — | `docs/DATA_INGEST_SPEC.md` |
| ~~F4.2~~ | ~~엑셀 업로드 UI~~ — Phase 1 미포함, 코드 보존 (Phase 2 부활). | — | 동일 |
| F1.2 | 공종/자재 동의어 매핑, 단위 변환 표준화 | 🔴 | `docs/DATA_INGEST_SPEC.md`, `harness/mapping/` |
| F9 | 공종/자재/단위 마스터 데이터 추가·수정·매핑 (vendor 보강은 노션 `고객 업체 DB` 활용) | 🟡 | `docs/MASTER_DATA_SPEC.md` |
| F1.3 | 누락/이상치 탐지 + 정제 규칙 편집·재처리 | 🟡 | `docs/DATA_INGEST_SPEC.md` |
| **NEW** | **work_code 147개 → cost_type 매핑 (단계적 escalation, Q12)** | 🔴 | `docs/MODEL_SPEC.md` §1.5 |
| **NEW** | **Sidecar `autocost_enriched.db` 빌드 (Q3)** | 🔴 | `docs/OPERATIONAL_DB_MAPPING.md` §6 |

**M0 종료 조건**:
- `harness/scripts/profile_actual_costs.py` 출력에서 `actual_costs` 결측률·이상치 정량화 (이미 산출).
- `material_aliases` (250개) 매칭 커버리지 측정 → `≥ 80%` 도달 (현재 미측정).
- `bim_unit_conversions` 활성 매핑 커버리지 측정.
- `vendor_name` 정제 룰 작성 + 결과 리포트 (`harness/reports/vendor_cleanup.json`).
- **Sidecar enriched DB 빌드 완료** (`autocost_enriched.db`). 노션 1415행 → sidecar 적재 (운영 DB 931행 +484 회수).
- **`work_code_cost_types` 매핑 완료**: 147개 work_code → 자재/노무/장비/간접비 분류 (Q10 B 확정 — Q10 A 검증 실패).

### M0 작업 큐 (현재 시점)

- [x] 운영 DB 인벤토리 → `docs/OPERATIONAL_DB_MAPPING.md`
- [x] `harness/data_contracts/notion_actual_costs.md` 운영 DB 정합성 재작성
- [x] `harness/data_contracts/excel_construction.md` 운영 DB 정합성 재작성
- [ ] `harness/scripts/profile_actual_costs.py` — 결측률/이상치/매핑 커버리지
- [ ] `harness/scripts/clean_vendor_names.py` — `vendor_name` URL 분리 (read-only 결과 리포트)
- [ ] `harness/scripts/measure_alias_coverage.py` — `raw_description` ↔ `material_aliases` 매칭률
- [x] **노션 source 스키마 검증** (Q6, Q10A) — 2026-05-09 zip export + MCP fetch 검증. `'선택'` 컬럼이 cost_type 확정. 결과: `docs/OPERATIONAL_DB_MAPPING.md` §6.
- [x] **`harness/sql/enriched_schema.sql`** — sidecar `autocost_enriched.db` 스키마. 5 테이블: actual_costs_enriched / vendors_master / projects_master / model_versions / etl_runs.
- [x] **`harness/scripts/build_enriched_db.py`** — Zip 3 (e32da8d7-...) 에서 1420 cost rows + 429 vendors + 23 projects 적재 완료 (2026-05-09 1차 빌드). cost_type=노션 '선택' 직접 매핑 (MAT/LAB/EXP/MIXED/ETC/EXCL/RECUR/OTHER 8종 정규화).
- [ ] **`unitlab-notion-cost/src/data_access.py:74` 수정** — `cost_type=source_ref`를 sidecar `actual_costs_enriched.cost_type` 조인으로 변경. Q10 A 부활로 work_code_cost_types 매핑 테이블 불필요 (escalation 2차 진입 시에만 필요).
- [ ] **23 → 16 프로젝트 reconciliation** — 빌드 결과 23개 distinct project_notion_id 추출되었으나 명세상 16개. 차이 분석 (parent rows / 다른 collection 섞임 / 영업 중인 신규 프로젝트 등). 실제 학습은 cost row 충분한 프로젝트만.
- [ ] **MCP로 16개 프로젝트 메타 보강** — projects_master의 address/customer_type/permit_type/module 메타를 영업 프로젝트 DB에서 fetch. 현재는 cost rows에서 derive만 됨 (name + module hint).
- [ ] `docs/MODEL_SPEC.md`, `MASTER_DATA_SPEC.md`, `AUTH_AUDIT_SPEC.md` 의 "신규 작업" 섹션 운영 DB 자산 기준으로 축소.

## M1 — MVP 예측 (4주 가정)

정제 데이터로 첫 예측 결과를 낸다. 단일 역할(Admin), 단일 모델 버전.

| F# | 기능 | 우선순위 | SPEC |
|---|---|---|---|
| F1.1 | 자재 원가 추출 → 공종별 옵션 자동 생성 | 🟡 | `docs/DATA_INGEST_SPEC.md` |
| F6.1 | 프로젝트 조건 입력 폼 + 로스율 가정 | 🔴 | `docs/UI_SPEC.md` |
| F2.1 | 원가 예측 실행 + 항목별(자재/노무/장비/간접비) 분해 | 🔴 | `docs/MODEL_SPEC.md` |
| F7.1 | 상위 영향 변수 + 유사 프로젝트 비교 | 🔴 | `docs/MODEL_SPEC.md` (Explainability 절) |
| F3.1 | 대시보드 시각화 (예측 원가/로스율/항목 비중) | 🟡 | `docs/UI_SPEC.md` |

**M1 추가 작업** (2026-05-09 부트스트랩 완료):
- [x] **부트스트랩 재학습** — sidecar 빌드 후 `backtest_v2.py` LOO 측정 완료.
- [x] **항목별 MAPE 측정** — 4 카테고리(MAT/LAB/EXP/MIXED) 측정 완료. 결과: `reports/loo_backtest_by_cost_type.json`.
- [x] **filter sweep** — 8개 scenario 측정. F가 best (`backtest_sweep.py`), `backtest_v2.py:DEFAULT_FILTERS`에 적용.

**M1 종료 조건 vs 현재 (2026-05-09)**:
- 총액 ±20% hit-rate **9/15 (60%) ✅** (확장 표본 기준 ≥ 9/15)
- 총액 MAPE 25.6% — 목표 ≤ 15% 미달
- 항목별 MAPE 4개 카테고리 산출 완료 ✅
- → **M1 부분 통과** (hit-rate ✅, wMAPE ❌). M2 진입은 wMAPE 개선 필요.

## M2 — 흡수 PR 준비 (3주 가정, Phase 1 = 내부 도구)

리포트 출력, 사용자 수동 재학습, 흡수 PR까지. 흡수 트리거(자재 항목 MAPE < 15%) 달성 시 운영 메인으로 PR.

| F# | 기능 | 우선순위 | SPEC |
|---|---|---|---|
| F3.2 | 리포트 다운로드 (PDF/엑셀, 포함 항목 선택) | 🟡 | `docs/UI_SPEC.md` |
| F6.2 | 조건 템플릿 저장/불러오기 | 🟡 | `docs/UI_SPEC.md` |
| F8.1 (early) | **사용자 수동 trigger 통합 endpoint `POST /api/refresh-data`** — ETL → sidecar 갱신 → 부트스트랩 재학습 → 부분 자동 롤백 검사 → UI 알림 (Q14) | 🟡 | `docs/MODEL_SPEC.md` §3 |

**M2 추가 작업** (분할 PR 전략, PLAN.md §10.2 참조):

**M2-PR1: 운영 schema + ETL 흡수** (2026-05-09 spec 작성 완료)
- [x] `harness/sql/migration_pr1.sql` — `actual_costs` ADD `cost_type`/`package` + `cost_type` 정규화 UPDATE (기존 source_ref 한글 → MAT/LAB/EXP/...). `projects` ADD 6 메타 컬럼 + 인덱스.
- [x] `harness/scripts/migrate_sidecar_to_op.py` — sidecar projects_master 23 → 운영 projects 메타 백필. project_name normalize fuzzy match (19/23 자동 매칭). `--apply` 없으면 dry-run.
- [x] `harness/migration/notion_etl_patch.md` — 운영 `agents/notion_etl.py` 변경 명세 (COST_TYPE_MAP 흡수, `source_ref` 본 의도 회복, 영업 프로젝트 DB → projects 메타 적재).
- [ ] (운영 메인 측 작업) `agents/notion_etl.py` 패치 적용 + 운영 DB에 migration_pr1.sql 적용 + migrate_sidecar_to_op.py 실행.

**M2-PR1.5 (옵션, 별도): vendors 마스터**
- [ ] `harness/sql/vendors_schema.sql` — vendors 테이블 신설 + actual_costs.vendor_id FK.
- [ ] `harness/scripts/vendor_cleanup_full.py` — 노션 업체DB 429 행 → 운영 vendors 백필. vendor_name URL 정제 적용.

**M2-PR2: 모델 코드 이동 spec** (2026-05-09 spec 작성 완료)
- [x] `harness/migration/pr2_model_code.md` — 9 파일 매핑 (이동/병합/폐기), data_access 단순화 (sidecar 의존 제거, v1+v2 통합), backtest 운영 메인 경로, promotion_status enum 통일 의존성, 검증 체크리스트.
- [ ] (운영 메인 측 작업) PR-1 머지 후, 본 spec대로 코드 이동 + LOO 재측정. trigger 7/7 통과 검증.

**M2-PR3: API/프론트 통합 spec** (2026-05-09 spec 작성 완료)
- [x] `harness/migration/pr3_frontend.md` — 8 endpoint 매핑 (이동/병합/feature flag) + `/api/refresh-data` Q14 통합 endpoint 신설 안 + 4 React 컴포넌트 (`<ProjectConditionForm>`, `<PredictionResult>`, `<EvidencePanel>`, `<DataRefreshButton>`) + F4 업로드 코드 보존 정책.
- [ ] (운영 메인 측) PR-2 머지 후 React 컴포넌트 작성 + FastAPI endpoint 이전.

**M2-PR4: archive 절차** (2026-05-09 spec 작성 완료)
- [x] `harness/migration/pr4_archive.md` — 사전 검증 4 항목, README archive 명시, sidecar 폐기 절차, GitHub archive, Phase 2 진입 조건.
- [ ] (운영 메인 머지 후 실행) 사전 검증 → README 갱신 → sidecar 백업·폐기 → repo archive.

**M2 종료 조건** (변경됨):
- 7-condition trigger 7/7 통과 ✅ (PLAN.md §10.1).
- M2-PR1 운영 메인 머지 → 후속 PR-1.5/2/3 단계적 머지.
- 운영 메인의 새 schema에서 자재 MAPE 재측정 (sidecar와 일치 검증).

**M2에서 제거된 작업** (Phase 1 = 내부 도구 결정 cascade):
- ~~F5.1 이메일 회원가입/로그인~~ → 흡수 후 운영 메인 측 별도 ticket
- ~~F5.2 사용자/권한 콘솔~~ → 동일
- ~~F10.1 감사 로그 조회~~ → 운영 메인의 `audit_log` (현재 0행, 스키마만 존재) 활성화 시 함께
- ~~"외부 시연 시나리오 무인 통과"~~ → 외부 가정 폐기

**M2 종료 조건**:
- **자재 항목 MAPE < 15%** 달성 (= 흡수 트리거).
- 흡수 PR 운영 메인에 머지 (이 repo는 archive 단계 진입).

## M3 — 모델 운영 자동화 (운영 메인 안에서, 흡수 후)

이 repo가 흡수된 뒤 운영 메인 `원가분석-프로그램` branch에서 진행. 새 데이터가 쌓일 때 모델을 갱신하고 성능을 추적한다.

| F# | 기능 | 우선순위 | SPEC |
|---|---|---|---|
| F8.1 | 모델 재학습 작업 큐 + 상태 표시 (정기 cron 또는 데이터 누적 trigger) | 🟡 | `docs/MODEL_SPEC.md` |
| F8.2 | 버전별 성능 지표 대시보드 + 수동 활성화/롤백 (M2의 부분 자동 롤백 위에 얹음) | 🟡 | `docs/MODEL_SPEC.md` |
| F5.1.1 | SSO 로그인 (선택) | 🟢 | `docs/AUTH_AUDIT_SPEC.md` |
| F3.2.2 | 엑셀 표준 템플릿 | 🟢 | `docs/UI_SPEC.md` |

**M3 종료 조건**: 신규 데이터 1회 추가 → 재학습 → 신·구 버전 성능 비교까지 무인 통과.

## 마일스톤 외 — 운영 메인 측 작업 (흡수 시점에 묶어서 진행)

이 repo의 결정에 따라 **운영 메인이 별도 ticket으로 작업**할 항목:

- **F5 사용자/권한 시스템 신규** — 운영 DB에 `users / role_permissions / user_roles` 테이블 신설 (운영 DB MAPPING §4 참조). Phase 1은 hardcode admin이지만 흡수 후 다인 사용을 위해 필요.
- **F10 audit_log 활성화** — 운영 DB에 스키마만 있는 `audit_log` 테이블에 트리거/미들웨어 연결.
- **운영 ETL 수정** — sidecar enriched 컬럼들이 운영 `actual_costs`에 schema 변경 + 백필. 이때 sidecar DB 폐기.
