# 공종별·자재별 MAPE 측정 — 기획서

작성일: 2026-05-05
대상: `cost_analysis.db` 운영 DB, `/api/accuracy`, `Accuracy.jsx`

---

## 1. 왜 필요한가

현재 정확도 지표는 **프로젝트 총액 단일 숫자**(MAE, 중앙값, ±X%) 만 노출합니다. 그러나:

- 총액이 ±20%여도 **STR-ST는 −50%, FIN-PANEL은 +30%** 인 경우, 우연히 상쇄돼 좋아 보이는 것일 뿐
- "어디가 부정확한지" 알아야 BIM/자재/단가 중 어느 입력을 보강할지 결정 가능
- 비전 문서의 90% 정확도 목표는 **공종 단위에서 달성**돼야 의미 있음 — 한 공종이 큰 오차여도 평균이 가려짐

**필요 지표:**
1. 공종별 MAPE (예: STR-ST의 평균 오차)
2. 자재별 MAPE (예: 강재 H-150×75의 평균 오차) — **현재 데이터 부족**
3. 비용유형별 MAPE (재료비 vs 노무비 vs 경비)
4. 가중 MAPE (금액 가중) vs 단순 MAPE (작은 outlier 영향 분리)

---

## 2. 데이터 충실도 진단 (2026-05-05 기준)

### 2.1 `actual_costs` (931건)
| 컬럼 | 채움률 | 비고 |
|---|---|---|
| `work_code_id` | **100%** ✓ | 공종 매칭 가능 |
| `source_ref` | **100%** ✓ | 비용유형 (재료비·노무비·경비) |
| `total_amount` | **100%** ✓ | 실제 금액 |
| `material_id` | **0%** ✗ | 전부 NULL — **자재별 측정 불가** |
| `actual_quantity` | **0%** ✗ | 전부 NULL |
| `unit_price` | **0%** ✗ | 전부 NULL |

→ **공종/비용유형 단위 측정은 즉시 가능. 자재 단위는 데이터 보강 필요.**

### 2.2 `bim_quantities` (2,455건, 새 IFC 9개 기준)
| 단위 | 비율 |
|---|---|
| m³ | 74% |
| EA | 20% |
| m² | 6% |
| m | 0.1% |

### 2.3 공종별 매핑 가능성 (TOP 12)

| work_code | 정의 unit | 실원가 | 적용 IFC | 매칭 여부 |
|---|---|---|---|---|
| STR-ST 철골공사 | ton | 313M | 9개 | ✓ |
| FIN-PANEL 샌드위치 판넬 | m² | 205M | 0개 | ⚠ **레벨 mismatch** (BIM은 FIN-PANEL-001) |
| EXT-WIN 창호공사 | EA | 172M | 9개 | ✓ |
| FUR 가구인테리어 | (없음) | 123M | 9개 | ✓ |
| FIN-LGS 경량철골 파티션 | m² | 108M | 9개 | ✓ |
| SITE-MOD-002 모듈 현장 접합 | EA | 108M | 0개 | ✗ BIM 없음 |
| FIN-CARP 목공사 | m² | 89M | 0개 | ✗ BIM 없음 |
| EXT-CLAD 외장재공사 | m² | 82M | 0개 | ✗ BIM 없음 |
| MEP-PLMB-004 온돌난방배관 | m | 43M | 0개 | ✗ BIM 없음 |

→ **5개 핵심 공종(STR/FIN-PANEL/EXT-WIN/FUR/FIN-LGS)이 약 921M (실원가 88%)** — 측정 가능 범위 충분.

### 2.4 `cost_predictions` 모델별 분포
| 모델 | 건수 | breakdown 구조 |
|---|---|---|
| v2.0-bim | 9 | work_code별 array (`{work_code, amount, ...}`) |
| v9.0-hybrid-ridge | 26 | area / option / site / total 4 컴포넌트 |
| v9.0-hybrid-knn | 26 | 동일 |
| v9.0-hybrid-ensemble | 26 | 동일 |

