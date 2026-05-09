# PR-2: 모델 코드 이동 + data_access 단순화 spec

전제: **PR-1 머지 완료** — 운영 DB가 `cost_type`, `package`, `projects.notion_page_id` + 6 메타 컬럼을 가짐. ETL 패치 적용으로 새 행도 정확히 적재.

본 PR의 목표:
1. `unitlab-notion-cost/src/`의 모델·학습 코드를 운영 메인으로 이동
2. **sidecar 의존 제거** — 운영 DB 단일 source
3. v1/v2 분기 통합 (v2가 정답이 됨)
4. backtest 스크립트들을 운영 메인 경로로

---

## 1. 파일 매핑 (이동/병합)

| 이 repo (`unitlab-notion-cost/src/`) | 운영 메인 (예상 경로 `cost-analysis-program/src/`) | 처리 |
|---|---|---|
| `notion_cost_model.py` | `cost_model.py` (rename) | 이동 + 명칭 단순화 |
| `data_access.py` | `data_access.py` | **단순화** (§2 참조) — sidecar 함수 제거, v1+v2 통합 |
| `backtest_v2.py` | `backtest.py` (기존 v1 backtest 대체) | 이동, 함수명 단순화 |
| `backtest_sweep.py` | `tools/backtest_sweep.py` | tools/ 하위로 (one-off scenario sweep) |
| `backtest_bootstrap.py` | `tools/backtest_bootstrap.py` | tools/ 하위로 (CI 측정 도구) |
| `save_predictions.py` | `save_predictions.py` | 이동 (작업 변경 없음, 운영 ml_model_info 사용) |
| `ensemble.py` | `tools/ensemble.py` (옵션) | v9-knn × v10 ensemble. 흡수 시 v2 경로로 재작성 필요 — **PR-2에는 옮기지 않음**, 별도 PRD |
| `server.py` | (이동 안 함) | 운영 메인의 FastAPI에 endpoint 통합 (PR-3 scope) |
| `backtest.py` (v1) | (drop) | source_ref 버그 의존 코드. PR-1 후 의미 없음 |

기존 v1 backtest는 폐기. v2가 새 backtest의 baseline.

---

## 2. `data_access.py` 단순화

### 현재 (sidecar+op hybrid)
- `connect_readonly()` — 운영 DB
- `connect_enriched()` — sidecar
- `load_actual_samples()` v1 — 운영 DB의 source_ref hack (버그)
- `load_actual_samples_v2()` — 운영+sidecar join, module 추정 fallback
- `list_projects_for_backtest()` v1 / `_v2`

### PR-2 후 (운영 DB only)

```python
# 새 data_access.py — 단일 source, 단일 함수

LEARNABLE_COST_TYPES = ("MAT", "LAB", "EXP", "MIXED", "ETC")
LEARNABLE_STATUS = (...)  # 운영의 promotion_status enum 통일 후 결정
NOISE_WORK_CODES = ("미해당", "32. 기타", "32.기타")
PROJECT_COST_THRESHOLD = 49_000_000


def connect_readonly() -> sqlite3.Connection: ...

def list_projects_for_backtest(con) -> list[dict]:
    """학습 가능 프로젝트 — projects 테이블에서 메타 + module_types 조인.
    PR-1 후 projects.module_size_text와 module_types.module_code 매칭.
    fallback estimate(_estimate_module_meta)는 유지 — 운영에 미등록 모듈 대응."""

def load_actual_samples(con, *, cost_types=LEARNABLE_COST_TYPES, drop_mixed=False,
                        exclude_noise_work_codes=False, outlier_pct=None) -> list[dict]:
    """학습 입력. 운영 actual_costs.cost_type 컬럼 직접 사용.
    sidecar 의존 없음. status 필터는 운영 promotion_status 기반으로 재정의 (§4)."""
```

**제거되는 것**:
- `connect_enriched()` 함수
- `LEARNABLE_STATUS_RELAXED` (운영 promotion_status enum과 통일 후 결정)
- `MODULE_HINT_TO_OP_CODE` 하드코드 매핑 (운영의 `projects.module_size_text` + `module_types.module_code` 매칭으로 대체)
- `_project_int_id` (project_id가 INT primary key이므로 surrogate 불필요)
- v1 `load_actual_samples` / `list_projects_for_backtest` (폐기)

**유지되는 것**:
- `_estimate_module_meta(module_size_text)` — 운영에 미등록 모듈 fallback (양평 S-15 등 제3자 모듈 대응)
- `_classify_work_code_category(work_code_text)` — work_code → category 정규화

---

