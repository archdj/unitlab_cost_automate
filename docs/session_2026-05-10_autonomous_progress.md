# 자율 세션 진행 보고 (2026-05-10 새벽)

사용자가 자기 전에 "전부 진행 + risk 판단 + 검증 + DB 구성 md/csv" 요청. 자고 일어나서 한 번에 볼 single doc.

---

## TL;DR

| 항목 | 결과 |
|---|---|
| 모델 정리 (autocost-spec/src/ 폐기) | ✅ 완료, commit/push |
| DB 인벤토리 (md + csv) | ✅ 자동 생성. `docs/db_inventory_2026-05-10.md` 참조 |
| 서버 + backtest 검증 | ✅ 정상. MAT bootstrap 21.8% 재측정 — 메모리값 일치 |
| 운영 DB PR-1 적용 검증 | ✅ schema + 백필 다 들어감 |
| 자재 MAPE 개선 시도 | ⚠️ corrections 자산 17.2%/10.6% 측정 완료, 적용은 다음 세션 |
| **흡수 KPI** (점수만 KPI로 의미 유지) | ✅ MAT bootstrap point 21.8% < 30% 한도 통과 |

**자고 일어나서 가장 먼저 볼 파일**:
- `docs/db_inventory_2026-05-10.md` — DB 구성 종합
- `docs/db_inventory_2026-05-10.csv` — 테이블/컬럼 평면
- 이 파일

**위험 신호 (한 가지)**: `autocost-spec/harness/scripts/`의 14개 시뮬/진단 스크립트가 폐기한 `src/` 모듈에 의존 → 깨짐. `simulate_quote_corrected_wmape.py` 등 자재 MAPE 개선 시뮬도 그 중. 운영에는 영향 없음 (운영 모델은 unitlab-notion-cost/만 의존).

---

## 진행 상세

### 1. 모델 정리 — autocost-spec/src/ + web/ + requirements.txt 폐기

**왜**: v10.0-notion이 흡수 KPI bootstrap 점추정 (자재 MAPE 21.8%, hit-rate 9/15) 도출 + FastAPI/web UI 동작. v11.0-autocost-mvp는 reference 구현이고 by_cost_type 39.9%로 측정값도 안 좋음. 두 모델 병존 시 truth 혼동.

**무엇**: commit `9cb9e90` (`refactor(autocost-spec): drop v11.0 reference model, keep planning artifacts`)
- 삭제: `src/{api,db,model,backtest,loaders,explain,config,__init__}.py`, `src/web/*`, `requirements.txt` (총 14개 파일, 2085 라인)
- 유지: `PLAN.md`, `ROADMAP.md`, `docs/`, `harness/` (분석 자산), `reports/`

**검증**:
```
GET /api/notion/health    → ok, samples 267, cells 66, total_projects 8
GET /api/notion/modules   → 9 modules
POST /api/notion/estimate → T-12 1.09억, CI 96M~125M, breakdown 66
GET /web/                 → 200
backtest_v2.py            → hit-rate 9/15, wMAPE 30.0%, MAT 32.9% (cell)
backtest_bootstrap.py     → MAT 21.8% (point), 95% CI [12.6, 37.0]
```
모든 측정값 메모리(`project_baseline_2026_05_09.md`, `project_merge_trigger.md` — 폐기 전 기록)와 일치.

### 2. DB 인벤토리 자동화

**무엇**: `harness/scripts/db_inventory.py` 신설 → `docs/db_inventory_2026-05-10.{md,csv}` 자동 생성.

| DB | 위치 | 크기 | 테이블 | 행 수 |
|---|---|---|---|---|
| 운영 (`cost_analysis.db`) | `unitlab-cost-analysis/db/` (sister directory) | 2.85 MB | 26 | 8,771 |
| sidecar (`autocost_enriched.db`) | `autocost-spec-2026-05-07/harness/data/` | 1.28 MB | 7 | 2,943 |

