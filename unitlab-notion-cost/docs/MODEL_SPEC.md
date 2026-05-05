# v10.0-notion 모델 설계

## 1. 입력

```python
EstimateRequest = {
  "modules": [
    { "module_code": "T-15-STD", "quantity": 1 },
    ...
  ]
}
```

또는 이름이 없는 자유 입력:
```python
{ "floor_area_m2": 49.6, "pyeong": 15, "grade": "ESSENTIAL" }
```

## 2. 학습 데이터 추출

```sql
SELECT
  ac.project_id,
  ac.work_code_id,
  ac.source_ref AS cost_type,
  SUM(ac.total_amount) AS amount,
  mt.module_type_id,
  mt.module_code,
  mt.floor_area_m2,
  mt.pyeong,
  mt.finish_grade,
  mt.structure_type
FROM actual_costs ac
JOIN projects p          ON ac.project_id     = p.project_id
JOIN project_modules pm  ON p.project_id      = pm.project_id
JOIN module_types mt     ON pm.module_type_id = mt.module_type_id
WHERE ac.total_amount > 0
GROUP BY ac.project_id, ac.work_code_id, ac.source_ref
```

`work_code`는 항상 **level 2로 정규화**한다 (level-3 leaf → 부모 level-2).

## 3. 비율 학습 — 공종 × 비용유형 × 모듈 메타

각 train sample은 `(work_code, cost_type, project_id)` 단위:

```
sample = {
  work_code:    "STR-ST",
  cost_type:    "재료비",
  project_id:   N-01-T-15,
  amount:       38_421_000,
  area_m2:      49.6,
  pyeong:       15,
  grade:        "ESSENTIAL",
  rate_per_m2:  amount / area_m2 = 774_617
}
```

## 4. 예측 산식 (per work_code × cost_type)

```python
def predict_rate(work_code, cost_type, target_grade, target_pyeong, target_area):
    pool = all_samples.filter(work_code, cost_type)

    # 유사도 weighting (priority order):
    #   1. 같은 grade  AND  pyeong 차이 ≤ 3
    #   2. 같은 grade
    #   3. pyeong 차이 ≤ 5
    #   4. 전체

    tiers = [
        [s for s in pool if s.grade == target_grade and abs(s.pyeong - target_pyeong) <= 3],
        [s for s in pool if s.grade == target_grade],
        [s for s in pool if abs(s.pyeong - target_pyeong) <= 5],
        pool,
    ]
    chosen = next((t for t in tiers if len(t) >= 2), pool)

    rates = sorted(s.rate_per_m2 for s in chosen)
    n = len(rates)
    median_rate = rates[n // 2]
    iqr_lower   = rates[n // 4]
    iqr_upper   = rates[(3 * n) // 4]

    return {
        "rate_per_m2":   median_rate,
        "amount":        median_rate * target_area,
        "lower":         iqr_lower * target_area,
        "upper":         iqr_upper * target_area,
        "sample_count":  n,
        "tier_used":     index_of_chosen,
        "source_cases":  [s.project_id for s in chosen],
        "confidence":    confidence_score(n, iqr_upper / median_rate),
    }
```

`confidence_score`:
```
sample_term = min(1.0, n / 8)         # 8 sample 이상이면 만점
spread_term = max(0, 1 - (iqr_upper - iqr_lower) / median_rate)
confidence  = round(0.5 * sample_term + 0.5 * spread_term, 2)
```

## 5. 출력 형식 (cost_predictions.breakdown 호환)

```json
{
  "model_version":  "v10.0-notion",
  "module_codes":   ["T-15-STD"],
  "total_area_m2":  49.6,
  "total":          152_300_000,
  "confidence_lower": 138_400_000,
  "confidence_upper": 168_900_000,
  "breakdown": [
    {
      "work_code":    "STR-ST",
      "work_name":    "철골공사",
      "cost_type":    "재료비",
      "amount":       12_540_000,
      "rate_per_m2":  252_823,
      "lower":        11_120_000,
      "upper":        14_200_000,
      "sample_count": 7,
      "tier_used":    "same_grade_close_pyeong",
      "confidence":   0.86,
      "source_cases": ["N-01-T-15", "N-13-T-15-3", ...]
    },
    ...
  ],
  "missing_workcodes": ["FUR-BATH"],   // 학습 sample 부족
  "warnings": []
}
```

## 6. 학습/예측 호출 흐름

```
[CLI / API]
   ↓
notion_cost_model.train()    → in-memory pool (공종·유형별 rate 분포)
notion_cost_model.predict()   → breakdown
   ↓
저장: cost_predictions(model_version='v10.0-notion', breakdown=JSON)
```

## 7. Leave-One-Out 검증 (backtest.py)

```python
for held_out_project in all_projects:
    train_pool = pool.exclude(project_id == held_out_project)
    target = held_out_project.module_meta
    pred = predict(target, pool=train_pool)
    actual = held_out_project.actual_total
    record(held_out_project, pred, actual)

# 출력:
total_mape          = mean(|pred - actual| / actual)
per_workcode_mape   = group by work_code, same metric
per_cost_type_mape  = group by cost_type
weighted_mape       = sum(|pred-actual|) / sum(actual)
```

## 8. 비전 vs 한계

**v10.0-notion이 잘 하는 것**:
- 공종별 평당 단가 (재료비/노무비/경비 분리)
- 같은 등급/평형 사례 가중
- 신뢰구간 per 공종
- IFC 변동성 영향 0%

**v10.0-notion이 못 하는 것**:
- 같은 모듈 내에서 자재 spec 차이 보정 (예: 같은 T-15 모듈에 일반판넬 vs 고급판넬)
- 단일 모듈에 옵션 추가/제거 (창호 1개 추가 같은 미시 변경)
- 자재 단위 단가 (`actual_costs.material_id`가 비어있어 측정 불가)

→ 이런 미시 변동 보정은 **나중에 IFC 데이터를 옵션으로 붙일 때** 해결.
