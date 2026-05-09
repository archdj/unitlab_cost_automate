# PR-3: API/프론트 통합 spec

전제: **PR-1, PR-2 머지 완료** — 운영 DB schema 통합 + 모델 코드 운영 메인에 위치.

본 PR의 목표:
1. 이 repo의 vanilla SPA(`src/web/`) 견적 화면을 운영 메인의 React 프론트로 이식
2. FastAPI 엔드포인트를 운영 메인 backend로 이전
3. `POST /api/refresh-data` (Q14 통합 endpoint)을 운영 메인에 신설

---

## 1. 엔드포인트 매핑 (`autocost-spec-2026-05-07/src/api.py` → 운영 메인)

| 현재 endpoint | 동작 | 운영 메인 대응 | 처리 |
|---|---|---|---|
| `GET /` | vanilla SPA index | (운영 React 라우트로 이전) | drop, React 페이지에서 대체 |
| `GET /api/health` | 운영 DB 연결 확인 | 운영 메인의 헬스체크에 통합 | merge |
| `GET /api/modules` | module_types 목록 | 운영 메인에 동일 endpoint 신설 | 이동 |
| `GET /api/projects` | 프로젝트 메타 | 운영 메인의 기존 projects API와 통합 | merge — PR-1 후 컬럼 풍부화로 한 번에 |
| `POST /api/predict` | 예측 + 근거 (F2+F7) | 운영 메인에 신설 (`/api/cost-prediction/predict`) | 이동 |
| `GET /api/profile` | M0 데이터 품질 | 운영 메인의 admin section | 이동 |
| `GET /api/coverage` | alias 매칭 커버리지 | 동일 | 이동 |
| `POST /api/upload` | F4 업로드 검증 | **Phase 1 미포함** (Q13). 코드는 보존되 endpoint 비활성. | feature flag |
| `POST /api/refresh-data` | **신규** Q14 통합 trigger | 운영 메인에 신설 | 신규 작성 |

### `/api/refresh-data` 구현 안 (운영 메인 측)

```python
@app.post("/api/refresh-data")
def refresh_data():
    """Q14 통합 endpoint. ETL → 재학습 → 부분 자동 롤백 검사 chain."""
    # 1. ETL: 노션 → 운영 actual_costs/projects (notion_etl.py 호출)
    etl_result = run_notion_etl(con)

    # 2. Bootstrap retrain
    samples = load_actual_samples(con, **DEFAULT_FILTERS)
    pool    = Pool.from_samples(samples)
    new_metrics = backtest_loo(pool, samples, projects)

    # 3. 부분 자동 롤백 (자재 MAPE 비교)
    old_active = get_active_model_version(con)
    activated  = should_activate(new_metrics, old_active)
    if activated:
        register_new_model(con, new_metrics)
    else:
        archive_new_model(con, new_metrics, reason="material_mape_regression")

    return {
        "added_rows":          etl_result.added,
        "updated_rows":        etl_result.updated,
        "model_version_new":   new_metrics["version"],
        "model_version_active": old_active["version"] if not activated else new_metrics["version"],
        "material_mape_new":   new_metrics["MAT_mape_pct"],
        "material_mape_old":   old_active["MAT_mape_pct"],
        "activated":           activated,
        "message":             "..."
    }
```

동기 실행 (n=15 학습 분 단위). 흡수 후 cron 자동화는 M3 별도 작업.

---

## 2. 프론트 통합

### 현재 vanilla SPA (`src/web/`)
- `index.html` — 단일 페이지
- `app.js` — F6 입력폼 + F2 예측 호출 + F7 근거 표시
- `style.css`

### 운영 메인 React 프론트
- 기존 페이지 layout 따름
- 신규 라우트 `/cost-prediction` (또는 운영 메인 컨벤션)
- 기능 컴포넌트:
  - `<ProjectConditionForm>` — F6.1 모듈 선택 + 평형/등급
  - `<PredictionResult>` — F2 결과 + breakdown 차트
  - `<EvidencePanel>` — F7 (top features / similar projects / data quality)
  - `<DataRefreshButton>` — Q14 `/api/refresh-data` trigger + 결과 toast + 마지막 갱신 시각

### 이식 가이드
- vanilla `app.js` → React 컴포넌트 변환 (페어와이즈 매핑)
- `style.css` → 운영 메인의 CSS-in-JS 또는 styled-components 컨벤션 따름
- API 호출 경로: `/api/predict` → `/api/cost-prediction/predict` (또는 운영 컨벤션)

PR-3 산출물에 *운영 메인의 컴포넌트 위치* 명세는 운영 메인 코드 검토 후 결정.

---

## 3. F4 업로드 — 코드 보존, UI 미포함 (Q13)

`POST /api/upload` 와 `loaders.py` 코드는 운영 메인의 admin tools/ 또는 dev-only 경로에 보존. Phase 1 사용자 시나리오에는 미포함.

Phase 2 (외부 SaaS화) 진입 시 React 컴포넌트로 이식.

---

## 4. 인증/권한 (F5/F10)

PR-3에서는 운영 메인의 *기존 인증 시스템* 사용. 인증 자체는 별도 구현 (Phase 1 = 내부 도구로 hardcode admin 또는 운영 메인 인증 재사용).

`audit_log` 활성화 (F10) 도 별도. PR-3 scope 밖.

---

## 5. 산출물 체크리스트

- [ ] 운영 메인 React에 `/cost-prediction` 라우트 + 4 컴포넌트 추가
- [ ] FastAPI에 5 endpoint 이전 + 1 endpoint(`/api/refresh-data`) 신설
- [ ] `/api/upload` 보존 + UI에서 미노출 (feature flag)
- [ ] vanilla SPA 코드 (`autocost-spec-2026-05-07/src/web/`) → "archived for reference" 명시
- [ ] PR-3 머지 후 사용자 시연 (PLAN.md §5 김대리 시나리오)

---

## 6. Out of scope

- F5 / F10 (PR-4 또는 별도 PR — 운영 메인이 자체 결정)
- F8 cron 자동화 (M3)
- 첨부 PDF 파싱 (별도 PRD)