## 3. `backtest.py` (구 backtest_v2)

```python
DEFAULT_FILTERS = dict(
    cost_types=LEARNABLE_COST_TYPES,
    drop_mixed=True,
    exclude_noise_work_codes=True,
    # use_all_statuses 옵션은 운영 promotion_status enum 통일 후 결정.
)

def run() -> dict:
    con = connect_readonly()
    samples  = load_actual_samples(con, **DEFAULT_FILTERS)
    projects = list_projects_for_backtest(con)
    con.close()
    # ... LOO + bootstrap CI + cost_type별 MAPE
```

`bucket_actuals_by_project()` 헬퍼 보존 (LOO O(1) lookup).

`MATERIAL_MAPE_FOCUS = "MAT"` 보존 — trigger 평가 component.

---

## 4. `promotion_status` enum 통일 (의존성)

운영 메인 측 별도 작업: 운영 DB의 `promotion_status` 가 `approved`로 사실상 단일 사용 중인데 schema 정의는 `candidate/validated/promoted/rejected`. PR-2 동시 진행 또는 별도 PR.

`load_actual_samples`의 status 필터는 enum 통일 후 결정. 임시:
```python
LEARNABLE_PROMOTION_STATUS = ("approved", "promoted", "validated")  # config.py에서 import
```

`use_all_statuses=True` (PR-1 후엔 `status_code`가 의미 다름 — 노션 '구분' 매핑 적재 여부). 운영 메인 측 결정 필요.

---

## 5. Import 경로 조정

이 repo의 sys.path hack:
```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

운영 메인 패키지화 시:
```python
from cost_analysis_program.data_access import connect_readonly, load_actual_samples
from cost_analysis_program.cost_model import Pool, predict_for_module
```

---

## 6. 테스트 / 검증 (PR-2 머지 후)

```bash
# 1. 단위 데이터 로드
python -m cost_analysis_program.data_access  # samples count 확인

# 2. 백테스트 LOO
python -m cost_analysis_program.backtest
# 기대: ±20% hit-rate ≥ 50%, median APE ≤ 18%, MAT bootstrap 점추정 ≤ 30%
# (sidecar 측정값과 ±2%p 이내 — 1420 vs 931 행 차이)

# 3. Bootstrap CI
python -m cost_analysis_program.tools.backtest_bootstrap

# 4. Sweep (옵션)
python -m cost_analysis_program.tools.backtest_sweep
```

`reports/` 출력 경로는 운영 메인 컨벤션 따름.

---

## 7. PR-2 후 7-condition trigger 재측정

운영 DB에 1420 행이 ETL 패치로 적재되면:
- N ≥ 12 ✅ (15+)
- hit-rate / median / MAT / LAB / EXP — 동일 분포 기대 (sidecar 측정과 일치 확인 필요)

**기대 결과**: 7/7 통과 유지. 만약 변동 큼:
- `data_access.py:_estimate_module_meta` fallback 동작 검증
- `notion_etl.py` 패치가 cost_type을 정확히 적재하는지

---

## 8. v9-knn / v11 ensemble — 별도 PR

`ensemble.py`는 v9 예측을 운영 DB의 `cost_predictions` 테이블에서 조회. 흡수 후엔 v9가 동일 코드 베이스에 있어야 작동.

PR-2 scope 밖. 흡수 후 별도 작업으로:
- v9-knn 모델 구현 (현재는 cost_predictions에 결과만 있음)
- v11 ensemble을 새 backtest 위에 재작성

---

## 9. Out of scope

- PR-3: API endpoint(`/api/refresh-data`) 운영 FastAPI로 이전 + 프론트 통합
- PR-4: 이 repo archive
- 별도 PRD: 첨부 견적서 PDF 파싱, work_code 그룹화, v11 ensemble v2

---

## 10. PR-2 산출물 체크리스트

- [ ] 운영 메인에 `cost_analysis_program/` 패키지 생성 (또는 기존 경로 사용)
- [ ] `data_access.py` 단순화 버전 작성 (§2)
- [ ] `cost_model.py` 이동 (notion_cost_model.py rename)
- [ ] `backtest.py` 이동 (구 backtest_v2)
- [ ] `tools/backtest_sweep.py`, `tools/backtest_bootstrap.py` 이동
- [ ] `save_predictions.py` 이동
- [ ] 구 v1 코드(`backtest.py`, v1 `data_access` 함수) 폐기
- [ ] sidecar `autocost_enriched.db` 의존 코드 모두 제거
- [ ] PR-2 머지 후 LOO 측정 → 7-condition 재평가 (PR 본문에 결과 보고)
