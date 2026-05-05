# 공종별 오차율 감소 — 종합 로드맵

작성일: 2026-05-05
관련 문서: [`WORKCODE_MATERIAL_MAPE_PLAN.md`](./WORKCODE_MATERIAL_MAPE_PLAN.md) (측정 방법론)

---

## 0. 목표 정의

| 지표 | 현재 | 단기(1주) | 중기(1달) | 장기 |
|---|---|---|---|---|
| **공종별 가중 MAPE** (5대 공종) | 측정 미구현 | ≤ 25% | ≤ 15% | ≤ 10% |
| ±20% 이내 케이스 비율 | 38% | 60% | 80% | 90% |
| BIM 단가 평균 신뢰도 | 0.81 | 0.85 | 0.90 | 0.95 |
| 자재별 측정 가능 % | 0% | 0% | 30% | 70% |
| BIM 커버 IFC 비율 | 56% (5/9 모듈) | 56% | 100% | 100% |

> "공종별 오차율 ≤ 10%"가 비전 문서의 "90% 정확도 시스템"에 직접 매핑.

---

## 1. 현재 시스템 갭 종합 (4 트랙으로 분류)

### A. 데이터 모델 / 정제 갭
| # | 항목 | 현 상태 | 영향도 |
|---|---|---|---|
| A1 | `actual_costs.material_id` | 0% (전부 NULL) | 🔴 자재 단위 측정 차단 |
| A2 | `actual_costs.actual_quantity` | 0% (전부 NULL) | 🔴 단가 검증 차단 |
| A3 | `actual_costs.unit_price` | 0% (전부 NULL) | 🔴 시장가 비교 차단 |
| A4 | `module_types` 오염 | IFC- 자동생성 7개 | 🟡 정확도 측정 노이즈 |
| A5 | `loss_factors` 모두 1.0 | 보정 미작동 | 🟡 BIM↔실투입 갭 미반영 |
| A6 | `unit_prices` source 단일성 | NOTION 평균만 | 🟡 모듈 등급별 분리 안 됨 |
| A7 | `cost_types` 표준화 | `source_ref` 문자열 | 🟢 별도 테이블 부재 (큰 문제 아님) |
| A8 | work_code 정규화 | level 1↔2↔3 혼재 | 🟡 매핑 누락 위험 |

### B. BIM 매핑 갭
| # | 항목 | 현 상태 | 영향도 |
|---|---|---|---|
| B1 | `IFC_WORK_MAP` 커버리지 | 18 IFC type | 🟡 FIN-CARP/EXT-CLAD/MEP-PLMB 등 누락 |
| B2 | BIM unit과 정의 unit 불일치 | FIN-PANEL m³ ≠ m², STR-ST m³ ≠ ton | 🟡 환산계수 의존 |
| B3 | level 정규화 | BIM=FIN-PANEL-001 / actual=FIN-PANEL → join 안 됨 | 🔴 actual 205M이 BIM 0건으로 잡힘 |
| B4 | 자재 밀도 (Mass Density) | 미설정 | 🟡 Volume → ton 환산 정확도 |
| B5 | BIM 미공급 모듈 4개 | S-18, U-6-1, 농어촌, T-10-SHW | 🟡 모듈별 측정 불가 |
| B6 | FUR (가구) IFC 추출 | EA만 (벽장/주방 다양성 없음) | 🟢 모듈러 한계 |

### C. 예측 모델 갭
| # | 항목 | 현 상태 | 영향도 |
|---|---|---|---|
| C1 | 공종별 학습 모델 | **없음** — v2.0은 룰, v9.0은 area/option/site | 🔴 공종 단위 보정 불가 |
| C2 | v9.0 breakdown 공종 단위 분해 | area/option/site만 (4 컴포넌트) | 🟡 공종별 backtest 불가 |
| C3 | 신뢰구간 per work_code | 없음 (전체만) | 🟢 사용자 신뢰성 시그널 부재 |
| C4 | 모델 ensemble weighting | 단순 평균 | 🟡 공종별 최적 모델 분리 불가 |
| C5 | 외부 시장단가 ground truth | 없음 | 🟢 NOTION m²만 의존 |
| C6 | 사용자 피드백 loop | 없음 | 🟡 발주 결과 → 학습 미반영 |

