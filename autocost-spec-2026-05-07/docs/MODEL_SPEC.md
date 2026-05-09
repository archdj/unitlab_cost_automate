# MODEL_SPEC — 예측 모델 + Explainability + 학습/버전 관리

명세서 기능 **F2, F7, F8** 통합. 모델은 `src/`, 학습/검증/재학습 워크플로는 `harness/scripts/` + `src/server.py`에 둔다.

## 1. F2 — 이력 기반 원가 예측 (M1 핵심)

### 1.1 입력 (F2.1.1 입력 요약)

| 입력 | 출처 | 필수 |
|---|---|---|
| 공종 | F6 프로젝트 조건 | ✅ |
| 규모 (면적/평형) | F6 | ✅ |
| 기간 | F6 | ✅ |
| 지역 | F6 | ✅ |
| 품질 수준 (등급) | F6 | ✅ |
| 로스율 가정 (기본/상한/하한) | F6.1.2 | ✅ |
| 학습 데이터 범위 | 자동 (정제된 actual_costs 전체) | — |

### 1.2 출력 (F2.1.2 항목별 분해)

```
{
  "total_cost": 123_456_789,
  "by_category": {
    "material": { "amount": ..., "ci_low": ..., "ci_high": ... },
    "labor":    { ... },
    "equipment":{ ... },
    "indirect": { ... }
  },
  "by_work_code": [ { "work_code": "...", "amount": ..., "ci_low": ..., "ci_high": ... } ],
  "evidence_id": "pred_2026..."  // F7에서 근거 조회 키
}
```

### 1.3 모델 출발점

`unitlab-notion-cost/src/notion_cost_model.py` (v10.0-notion) 를 베이스로 사용. 차이:

| 항목 | v10.0-notion (기존) | 본 프로그램 |
|---|---|---|
| 입력 | 면적 + 평형 + 등급 | + 공종, 지역, 기간, 로스율 가정 |
| breakdown | 공종 × 비용유형 | 동일 (자재/노무/장비/간접비) |
| 신뢰구간 | 공종별 ±X% | 동일 + Conformal Prediction 검토 |

### 1.4 검증 절차 (KPI 측정)

- LOO backtest v2 재사용 (`unitlab-notion-cost/src/backtest_v2.py` — sidecar 기반).
- KPI (PLAN.md §7 absolute 기준):
  - **M1 종료**: 총액 ±20% hit-rate ≥ 6/8 (확장 N=15+ 기준 ≥ 9/15), 총액 MAPE ≤ 15%, 항목별 MAPE 4개 카테고리(자재/노무/장비/간접비) **측정 완료**.
  - **흡수 트리거 (M2 종료, Q15-17 multi-metric, 자세히는 PLAN.md §10.1)**: 7-condition 충족 (자재 bootstrap 점추정 ≤ 30%, 노무 ≤ 50%, 경비 ≤ 60%, hit-rate ≥ 50%, median APE ≤ 18%, N ≥ 12, 안정성 ≤ 5%p).
  - **Aspiration (hard 아님)**: 모든 항목 MAPE < 10%.
- 결과는 `reports/backtest_<version>.json` + 항목별 결과는 `reports/loo_backtest_by_cost_type.json`.

#### 1.4.1 현재 baseline (2026-05-09, F filter 적용)

| 지표 | 결과 | 목표 | 갭 |
|---|---|---|---|
| 총액 ±20% hit-rate | **9/15 (60%)** | ≥ 60% | ✅ 도달 |
| 총액 wMAPE | 25.6% | ≤ 15% | -10.6%p |
| 총액 중앙값 APE | 13.9% | (참고) | — |
| **자재 MAPE (흡수 트리거)** | **39.5%** | < 15% | **-24.5%p** |
| LAB MAPE | 69.4% | < 10% (asp) | × |
| EXP MAPE | 61.1% | < 10% (asp) | × |

**F filter 정의** (`backtest_v2.py:DEFAULT_FILTERS`): cost_type IN (MAT,LAB,EXP,ETC), MIXED 학습 제외, status 무관(`use_all_statuses=True`), '미해당'/'32. 기타' work_code 제외.

#### 1.4.2 sweep 단계별 개선 이력 (2026-05-09)

| Scenario | wMAPE | ±20% hit | 자재 MAPE |
|---|---|---|---|
| baseline (입금완료만, 모든 cost_type) | 53.8% | 3/14 | 65.9% |
| A. + 진행 전 (status 완화) | 48.6% | 3/15 | 45.1% |
| B. A + drop MIXED | 43.1% | 3/15 | 45.1% |
| C. B + 완료/준공 프로젝트만 | 39.1% | 3/12 | 41.6% |
| D. C + drop noise wc(미해당/기타) | 27.3% | 5/12 | 41.2% |
| E. D + all statuses | 20.7% | 6/12 | 38.7% |
| **F. all statuses + drop noise** | **25.6%** | **9/15** | **39.5%** |
| G. F + outlier P95 | 25.6% | 9/15 | 39.5% (효과 없음) |
| H. F + outlier P90 | 28.0% | 9/15 | 41.0% (악화) |