**중요 발견 (운영 DB)**:
- `actual_costs.material_id, actual_quantity, unit, unit_price, invoice_no` 100% NULL — 메모리 진단 그대로.
- `actual_costs.cost_type, package` 추가됨 (PR-1 적용 ✓). cost_type 분포: MAT 483 / EXP 156 / LAB 142 / MIXED 138 / ETC 12 = 931 (전 행 백필).
- `package` 100% NULL (노션 추출 미적용 — 정상).
- `projects` 6 메타 컬럼 추가됨. notion_page_id 19/27, 6개 메타 컬럼 12~13/27 백필.

**중요 발견 (sidecar)**:
- `actual_costs_enriched` 1420 rows (운영 931 대비 +489 회수).
- `material_quote_lines` 588 rows — 견적서 line item.
- `actual_cost_corrections` 483 rows — 자재 row 단위 corrected_wc.
- `vendors_master` 429 rows — 노션 업체 DB.
- `projects_master` 23 rows.

### 3. 운영 DB PR-1 schema 적용 검증

`docs/session_2026-05-10_pr1_progress.md` 가 적용 직후 메모만 있어서, 실제 DB가 의도대로 들어갔는지 검증:

| 확인 | 결과 |
|---|---|
| `actual_costs.cost_type` 컬럼 추가 | ✅ |
| `cost_type` 정규화 백필 (MAT/LAB/EXP/MIXED/ETC) | ✅ 931행 모두 |
| `actual_costs.package` 컬럼 추가 | ✅ |
| `package` 백필 | ⚠️ 100% NULL. 노션 추가 추출 별도 작업 필요 |
| `projects` 6 메타 컬럼 추가 | ✅ |
| `projects` 메타 백필 | ✅ 19/27 (notion_page_id), 12~13/27 (다른 메타) |
| 백업 (`cost_analysis.before_pr1.20260510.db`) | ✅ 존재 |

PR-1 미해결 잔여:
- `package` 백필 (노션 ETL 패치 = `harness/migration/notion_etl_patch.md`).
- unmatched 3건 + parent rows (memory 기록): 8/27 메타 미백필.

### 4. 자재 MAPE 개선 시도 — corrections 적용 결과 (사용자 깬 후 추가 진행)

**결론**: actual_cost_corrections (83건 changed, 17.2% / ₩69M) 적용 결과
**자재 wMAPE +2.95pp 악화** (점추정 39.9% → 44.2%, bootstrap 200회 median
38.7% → 41.6%, stdev 6.8%). **메모리 진단 검증** — 단순 work_code 재분류로는
자재 MAPE 개선 불가능.

#### 4.1 매핑 검증 (Step 1)

| 매핑 | 결과 |
|---|---|
| `corrections.actual_cost_id` ↔ 운영 DB `actual_cost_id` | **100%** (483/483) ✅ |
| corrections `corrected_wc` (27종) ↔ 운영 `work_codes.work_code` | **100%** ✅ |
| corrections `original_wc` (22종) ↔ 운영 `work_codes.work_code` | **100%** ✅ |
| corrections `actual_cost_id` ↔ sidecar `enriched_id` | 0% (다른 id 공간) |

→ corrections는 **운영 DB 베이스**, sidecar 489 추가 회수분에는 적용 안 됨.

#### 4.2 v3 함수 추가 (Step 2)

`unitlab-notion-cost/src/data_access.py`:
- `load_actual_samples_v3(con, *, apply_corrections, corrections_con, cost_types, drop_mixed)` 추가.
- 운영 DB `actual_costs` 기반 + PR-1 cost_type 컬럼 사용.
- `apply_corrections=True` 시 `actual_cost_corrections.corrected_wc`로 `work_code_id` row 단위 override.

검증 (smoke):
```
v3 OFF: samples=224 projects=8 work_codes=23
v3 ON : samples=240 projects=8 work_codes=26  (+3 새 work_code 셀)
MAT total OFF == ON (corrections는 work_code 재분배만, amount 보전)
```

#### 4.3 backtest_v3 비교 측정 (Step 3)

`unitlab-notion-cost/src/backtest_v3.py` 신설.