### D. 결과/검증 갭
| # | 항목 | 현 상태 | 영향도 |
|---|---|---|---|
| D1 | 공종별 MAPE API | 없음 (Accuracy.jsx는 슬롯만) | 🔴 측정 자체 미공급 |
| D2 | Outlier 자동 탐지 | 없음 | 🟡 데이터 정제 큐 미생성 |
| D3 | 정확도 추이 (시계열) | 없음 | 🟢 개선 효과 가시화 X |
| D4 | 견적 화면 공종별 신뢰구간 | 없음 | 🟡 사용자가 어디 보강할지 모름 |
| D5 | 자동 backtest | 수동 | 🟡 IFC 추가 시 자동 갱신 X |
| D6 | 정확도 리포트 export | 없음 | 🟢 외부 보고서 어려움 |

---

## 2. 우선순위 매트릭스

각 항목을 **임팩트 × 노력**으로 매핑 (10점 척도).

| 항목 | 임팩트 | 노력 | 점수(임팩트/노력) | 트랙 |
|---|---|---|---|---|
| D1 공종별 MAPE API | 9 | 2 | **4.5** | 즉시 |
| B3 work_code level 정규화 강화 | 9 | 2 | **4.5** | 즉시 |
| C2 v9 breakdown 공종 단위 추가 | 8 | 3 | **2.7** | 1순위 |
| A4 module_types 정리 | 5 | 2 | **2.5** | 1순위 |
| B1 IFC_WORK_MAP 확장 | 7 | 3 | **2.3** | 2순위 |
| D4 견적 화면 공종 신뢰구간 | 7 | 3 | **2.3** | 2순위 |
| C1 공종별 학습 모델 신설 | 9 | 5 | 1.8 | 3순위 (큰 작업) |
| A1~A3 actual_costs 자재 보강 | 8 | 6 | 1.3 | 3순위 (Notion ETL) |
| A5 loss_factor 진짜 산출 | 7 | 4 | 1.8 | 3순위 |
| B5 BIM 미공급 4개 모듈 | 6 | (외부) | — | 외부 의존 |
| B4 Mass Density 매개변수 | 5 | (외부) | — | 외부 의존 |

→ **즉시(1주) 작업 4개 + 1순위(2주) 4개 + 3순위(1달+)**.

---

## 3. 단계별 실행 계획

### Phase 0 (오늘) — 측정 인프라 (이미 분석됨)
- [x] 데이터 진단 완료 (이 문서)
- [x] 새 IFC 9개 import (BIM 정확)
- [x] 기존 변환계수 calibration

### Phase 1 (1~2일) — 측정 자체를 켠다 ⭐ 즉시
**목적**: "어디가 부정확한지" 알 수 있게.

| 작업 | 결과물 |
|---|---|
| D1 + B3: `/api/accuracy` 확장 (공종별 MAPE) | `work_code_accuracy[]` 응답, `Accuracy.jsx` 자동 채워짐 |
| D2: Outlier 자동 탐지 (IQR × 2) | `work_code_outliers[]` |
| 비용유형별 MAPE | `cost_type_accuracy[]` (재료비/노무비/경비) |
| 가중 MAPE 추가 | `weighted_mape_pct` per work_code |

**검증 메트릭**:
- 5대 공종별 MAPE 표 화면 출력
- outlier 케이스 수 보고
- 가중 MAPE vs 단순 MAPE 격차 (>5%면 outlier 영향 큼)

### Phase 2 (3~5일) — 데이터 품질 보강 ⭐ 1순위
**목적**: 모델이 정확하려면 입력 데이터가 정확해야.

| 작업 | 결과물 |
|---|---|
| A4: `module_types` 정리 — IFC- 접두 자동 생성 행 통합 | 14개 → 8개로 정상화 |
| B1: `IFC_WORK_MAP` 확장 — 12개 미커버 공종 추가 | FIN-CARP, EXT-CLAD 등 BIM 매칭 |
| B3: work_code 정규화 일관화 | 모든 join 시 normalized() 거치도록 코드 단일화 |
| A5: `loss_factors` 산출 로직 검토 | sample 수 부족 시 모듈 등급 평균 fallback |
| C2: v9 breakdown에 공종별 amount 추가 | `cost_predictions.breakdown.work_codes[]` |

**검증 메트릭**:
- FIN-PANEL의 BIM 매칭 0건 → 100건+로 증가
- IFC_WORK_MAP 커버리지 95%+
- 공종별 v9 backtest 가능

### Phase 3 (1~2주) — 공종별 신뢰구간 + 화면 ⭐ 2순위
**목적**: 사용자가 "이 견적의 어디가 위험한지" 본다.