#### 1.4.3 자재 MAPE 15% 도달을 위한 다음 후보 (별도 PRD)

코드 개선 한계 도달. 다음 단계는 데이터/도메인 작업:
1. **첨부 견적서/세금계산서 파일 파싱** — 수량·단가 보강 (R1 별도 PRD)
2. **모듈 마스터 entry 추가** — S-30/U-9/S-15 등 운영 메인에 신규 module_types 추가
3. **work_code 그룹화** — 51 distinct → 운영 6 category(STRUCTURE/FINISH/MEP/EXTERIOR/FURNITURE/SITE)로 정규화
4. **데이터 누적** — 매 입찰마다 sample 증가 → LOO 신뢰도 향상
5. **v11 ensemble v2** — 기존 ensemble.py를 sidecar 기반으로 재작성 (knn × conditional)

### 1.5 항목별(cost_type) 분리 데이터 source

운영 DB `actual_costs`에는 자재/노무/장비/간접비 분류 컬럼이 **존재하지 않음** (2026-05-09 schema 확인). `data_access.py:74`에 있는 `cost_type=source_ref` 매핑은 **버그** — `source_ref`는 노션 page_id이고 현재 한글 텍스트 혼입 상태라 의미 없는 group key.

**노션 원본 검증 결과** (2026-05-09 MCP fetch):
- 노션 source DB ("지출결의/입금요청", 1420행) 의 `'선택'` 컬럼이 **진짜 cost_type**.
- 96.3% 채워짐 (1362/1420). enum 값:
  - `재료비` → MAT (607행)
  - `노무비` → LAB (173행)
  - `경비` → EXP (199행)
  - `재료비+노무비` → MIXED (162행)
  - `제작+현장설치 비` → MIXED (10행 추가)
  - `기타` → ETC (125행)
  - `합계제외` → EXCL (50행, 학습 제외)
  - `정기이체` → RECUR (48행, 임대료/구독료 — 학습 제외)
- `'구분'` 컬럼은 **status** (입금완료/진행 전/검토중) — cost_type 아님.
- `'공종'` 컬럼은 work_code source (94.2% 채워짐, 51개 enum) — work_code_cost_types 수동 매핑 대신 work_code_text로 그대로 sidecar에 저장.
- → **Q10 A 채택** (노션 '선택' 컬럼이 cost_type) — 처음 zip 검증 시 컬럼명 오인으로 B로 결정했었으나 MCP fetch에서 schema 직접 확인 후 A로 부활.

**확정 source**: `actual_costs_enriched.cost_type` 컬럼 (sidecar enriched DB) — 노션 '선택' 직접 정규화.

**Q12 단계적 escalation 정책** (자재 MAPE < 15% 도달이 막힐 때 적용):

| 단계 | 매핑 형태 | 적용 시점 |
|---|---|---|
| 1차 (M0 기본) | 노션 '선택' 그대로 사용. MAT/LAB/EXP 라벨된 행만 각 카테고리 MAPE 측정. **MIXED·ETC·RECUR·EXCL은 학습엔 포함, 자재 MAPE 측정에서 제외** | M0에서 시작 |
| 2차 | MIXED 행을 추가로 학습 데이터에서 제외 (모델 입력 자체에서 drop) | 1차 측정값이 < 15% 미달이면 적용 |
| 3차 | MIXED를 (재료:0.6, 노무:0.4) 같은 비율로 분리. 비율 출처는 운영팀 검토 또는 첨부 견적서 파싱 | 2차로도 미달이면 적용 (비율 자료 필요) |

**M0 작업 항목 (실행 완료)**:
- ✅ `harness/sql/enriched_schema.sql` — sidecar 스키마.
- ✅ `harness/scripts/build_enriched_db.py` — Zip 3에서 1420 cost rows + 429 vendors 적재 완료. 23 projects 추출.
- [ ] `unitlab-notion-cost/src/data_access.py:74` 수정 — `cost_type=source_ref` → sidecar `actual_costs_enriched`의 `cost_type` 컬럼 직접 사용 (work_code_cost_types 매핑 불필요).

## 2. F7 — Explainability (M1 동시 출시)

### 2.1 F7.1.1 상위 영향 변수 랭킹

- 모델별 산출법:
  - Tree 계열 → `feature_importance_` 또는 SHAP TreeExplainer
  - 선형/Ridge → 표준화 계수 절댓값
- 응답 포맷:
  ```
  [ { "feature": "면적", "contribution": 0.31, "direction": "positive" }, ... ]
  ```