→ **v2.0-bim만 공종별 분해 가능**. v9.0은 컴포넌트별 (이미 `Accuracy.jsx`에 표시 슬롯 있음).

### 2.5 비용유형 (`source_ref`) 분포
| 유형 | 건수 | 비율 |
|---|---|---|
| 재료비 | 483 | 52% |
| 경비 | 156 | 17% |
| 노무비 | 142 | 15% |
| 재료비+노무비 | 137 | 15% |
| 기타 | 12 | 1% |

---

## 3. 측정 설계

### 3.1 공종별 MAPE (Phase 1 — 즉시 가능)

**입력:**
- 실측: `actual_costs.total_amount` GROUP BY `(project_id, normalized_work_code)`
- 예측: `cost_predictions.breakdown[*].{work_code, amount}` (v2.0-bim 모델)

**정규화 처리 (중요):**
- BIM은 level 3 work_code (FIN-PANEL-001) → `actual` level 2 (FIN-PANEL)와 매칭 안 됨
- 모든 비교 전에 work_code를 **level 2로 정규화** (이미 우리 시스템 표준)
- 매핑 테이블 활용: `BIM_TO_ACTUAL_WC`

**산식 (per work_code):**
```
errors = []
for project in projects:
    actual_wc   = sum(actual_costs.total_amount where project, work_code=W)
    pred_wc     = sum(breakdown[*].amount where project, normalized_work_code=W)
    if actual_wc > 0:
        errors.append(abs(pred_wc - actual_wc) / actual_wc)

mae_pct          = mean(errors) × 100
median_ape_pct   = median(errors) × 100
weighted_mape    = sum(|pred-actual|) / sum(actual) × 100
sample_count     = len(errors)
priority_score   = mae_pct × sum(actual)   # 큰 금액 + 큰 오차일수록 우선 보강
```

### 3.2 비용유형별 MAPE (Phase 1 — 즉시 가능)

`source_ref` 별로 같은 산식. 단, 예측은 cost_type별로 분해된 데이터 필요. 현재 v2.0-bim breakdown에는 cost_type 없음 — `evidence_estimate_components` 패턴(`/api/evidence/estimate`) 사용해 별도 도출 가능.

대안: **EvidenceEstimate 결과의 components를 cost_predictions와 별개로 저장** 또는 산식 보강.

### 3.3 자재별 MAPE (Phase 2 — 데이터 보강 후)

**현재 차단 사항:**
- `actual_costs.material_id` 100% NULL
- `actual_costs.actual_quantity` 100% NULL

**선결 작업 (마이그레이션):**
1. `migrate_notion.py` 보강 — Notion 발주 raw에서 자재명·수량·단가 파싱
2. 자재명 → `materials.canonical_name` 매핑 (기존 3,356개)
3. work_code 미매칭 자재는 별도 큐로 처리

**산식 (per material):**
```
actual_qty   = sum(actual_costs.actual_quantity where material_id=M)
actual_amt   = sum(actual_costs.total_amount where material_id=M)
predicted_qty = sum(bim_quantities.quantity where material_id=M)
predicted_amt = sum(bim_quantities.quantity × material_unit_price)

qty_mape   = abs(predicted_qty - actual_qty) / actual_qty
amount_mape = abs(predicted_amt - actual_amt) / actual_amt
```

**산출 시기:** Phase 2 (별도 마이그레이션 작업)

### 3.4 가중 MAPE 정의

```
weighted_mape = sum(|pred - actual|) / sum(actual)
```

큰 금액 케이스의 오차가 더 영향 — outlier(작은 금액 +200%)에 둔감. **Accuracy.jsx에 이미 표시 슬롯 있음**.

### 3.5 Outlier 식별