| 작업 | 결과물 |
|---|---|
| 공종별 confidence interval 산출 (IQR 기반) | predicted ± lower/upper per work_code |
| 견적 화면 컬럼 추가: 공종별 신뢰구간 | `EvidenceEstimate.jsx`, `QuickEstimate.jsx` |
| 공종 우선순위 점수 = MAPE × actual_sum | "여기 보강하면 임팩트 큼" 표시 |
| BoQ Excel에 공종별 신뢰구간 컬럼 | xlsx export 보강 |

**검증 메트릭**:
- 견적 결과 화면에 공종별 ±X% 표시
- 사용자가 ConversionFactors에서 multiplier 조정 → 신뢰구간 즉시 반영

### Phase 4 (2~4주) — 공종별 학습 모델 ⭐ 3순위 (가장 큰 작업)
**목적**: 룰베이스를 넘어 ML로 공종별 오차 줄이기.

| 작업 | 결과물 |
|---|---|
| `ml_pipeline.py` 확장 — 공종별 KNN/Ridge 모델 | per-workcode 예측기 (5개 핵심 공종) |
| 입력 feature: 모듈 면적/평형/등급, BIM 정량(m²/m³), 자재 spec | per-prediction confidence |
| Cross-validation (LOO per workcode) | 정확한 backtest 점수 |
| Ensemble: 공종별로 다른 모델 가중치 | v10.0-workcode-aware |

**필요 데이터:**
- 공종별 sample n ≥ 5 (BIM 커버 모듈 확장 후 가능)
- IFC 추가 기다리는 게 좋음

### Phase 5 (1달+) — 자재 단위 측정 ⭐ 3순위 (Notion ETL 보강)
**목적**: 자재 단위로 시장가 비교, 자재별 정확도 산출.

| 작업 | 결과물 |
|---|---|
| `migrate_notion.py` 보강 — Notion 발주 raw에서 자재명·수량·단가 파싱 | `actual_costs.material_id, actual_quantity, unit_price` 채움 |
| 자재명 fuzzy 매칭 → `materials` 테이블 | 매칭 % 보고 |
| `material_accuracy` API 활성화 | 자재별 MAPE, 시장가 비교 |
| 외부 시장단가 카탈로그 import (선택) | benchmark 비교 |

**난이도:** 큰 작업. Notion 데이터 schema에 따라 작업량 변동.

### Phase 6 (외부 의존) — BIM 보강
| 작업 | 책임 |
|---|---|
| BIM 미공급 4개 모듈 (S-18, U-6-1, 농어촌, T-10-SHW) IFC export | BIM 팀 |
| Material Mass Density 입력 (강재 7,850 kg/m³ 등) | BIM 팀 |
| 받자마자 `audit_ifc_quantities.py` → import → 정확도 자동 갱신 | 자동화 |

---

## 4. 상세 설계 — 핵심 작업

### 4.1 D1+B3: 공종별 MAPE API (Phase 1, 즉시)

**핵심 함수:**
```python
def workcode_accuracy(c, model_version: str) -> list[dict]:
    """모델별 breakdown × actual_costs 매칭."""
    norm = workcode_normalize_map(c)  # work_code_id → normalized level-2 code

    # actual: project × normalized_workcode → amount
    actual = defaultdict(lambda: defaultdict(int))
    for r in c.execute("""
        SELECT project_id, work_code_id, SUM(total_amount) amt
        FROM actual_costs WHERE total_amount > 0
        GROUP BY project_id, work_code_id
    """):
        nwc = norm[r["work_code_id"]]
        actual[r["project_id"]][nwc] += r["amt"]

    # predicted: project × normalized_workcode → amount (from breakdown JSON)
    predicted = defaultdict(lambda: defaultdict(int))
    for r in c.execute("""
        SELECT project_id, breakdown FROM cost_predictions
        WHERE model_version=? AND breakdown IS NOT NULL
    """, (model_version,)):
        bd = json.loads(r["breakdown"])
        if isinstance(bd, list):
            for item in bd:
                wc = item.get("work_code")
                if not wc: continue
                # 정규화: normalize_workcode_string(wc) — level-2로
                nwc = normalize_workcode_str(wc, norm)
                predicted[r["project_id"]][nwc] += int(item.get("amount") or 0)

    # per work_code 집계
    per_wc = defaultdict(lambda: {"errors": [], "actual_sum": 0, "predicted_sum": 0, "abs_diff_sum": 0})
    for proj_id, wc_actuals in actual.items():
        for wc, a in wc_actuals.items():
            p = predicted[proj_id].get(wc, 0)
            if a > 0:
                per_wc[wc]["errors"].append(abs(p - a) / a)
                per_wc[wc]["actual_sum"] += a
                per_wc[wc]["predicted_sum"] += p
                per_wc[wc]["abs_diff_sum"] += abs(p - a)

    # 산출
    result = []
    for wc, d in per_wc.items():
        n = len(d["errors"])
        if n == 0: continue
        errs = sorted(d["errors"])
        result.append({
            "work_code": wc,
            "sample_count": n,
            "mae_pct": round(sum(errs) / n * 100, 1),
            "median_abs_error_pct": round(errs[n // 2] * 100, 1),
            "weighted_mape_pct": round(d["abs_diff_sum"] / d["actual_sum"] * 100, 1) if d["actual_sum"] else None,
            "max_pct": round(max(errs) * 100, 1),
            "actual_sum": d["actual_sum"],
            "predicted_sum": d["predicted_sum"],
            "priority_score": round(sum(errs) / n * d["actual_sum"]),
        })
    return sorted(result, key=lambda x: -x["priority_score"])
```