- 상위 N=5 고정 (UI 측 결정).

### 2.2 F7.1.2 유사 프로젝트 비교

- 거리 함수: `unitlab-notion-cost`의 모듈/평형/등급 weighting 재사용.
- 출력: 상위 5개 프로젝트 + 각 프로젝트의 실제 원가/조건 + 본 예측과의 차이.
- 데이터 품질/커버리지 지표 (명세서 수용기준 #3): 누락률, 최신성(median 결제일 경과 일수), 공종별 샘플 수.

## 3. F8 — 재학습 / 버전 관리

ROADMAP 재배치에 따라 단계별로 등장:
- **M1 (이 repo)**: ① sidecar 빌드 직후 1회 부트스트랩 재학습 (`harness/scripts/bootstrap_retrain.py`).
- **M2 (이 repo)**: ② 사용자 수동 trigger UI + **부분 자동 롤백** — 신 모델의 자재 MAPE가 구 모델 대비 악화하면 active로 승격하지 않음.
- **M3 (운영 메인 안에서)**: F8.1 큐 + F8.2 버전 비교 대시보드 (수동 롤백 UI 추가).

### 3.1 재학습 정책 (Q9 + Q14 결정)

| Trigger | 시점 | 자동/수동 |
|---|---|---|
| ① 부트스트랩 | sidecar enriched DB 첫 빌드 직후 | 자동 (빌드 스크립트 마지막 단계) |
| ② **`POST /api/refresh-data` 통합 endpoint** — ETL → sidecar 갱신 → 재학습 → 부분 자동 롤백 검사를 한 chain | 사용자가 UI "데이터 갱신" 버튼 누를 때 (Q14) | 수동 trigger, 내부 자동 chain |
| ③ 정기 cron | 흡수 후 운영 메인 측 결정 (M3) | 자동 (옵션) |

### 3.2 F8.1 재학습 워크플로

```
[① bootstrap]   sidecar build 마지막 → bootstrap_retrain.py
                  → notion_cost_model.train + LOO 측정 → model_versions row + reports/

[② refresh-data]  사용자(hardcode admin) → "데이터 갱신" 버튼
                  → POST /api/refresh-data
                    → notion_etl 실행 (변경된 노션 행만 sidecar 갱신)
                    → bootstrap_retrain (n=16 분 단위 동기)
                    → 신 모델 LOO 측정 (총액 + 항목별)
                    → 부분 자동 롤백 검사 (자재 MAPE 비교)
                    → 악화 → archived 저장, active 미승격
                    → 개선 → active 갱신
                  → response: {added_rows, model_version_new/active, material_mape_new/old, activated, message}
                  → UI: 결과 toast + 마지막 갱신 시각 갱신
```

### 3.3 부분 자동 롤백

- 신 모델 자재 항목 weighted MAPE > 구 모델 자재 항목 MAPE × 1.05 (5% margin) → 신 모델 archived 상태로 저장, active 미승격.
- 사용자는 `model_versions` 목록에서 archived 모델을 수동으로 active 변경 가능 (override).
- 흡수 후 (M3) F8.2에서 본격적인 비교 대시보드 + 클릭 롤백.

### 3.4 model_versions 테이블

흡수 전: sidecar `autocost_enriched.db`의 `model_versions` 테이블.
흡수 후: 운영 DB의 **`ml_model_info`** 테이블 그대로 사용 (운영 DB MAPPING §3.F8 참조 — 운영 자산 재사용, 신규 만들 필요 없음).

| 컬럼 | 설명 |
|---|---|
| version | 'v11.0' 등 |
| trained_at | 학습 시각 |
| data_range_start / data_range_end | 학습 데이터 범위 |
| metrics_json | LOO MAPE (총액·항목별 4종), hit-rate 등 |
| status | active / archived / failed |
| created_by | 사용자 ID (흡수 전엔 'admin' 고정) |

## 4. 작업 항목 (이 문서 기준)

- [ ] `src/predict.py` — F6 입력 → F2 출력 어댑터 (`unitlab-notion-cost`의 predict 호출)
- [ ] `src/explain.py` — F7.1.1, F7.1.2
- [ ] `harness/scripts/retrain.py` — F8.1 큐 진입점
- [ ] `harness/sql/model_versions_schema.sql` — F8 버전 테이블
- [ ] `harness/sql/predictions_schema.sql` — `evidence_id` 키 보관

## 5. 가정·결정 사항

- 운영 DB `unitlab-cost-analysis/db/cost_analysis.db`는 **read-only**. 모델 학습 결과는 `reports/`와 `harness/sql/`로 정의된 보조 테이블에만 쓴다.
- 모델 binary는 `*.pkl`로 `.gitignore` 처리, 버전별 위치는 `reports/model_<version>.pkl`.