같은 공종 내 |error_pct|가 (median + 2×IQR) 초과 케이스를 outlier로 분리:
```
outliers = [e for e in errors if abs(e) > median + 2 * IQR]
```

UI에 별도 표 — "데이터 점검 필요한 케이스".

---

## 4. API 설계

### 4.1 `/api/accuracy` 응답 확장

**현재:**
```json
{
  "model_version": "...",
  "overall_with_area": { mae_pct, median_abs_error_pct, ... },
  "overall_without_area": { ... },
  "by_module": [...],
  "samples": [...],
  "unit_price_confidence": {...}
}
```

**추가 필드:**
```json
{
  ...,
  "overall_with_area": {
    ...,
    "weighted_mape_pct": 18.5,        // NEW
    "actual_sum": 1234567000           // NEW
  },
  "component_accuracy": [               // NEW (v9 모델용)
    { component: "area", sample_count, mae_pct, median_abs_error_pct, weighted_mape_pct, max_pct }
  ],
  "work_code_accuracy": [               // NEW (v2.0-bim 모델용)
    {
      work_code, work_name_ko, category, definition_unit,
      sample_count,
      mae_pct, median_abs_error_pct, weighted_mape_pct, max_pct,
      actual_sum, predicted_sum,
      priority_score
    }
  ],
  "work_code_outliers": [               // NEW
    {
      project_code, work_code, actual, predicted, error_pct
    }
  ],
  "cost_type_accuracy": [               // NEW
    { cost_type, sample_count, mae_pct, weighted_mape_pct, actual_sum }
  ],
  "material_accuracy": []               // Phase 2 (현재 빈 배열)
}
```

### 4.2 신규 헬퍼 함수 (compute side)

```python
def workcode_accuracy(c: sqlite3.Connection, model_version: str) -> list[dict]:
    """공종별 actual vs predicted breakdown 매칭 → MAPE/weighted MAPE 산출"""
    # 1. v2.0-bim breakdown JSON 파싱
    # 2. project_id × work_code 집계
    # 3. actual_costs와 work_code 정규화 후 join
    # 4. per work_code MAPE 산출
    ...

def cost_type_accuracy(c: sqlite3.Connection) -> list[dict]:
    """source_ref 단위 매칭 — actual은 직접, predicted는 evidence_estimate 패턴"""
    ...

def workcode_outliers(c: sqlite3.Connection, threshold_iqr: float = 2.0) -> list[dict]:
    """공종 내 IQR 기반 outlier 식별"""
    ...
```

---

## 5. UI 노출 (Accuracy.jsx 기준)

### 5.1 이미 화면에 슬롯 있음 (`Accuracy.jsx` 수정본)
- v9 컴포넌트별 오차: `component_accuracy`
- 공정별 오차 병목: `work_code_accuracy`
- Outlier: `work_code_outliers`

→ **백엔드 endpoint만 추가하면 화면 즉시 채워짐**.

### 5.2 추가 권장 (이번 기획)

**공정별 표 컬럼 (우선순위):**
| 공정 | 샘플 | MAPE | 가중 MAPE | 중앙값 APE | 실원가 합 | 예측 합 | priority |
|---|---|---|---|---|---|---|---|

**필터:**
- 모델 버전 (v2.0-bim / v9.0-hybrid-ridge)
- 비용유형 (전체 / 재료비 / 노무비 / 경비)

**시각화:**
- 공정별 막대그래프 (가중 MAPE × 실원가 = 임팩트)
- "비전 90% 목표 라인" overlay

---

## 6. 단계별 실행 계획

### Phase 1 (즉시, 1~2일)
1. ✅ 데이터 진단 (이 문서)
2. `/api/accuracy`에 `work_code_accuracy`, `component_accuracy`, `work_code_outliers`, `cost_type_accuracy` 추가
3. `weighted_mape_pct`, `actual_sum`을 `overall_with_area`/`overall_without_area`에 추가
4. 새 IFC 9개로 `compute_analytics --step 4 --step 5` 재실행 후 측정
5. 화면 검증 (현재 `Accuracy.jsx` 기대 필드 모두 채워짐)