**예상 출력 (5대 공종):**
```json
[
  {"work_code": "STR-ST", "sample_count": 9, "mae_pct": 18.5, "weighted_mape_pct": 14.2, "actual_sum": 313000000, "priority_score": 57905000},
  {"work_code": "FIN-PANEL", "sample_count": 9, "mae_pct": 25.0, ..., "priority_score": 51250000},
  ...
]
```

### 4.2 B1: IFC_WORK_MAP 확장 (Phase 2)

**현재 누락 공종 (actual은 있지만 BIM 매칭 0):**

| work_code | 실원가 | 누락 IFC type 후보 |
|---|---|---|
| FIN-CARP 목공사 | 89M | IfcStair, IfcRailing, IfcColumn (목구조) |
| EXT-CLAD 외장재 | 82M | IfcCurtainWall, IfcCovering(외부) |
| FUR-BATH 욕실 | 24M | IfcSanitaryTerminal |
| FIN-FLOOR 바닥마감 | 18M | IfcCovering(바닥) — Material로 분기 |
| FUR-DOOR 실내문 | 16M | IfcDoor (이미 있지만 -001 vs 비-001 분기 검토) |
| FIN-TILE 타일 | 16M | IfcCovering(욕실/주방) |
| EXT-DECK 외부 데크 | 10M | IfcSlab(외부 marker) |
| MEP-PLMB 배관 | 9M | IfcPipeSegment(이미 있음 — extraction 안 되는 이유 점검) |
| MEP-HVAC 공조 | 8M | IfcDuctSegment (이미 있음) |
| EXT-ROOF 지붕 | 3M | IfcRoof, IfcSlab(roof marker) |

**개선 방향:**
- IFC type만으로 부족 — Material name·ObjectType·Pset_*로 보조 분기
- 예: `IfcCovering` + Material "타일" → FIN-TILE / Material "단열재" → FIN-INS
- 새 매핑 함수 `classify_bim_element(elem)` 도입

### 4.3 C1: 공종별 학습 모델 (Phase 4, 가장 큰 작업)

**구조:**
```
공종별 모델 ensemble:
  STR-ST   → KNN (BIM volume m³ + 모듈 면적 + 등급)
  FIN-PANEL → Ridge (BIM volume + 면적)
  FIN-LGS  → Ridge
  EXT-WIN  → KNN (BIM area + 개수)
  FUR     → 모듈 등급별 평균 (sample 부족 → 통계 기반)
  MEP-ELEC → Power-law (모듈 면적의 0.7제곱 ≈ LS 추정)
  
공종 외 항목 (SITE, FIN-CARP 등):
  → 면적 기반 fallback (현 v9.0과 동일)
```

**Cross-validation 전략:**
- LOO per work_code (현재 IFC 9개로는 매우 빠른 학습)
- 예: STR-ST 측정 시 9개 IFC 중 1개 제외하고 8개로 학습 → 1개 검증, 9회 반복

**출력:**
- per-prediction `confidence_lower`, `confidence_upper` per work_code
- `Accuracy.jsx`에 v10.0 컬럼 추가

### 4.4 A4: module_types 정리 (Phase 2)

**문제:** 9개 IFC import 시 매핑 안 된 IFC 7개가 자동 `IFC-...` 모듈을 생성. backtest 노이즈.

**조치:**
1. 사용자 확인 후 IFC- 접두 모듈을 정상 모듈에 통합
2. `parse_ifc_all.py`의 `FILE_META` 키워드 매핑 보강 (현재 9개 키워드 → 모든 IFC 매핑되도록)
3. 매핑 안 되는 신규 IFC는 `module_type_id=NULL`로 두고 admin에게 알림