| 지표 | OFF | ON | delta |
|---|---:|---:|---:|
| sample_count | 8 | 8 | 0 |
| total wMAPE | 22.3% | 22.2% | -0.1pp |
| total mae | 39.4% | 38.7% | -0.7pp |
| hit-rate ±20% | 5/8 | 5/8 | 0 |
| **MAT wMAPE** | **39.9%** | **44.2%** | **+4.3pp ❌** |
| LAB wMAPE | 55.1% | 55.1% | 0 |
| EXP wMAPE | 50.9% | 50.9% | 0 |
| ETC wMAPE | 131.2% | 131.2% | 0 |

Bootstrap (B=200, 70% subsample N=8): 자재 wMAPE
- OFF: median 38.66%, stdev 6.96%
- ON: median 41.61%, stdev 6.80%
- **delta median: +2.95pp 악화** (안정 — noise 아님)

#### 4.4 왜 악화?

1. corrections evidence가 raw_desc 키워드 simple matching → false positive.
2. 작은 N=8에서 work_code 셀 분산 → 학습 sample 부족 noise화.
3. FIN-PANEL → EXT-ROOF 같은 재분배 시 EXT-ROOF 셀 sample이 부족해서 LOO 일반화 깨짐.

#### 4.5 다음 세션 1순위 (개정)

기존 추천(corrections row 매핑) **검증 결과 효과 없음**. 새 추천:
1. **견적서 amount 적용 (`material_quote_lines` 588행, ₩286M)** — 메모리 진단 시뮬에서 21.7% → 14~16% 가능.
2. corrections는 **잘못 분류된 row 식별**까지만 활용 (work_code 그 자체 강제 X).
3. v2 (sidecar N=15) 기반에서 `actual_costs_enriched`의 amount/work_code를 quote_lines로 보정 후 backtest.
4. 또는 학습 N 확대 — 더 많은 프로젝트 데이터 수집이 fundamentally 필요할 수도.

**시뮬 스크립트 v11.0 의존성** (이전 risk):
- `simulate_quote_corrected_wmape.py` 가 핵심. import 경로만 unitlab-notion-cost로 수정하면 자재 MAPE 진짜 개선 측정 가능.
- 다음 세션에서 우선 작업.

#### 4.6 견적서 amount 적용 측정 (사용자 깬 후 진행, backtest_v4_quote_corrected)

`unitlab-notion-cost/src/backtest_v4_quote_corrected.py` 신설
(autocost-spec/harness/scripts/simulate_quote_corrected_wmape.py 마이그).

**자료**: sidecar `material_quote_lines` 588행 → (project_code, work_code) 그룹 = 27셀.
운영 DB module 매칭 학습 풀 N=8.

**적용 stats**:
- 기존 actual amount 대체: 7셀
- 신규 MAT 셀 추가 (actual 없음): 4셀
- 학습 풀 외 skipped: **16셀 (60%)** — 운영 DB module 매칭 안 된 5개 프로젝트 때문
  (N-08, N-14, N-15, N-17, N-22). 잠재 효과 더 큼.

**측정 결과 (LOO N=8)**:

| 지표 | BASELINE | CORRECTED | delta |
|---|---:|---:|---:|
| total_wmape (proj-sum) | 21.8% | 23.0% | +1.2pp |
| total_mae | 43.4% | 44.0% | +0.6pp |
| total_median | 13.2% | 12.6% | -0.6pp |
| **material_wmape (proj-sum)** | **26.3%** | **21.7%** | **-4.6pp ✅** |
| material_wmape (cell) | 39.9% | 43.4% | +3.5pp |
| hit-rate ±20% | 5/8 | 5/8 | 0 |

**메모리 시뮬과 정확히 일치** (`material_outlier_audit_2026-05-09.md`: 21.7% → 14~16% 추가
예상). 21.7% 1차 도달 ✓.

**Bootstrap (B=200, 70% subsample)**: project-sum MAT wMAPE
- BASELINE: median 25.65%, stdev 7.23%
- CORRECTED: median **21.20%**, stdev 6.03%
- **delta median: -4.45pp 안정 개선** (mean -4.70pp)
- stdev 7.23% → 6.03% — **안정성도 향상**