### Phase 2 (자재 보강, 1주)
1. `migrate_notion.py` 또는 `import_procure.py` 보강 — 자재명/수량/단가 파싱
2. 자재명 → `materials.canonical_name` fuzzy 매핑 (sequence matcher)
3. `actual_costs.material_id`, `actual_quantity`, `unit_price` 채우기
4. `material_accuracy` 산출 활성화

### Phase 3 (BIM 보강, 외부 의존)
1. BIM 팀에 누락된 4개 모듈(S-18, U-6-1, 농어촌, T-10-SHW) IFC export 요청
2. 받자마자 audit → import → 정확도 자동 갱신

### Phase 4 (모델 재학습, 30분)
1. `ml_pipeline.py` 실행 — 새 BIM 데이터로 v9.0 ML 모델 재학습
2. `/api/accuracy`로 v2.0 vs v9.0 비교

---

## 7. 예상 결과 (가설)

새 IFC 9개 + Phase 1 적용 시:

| 공정 | 예상 MAPE | 신뢰도 |
|---|---|---|
| STR-ST 철골공사 | 10~15% | 높음 (BIM 정확) |
| FIN-LGS 경량철골 | 10~20% | 높음 |
| EXT-WIN 창호 | 15~25% | 중간 (CV 29%) |
| FIN-PANEL | 25~40% | 중간 (level 정규화 영향) |
| FUR | 50%+ | 낮음 (CV 116%) |
| MEP-ELEC | 40~50% | 중간 (LS 환산 추정) |

→ **80% 이상의 실원가가 ±25% 이내** 가능성. 단 FUR/MEP 두 영역은 별도 보강 작업 필요 (자재 단가 다양성).

---

## 8. 데이터 정제 필요 항목 (액션 아이템)

| 항목 | 현 상태 | 필요 조치 |
|---|---|---|
| `actual_costs.material_id` | 0% | Notion ETL 보강 |
| `actual_costs.actual_quantity` | 0% | Notion ETL 보강 |
| FIN-PANEL level 정규화 | BIM=001 / actual=PANEL | 비교 시 자동 정규화 (현 normalized() 함수 재사용) |
| BIM 미공급 모듈 4개 | (S-18, U-6-1, 농어촌, T-10-SHW) | BIM팀 export 요청 |
| FUR 정의 unit | NULL | work_codes에 'EA' 명시 |
| 매뉴얼 link review pending 3개 | (밀양/청주 미원/서산 신규) | 사용자 검토 |

---

## 9. 측정 한계 / 주의사항

1. **샘플 부족** — IFC 9개 × 단일 모듈 = 통계적 신뢰성 한계. 평균보다 중앙값/IQR 사용 권장.
2. **work_code 정규화 일관성** — actual은 level 2 위주, BIM/예측은 mixed. 매번 정규화 거쳐야 함.
3. **NOTION m² 단가 의존** — 자동 보정에 NOTION을 ground truth로 쓰는데, NOTION은 모듈 면적 기반 평균이라 실제 m² 청구 단가와 다를 수 있음 (이미 인지된 한계).
4. **outlier 정의** — IQR × 2 가 단순한 통계 룰. 공정마다 적정 threshold가 다를 수 있음 — 도메인 검토 필요.

---

## 10. 다음 단계 결정 포인트

이 기획대로 진행하려면 사용자 확인 필요:

- [ ] Phase 1 (백엔드 + 공종별 MAPE) 진행 — 즉시 시작 가능
- [ ] 자재 단위 측정을 위한 Notion ETL 보강이 가치 있는지 — 작업량 큼
- [ ] BIM팀에 누락 4개 모듈 export 요청 (외부 의존)
- [ ] ML 모델 재학습 (`ml_pipeline.py`) — 가장 빠른 정확도 개선