**FILE_META 보강 예시:**
```python
"화성시 비봉면 쌍학리": {"project_code": "N-20-경기-화성시-쌍학리-667", "module_code": "S-18-2025", ...},
"성남시 수정구 상적동": {"project_code": "N-19-T-12", "module_code": "T-12-2025", ...},
"제주 안덕면 서광리": {"project_code": "N-09-H-30", "module_code": "H-30-2025", ...},
"추부면 마전리": {"project_code": "N-18-T-12", "module_code": "T-12-2025", ...},
"청주-남이면-가마리": {"project_code": "N-22-NEW", "module_code": "T-9-STD", ...},
```

---

## 5. 의존 관계 그래프

```
Phase 1 (D1, B3 일부)
    ↓
Phase 2 (B1, B3 완성, A4, A5, C2)
    ↓
Phase 3 (C3, D4)        Phase 5 (A1~A3 자재 보강) ─┐
    ↓                                            │
Phase 4 (C1 공종별 ML 모델) ←────────────────────┘
    ↓
Phase 6 (BIM 외부 의존, 가장 큰 정확도 향상)
```

**병렬 가능:** Phase 1과 A4, Phase 5 시작은 같이 진행 가능.

---

## 6. 체크포인트와 측정 지표

각 Phase 종료 시 자동 측정:

| 체크포인트 | 측정 대상 | 통과 기준 |
|---|---|---|
| Phase 1 종료 | 화면에 공종별 MAPE 노출 | 5대 공종 모두 표시 |
| Phase 2 종료 | FIN-PANEL BIM 매칭 | 0건 → 100+건 |
| Phase 2 종료 | IFC_WORK_MAP 커버리지 | 80% → 95% |
| Phase 3 종료 | 견적 화면 공종 신뢰구간 | 모든 공종에 ±X% 표시 |
| Phase 4 종료 | v10.0 가중 MAPE | v2.0 대비 50% 감소 |
| Phase 5 종료 | 자재별 측정 sample | 0건 → 200건+ |

각 단계마다 자동 backtest 스크립트가 결과를 비교 표로 출력.

---

## 7. 리스크 및 완화

| 리스크 | 가능성 | 영향 | 완화 방법 |
|---|---|---|---|
| IFC 9개로는 통계적 신뢰성 한계 | 높음 | 큼 | 중앙값/IQR 기반 보고. 평균만으로 결론 짓지 않음 |
| Notion ETL 보강 시 raw schema 변동 | 중간 | 큼 | 보강 전 schema dump → 변경 감지 hook |
| 공종별 ML 모델 overfitting | 중간 | 중간 | LOO + 단순 모델(Ridge) 우선 |
| BIM 미공급 모듈 무한 대기 | 높음 | 중간 | 모듈 4개 우선순위 표 작성 후 BIM팀 협의 |
| level 정규화 버그 누락 | 중간 | 큼 | 정규화 함수 단일 진입점 + 단위 테스트 |

---

## 8. 즉시 실행 가능한 첫 작업 (1~2일 예상)

**Phase 1만 단독 실행해도 즉각적인 가치:**

1. `/api/accuracy` 백엔드 확장 (workcode_accuracy + outliers + cost_type)
2. work_code 정규화 헬퍼 단일 진입점 (`normalize_workcode_id` 또는 `_str`)
3. `Accuracy.jsx`는 이미 슬롯 있음 — 백엔드만 업데이트
4. 새 IFC 데이터로 즉시 backtest → 공종별 MAPE 측정값 보고
5. 우선순위 점수 기반 "어디부터 보강해야 할지" 자동 추천

→ **이게 끝나면 의사결정의 근거가 생김 — 그 후 Phase 2~6 우선순위를 데이터 기반으로 결정.**

---

## 9. 다음 결정 포인트

이 로드맵으로 진행하려면:
- [ ] Phase 1 즉시 시작 — 측정 인프라 (1~2일)
- [ ] Phase 2 동시 시작 가능한지 (data fix는 Phase 1 결과 보고 결정)
- [ ] Phase 5 (Notion ETL 보강) 우선순위 — 자재 측정이 비전 핵심인가?
- [ ] BIM 팀 협의 일정 — 미공급 모듈 4개 export 요청
- [ ] ML 모델 재학습 (`ml_pipeline.py` 한 번 돌려서 v9.0 갱신)