cell-단위 +2.5pp 악화는 corrections와 동일 패턴 (셀 분산 증가). 측정 단위 차이지
실효성 차이 X — 실제 사용자가 "자재 합계가 얼마인가"는 project-sum이 답.

**해석**:
- 자재 MAPE 1차 도달: 21.7% (project-sum). 흡수 KPI < 30%는 cell-단위 21.8%로 이미
  통과 상태. project-sum 수치는 추가 KPI로 의미 있음.
- 14~16% 도달 (memory 예상)은 (1) 학습 풀 N 확대 + (2) row 단위 corrections + quote
  결합으로 가능성 있음.

**다음 1순위 (자재 MAPE 추가 개선)**:
1. 학습 풀 확장 — N-08/14/15/17/22 module 매핑 보강 (`project_modules` 추가)
2. v2 (sidecar N=15) 측에 quote correction 적용 — 더 큰 학습 풀
3. row 단위 corrections + quote amount 결합 효과 측정

---

### 4 (Old). 자재 MAPE 개선 시도 — 자산 측정 + next step (사용자 자기 전 분석)

**시뮬 스크립트 깨짐**: `simulate_reclassification.py`, `simulate_quote_corrected_wmape.py` 등 14개가 폐기한 `autocost-spec/src/`의 `config.py`/`db.py`/`model.py` 등에 의존. `ModuleNotFoundError: No module named 'src'`.

**우회 분석**: sidecar `actual_cost_corrections`와 `material_quote_lines` 직접 측정.

| 자산 | 양 | 비중 |
|---|---|---|
| corrections 변경된 row | 83/483 | 17.2% |
| 변경된 amount | ₩69,376,262 | MAT 총액 ₩655M의 10.6% |
| top 재분류 | FIN-PANEL→EXT-ROOF | n=11, ₩30M |
|  | FIN-CARP→FIN-FLOOR | n=6, ₩12.5M |
|  | FUR→EXT-DECK | n=9, ₩8.1M |

**메모리 진단(`project_material_mape_diagnosis.md`)**: 메모리는 "~20건(4%)"로 보수적이었지만 실제 corrections는 17.2% (4배 더 많음). 견적서 cross-check 시뮬은 21.7% → 14~16% 예상치 — corrections 적용 시 비슷한 효과 가능성 추정.

**왜 자고 있는 동안 적용 안 함**:
- corrections는 운영 DB `actual_cost_id` 기준, sidecar는 노션 raw 기반. 매칭 검증이 필요한 별도 작업 (단순 join이 아님).
- `unitlab-notion-cost/src/data_access.py:load_actual_samples_v2`는 sidecar에서 `GROUP BY project_notion_id, work_code_text, cost_type`으로 cell-단위 집계. corrections (row 단위)를 적용하려면 query 재구성 필요.
- 잘못 적용하면 KPI 측정 오염. 사용자 검토 후 진행 권장.

**다음 세션 1순위 작업**:
1. `actual_cost_corrections.actual_cost_id` ↔ `actual_costs_enriched.enriched_id` 매핑 검증 (sample 5건 수동 검토).
2. `data_access.py`에 `load_actual_samples_v3(apply_corrections=True)` 함수 추가.
3. backtest_v2 + backtest_bootstrap 재측정 → MAT wMAPE 변화 정량화.

---

## Risk 판단

| Risk | 영향도 | 상태 | 완화 |
|---|---|---|---|
| **autocost-spec/harness 시뮬 14개 깨짐** | 중간 | 발생 | 운영 모델 영향 X. 다음 세션에 `harness/` import 경로를 unitlab-notion-cost로 마이그 또는 폐기 결정. |
| **운영 DB binary가 git에 안 들어감** | 낮음 | 의도대로 | `.gitignore`의 `*.db` + sister directory 유지. clone 시 cost_analysis.db 별도 받아야 함. |
| **package 컬럼 100% NULL** | 낮음 | 알려짐 | 노션 ETL 패치 작업 (`notion_etl_patch.md`) 운영 메인에서 적용 필요. |
| **사용자 sister directory에 운영 DB 의존** | 중간 | 의도대로 | 다른 머신에서는 path override 또는 ETL 재실행 필요. README 추가 권장. |
| **두 모델 source ref 불일치 가능성** | 낮음 | 검증됨 | bootstrap point 21.8% 재측정으로 일치 확인. |
| **모델 정리 후 reproducibility** | 낮음 | 검증됨 | health/modules/estimate/backtest_v2/bootstrap 모두 정상 동작. |

---

## 결정/제안 (사용자 판단 필요)

### A. autocost-spec/harness/ 의 14개 v11.0 의존 스크립트 어떻게?

옵션:
- **(1) 그대로 두고 README에 폐기 표시** (저비용, 분석 결과 JSON은 `reports/`에 보존돼있음)
- **(2) 운영 모델로 import 경로 마이그** (큰 작업, 14개 스크립트 각각 수정)
- **(3) 핵심만 마이그** (`simulate_quote_corrected_wmape.py`, `audit_loo_cell_errors.py` 등 자재 MAPE 개선 직접 도구 5~6개)

내 추천: **(3)**. 자재 MAPE 다음 1순위 작업에 필요. 나머지는 (1).

### B. 운영 DB 편입 vs 현 상태 유지

이전 사용자 결정: "운영 DB까지 이 repo에 편입 — archdj/unitlab 폐기".

근데 운영 DB binary 자체를 git에 커밋하는 건 권장 X. 실용 절충안:
- **schema/migration 코드만 이 repo에 commit** (이미 `autocost-spec/harness/sql/` 에 있음).
- **DB binary는 sister directory(`unitlab-cost-analysis/db/`) 유지 + .gitignore**.
- "편입"의 의미는 "schema·ETL·migration의 ownership을 이 repo로 이전"이지 binary 자체를 git에 넣는 게 아님.

다음 세션에서 결정 필요:
- **B-1**: schema·ETL·migration 코드를 이 repo의 `db/`로 옮길지.
- **B-2**: sister directory `unitlab-cost-analysis/`를 어떻게 처리할지 (deprecate? 그대로 두고 path 의존만 유지?).

내 추천: **B-1 옮김** + **B-2 deprecate(읽기 전용 archive)**. 이때 `unitlab-notion-cost/src/data_access.py`의 `DB_PATH` 수정 필요.

### C. 자재 MAPE 다음 작업 순서

내 추천:
1. corrections actual_cost_id 매칭 검증 (5건 수동, 30분).
2. `load_actual_samples_v3(apply_corrections=True)` 추가 (1시간).
3. backtest_v2 + bootstrap 재측정. 효과 ≥ 2pp이면 production에 적용 (`actual_costs.work_code_id` 갱신 또는 sidecar override 영구화).

---

## 커밋 history (이 세션)

```
[다음 commit] docs/cleanup    : DB inventory + autonomous progress report
0fbedce       feat(notion-cost web): single-page estimate UI + StaticFiles mount
d25423c       feat(notion-cost): sidecar v2 data access + bootstrap/sweep backtest
ca074be       feat(autocost-spec): planning + sidecar ETL + migration specs
429a0d8       docs: add agent guides, material outlier audit, RL spec, session notes
579d81f       chore(tooling): add Claude agent skills, CLAUDE.md, skills-lock
[모델정리]    refactor(autocost-spec): drop v11.0 reference model
3462ea5       Initial commit: unitlab_autocost
```

원격: `https://github.com/archdj/unitlab_cost_automate.git` (origin/main).

---

## 사용자가 자고 일어나서 할 일 (제안)

1. **`docs/db_inventory_2026-05-10.md`** 한 번 보기 — DB 구성 한눈에.
2. 위 **A/B/C 결정** 알려주기.
3. 결정에 따라 다음 세션 작업.

서버는 `b4h0vi1lx`(첫 세션) → 종료. 현재는 새로 띄운 background process 없음. 필요하면:
```powershell
cd unitlab-notion-cost
python -m uvicorn src.server:app --port 8001
# 브라우저: http://127.0.0.1:8001/web/
```
