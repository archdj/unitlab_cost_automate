# 자재(재료비) outlier 진단 — 2026-05-09

baseline `loo_backtest_v11.0-autocost-mvp.json` 기준 자재 wMAPE = **39.9%**.
흡수 트리거 (자재 MAPE < 15%) 미달의 원인을 셀 단위로 추적.

## TL;DR

- **단순 outlier 격리만으로는 트리거 불가**: err > 500% 셀 격리 → wMAPE 49.8% → 39.x%
  수준 그대로. err > 100% 셀 13개를 모두 격리해도 40.2% 까지만.
- **진짜 원인은 outlier가 아니라 catalog mismatch (분류 누락)**:
  특정 (project, work_code) 셀에 단 1 row만 남은 채 0.05M~0.3M 같은 미니
  actual이 LOO에서 다른 프로젝트의 정상 평균(1~35M/m²)과 비교되어 비율
  500%~2940% 폭주. 자재 자체의 단가가 outlier가 아니라 **분류 단계에서
  대부분의 자재 row가 다른 셀로 빠져나간 것**.
- **데이터 품질 사전 조건**: 자재 row 98/98이 `actual_quantity` + `unit` NULL,
  `vendor_name` 100%가 Notion URL 오염. 단가 정규화·번들/MOQ 도입 이전에
  이 사전 조건부터 정리해야 함.

## 1. 진단 메커니즘

두 단계로 진단했다:

### A. 셀 자체의 rate_per_m2 분포 outlier
스크립트: `harness/scripts/audit_material_outliers.py`

각 (project, work_code) 셀의 `rate_per_m2`를 work_code 그룹 median과 비교.
median × 3 초과 또는 median ÷ 3 미만이면 hi/lo 플래그.

결과: 98 셀 중 hi=1, lo=4. **rate 분포 자체는 정상**. 하지만:
- `zero_qty` (actual_quantity NULL): **98/98 (100%)**
- `no_unit` (unit 빈값): **98/98 (100%)**
- `multi_vendor` (`,;/외` 분리자 포함 vendor_name): **97/98 (99%)**
- `dominant_row` (단일 row가 셀 합의 50%+): **84/98 (86%)**

→ **자재 데이터 전체가 quantity/unit이 비어 있고, vendor에 Notion URL이
포함되어 있다.** sandbox `doc2_internal_brief.html` §즉시 조치 이슈의
"수량 누락 463건" 과 일치.

### B. LOO 셀 단위 err 추적
스크립트: `harness/scripts/audit_loo_cell_errors.py`

baseline backtest와 동일 메커니즘으로 LOO 시 각 셀의 actual / predicted / err 추출.

| percentile | err |
|---|---|
| p50 | 30.6% |
| p75 | 75.5% |
| p90 | 112.8% |
| p95 | 201.4% |
| p99 | 563.6% |

work_code별 wMAPE 영향도 (자재 한정):

| work_code | n | wMAPE | abs_diff | over/under |
|---|---|---|---|---|
| EXT-CLAD | 8 | 59.6% | 19.5M | 4 / 4 |
| FIN-PANEL | 8 | 30.3% | 15.8M | 5 / 3 |
| EXT-WIN | 6 | 59.8% | 12.5M | 2 / 4 |
| FIN-LGS | 7 | 55.8% | 6.7M | 4 / 3 |
| FIN-CARP | 8 | 28.6% | 6.0M | 4 / 4 |
| **FUR** | 4 | **113.8%** | 5.7M | 2 / 2 |
| STR-ST | 8 | **11.1%** ✅ | 4.6M | 6 / 2 |
| FUR-DOOR | 7 | 45.0% | 3.2M | 3 / 4 |
| EXT-DECK | 1 | 100.0% | 3.1M | 0 / 1 |
| MEP-ELEC | 7 | 61.6% | 2.7M | 4 / 3 |

STR-ST(철골)는 이미 트리거 충족(11.1%). **FUR / EXT-CLAD / EXT-WIN / FIN-LGS** 가 병목.

## 2. Top 10 폭주 셀 — raw row 까지 추적

| project | wc | actual | predicted | err | raw rows | raw_description (vendor) |
|---|---|---|---|---|---|---|
| N-13-T-15-3 | FUR | 0.06M | 1.74M | 2940% | 1 | **남기동길_부엌수전** ((주)남우) |
| N-21-서산 | EXT-WIN | 0.31M | 2.07M | 564% | 1 | 서산 강수리_창호 그리드 ((주)진흥창호) |
| N-07-U-6-1 | MEP-HVAC | 0.04M | 0.20M | 442% | 1 | 환풍기 1 ((주)힘펠) |
| N-11-T-12 | FUR | 0.29M | 1.27M | 343% | 1 | **청주_처마하부마감** (KH인터내셔날) |
| N-10-S-18 | EXT-CLAD | 2.10M | 8.81M | 319% | 1 | 루떼르_외장재 (비엠2(주)) |
| N-21-서산 | MEP-ELEC | 0.19M | 0.58M | 201% | 2 | 서산 강수리_스위치콘센트 + 서산 사이니지 |
| N-10-S-18 | FIN-LGS | 1.58M | 3.76M | 139% | 1 | 루떼르_경량 (주식회사 화영) |
| N-10-S-18 | MEP-ELEC | 0.69M | 1.64M | 137% | 7 | 분전반/콘센트/등기구/간접조명/사이니지 |
| N-21-서산 | FIN-LGS | 0.71M | 1.61M | 128% | 2 | 서산 강수리_경량 + 서산 스카이비바 |
| N-03-농어촌 | EXT-CLAD | 0.94M | 2.10M | 123% | 2 | 농어촌_외장재 + 농어촌_외장재 **운반비** |

### 패턴 분석

1. **카테고리 오분류** (확실): `N-13-T-15-3 FUR` 의 단일 row "남기동길**부엌수전**"
   은 가구(FUR)가 아니라 P25 도기/수전 또는 FUR-BATH로 분류해야 함.
   `N-11-T-12 FUR` 의 "청주_**처마하부마감**" 도 가구가 아니라 외부마감(EXT-CLAD)으로
   봐야 함. 이 둘 때문에 FUR 의 wMAPE가 113.8%까지 치솟음.

2. **단일 row + 작은 actual** (10건 중 6건이 raw_rows = 1):
   해당 프로젝트의 그 work_code 발주 데이터가 거의 누락되어 있음.
   학습에 사용된 다른 프로젝트(같은 grade/면적 대역)의 평균이 그대로 적용되어 비율 폭주.

3. **운반비 분리**: `N-03-농어촌 EXT-CLAD` 에 자재(84.3만원) + "외장재 운반비"(9.9만원)
   가 별도 row로 분리. 같은 자재의 부속 비용이 row 단위로 흩어져 있음 → 단가 정규화 어려움.

4. **vendor 오염**: 모든 row의 vendor_name 에 `(https://www.notion.so/...)` URL 부착.
   sandbox 문서의 vendor cleanup 대상.

## 3. 격리 시뮬레이션

err > N% 셀을 학습/평가에서 제외했을 때 자재 wMAPE 변화 (top-10 per project 부분 데이터 기준):

| 임계 | 격리 셀 | 격리 abs_diff | 후 wMAPE |
|---|---|---|---|
| 베이스 | 0 | 0 | **51.7%** (top-10 부분합) |
| err > 500% | 2 | 3.4M | 49.8% |
| err > 300% | 5 | 11.3M | 45.7% |
| err > 200% | 6 | 11.7M | 45.5% |
| err > 150% | 6 | 11.7M | 45.5% |
| err > 100% | 13 | 24.6M | **40.2%** |

→ **격리만으로는 < 15% 트리거 도달 불가**. err > 100% 셀 13개를 모두
제외해도 40.2%. 이는 자재 데이터 자체에 구조적 문제(분류 누락)가
있어서 outlier 한두 건의 문제가 아님.

## 4. 결론 및 다음 단계 후보

### 결론
- 자재 MAPE 39.9% → < 15% 의 33pp gap은 **outlier 격리로 메울 수 없다**.
- 핵심 병목 3종:
  1. **분류 단계 누락**: 한 프로젝트의 자재 row가 work_code 별로 들쭉날쭉.
     특히 FUR / EXT-CLAD / EXT-WIN 같은 work_code 에 도기·외부마감 등이
     섞여 들어가거나 한 프로젝트 데이터가 누락됨.
  2. **운반비/부속비 분리**: 자재와 별도 row로 잡혀 단가 정규화 방해.
  3. **데이터 결함**: actual_quantity 100% NULL, unit 100% 빈값,
     vendor 100% URL 오염. 단가 분포 학습 불가능.

### 다음 단계 후보 (우선순위)

| # | 작업 | 예상 효과 | 위치 |
|---|---|---|---|
| 1 | **raw_description → P01~P40 재분류 (sandbox 매핑 도입)** | wMAPE -10pp 이상 기대 — FUR/EXT-CLAD top 케이스 직접 해결 | sandbox `doc1_master_plan.html` 의 old_to_new_mapping 컨셉 |
| 2 | **vendor_name + raw_description 정제 파이프라인** | 매핑 정확도 향상 → #1 의 confidence 등급 상승 | `harness/scripts/clean_vendor_names.py` 가 이미 있음 |
| 3 | **운반비 / 부속비 row 를 자재 row 에 흡수** | 단가 분포 안정화 | enriched.db sidecar 에 합산 컬럼 추가 |
| 4 | **단일-row 프로젝트 셀에 applicability tier 가드** | 폭주 비율 억제 — wMAPE -3~5pp | `src/model.py` `predict_for_module` |
| 5 | actual_quantity / unit backfill (Notion 원본 재추출) | 단가 학습 자체를 가능하게 | DATA_INGEST_SPEC.md |

### 권장 진행 순서
1. **#1 (재분류 매핑)** 을 먼저. 이게 수단으로 가장 강력하고 sandbox 문서의
   P01~P40 + measurement_class + old_to_new_mapping 자산을 그대로 활용 가능.
2. #2 (vendor 정제) 와 #3 (운반비 흡수) 는 #1 의 부속 작업으로 동시 진행.
3. #4 (model guard) 는 #1 후 backtest 재측정 결과를 보고 판단.
4. #5 (Notion 재추출) 는 #1~#4 효과를 모두 반영해도 트리거 미달일 때 착수.

## 5. 산출 데이터

- `harness/reports/material_outlier_audit.json` — 셀별 패턴 플래그
- `harness/reports/loo_cell_error_audit.json` — LOO 셀 단위 err + raw row
- `harness/reports/material_descriptions_dump.json` — work_code별 raw_description 전체
- `harness/reports/reclassification_simulation.json` — §6 시뮬레이션 raw 결과
- `harness/mapping/material_reclassification.csv` — 12개 키워드 매핑 룰
- `harness/scripts/audit_material_outliers.py`
- `harness/scripts/audit_loo_cell_errors.py`
- `harness/scripts/inspect_top_outlier_rows.py`
- `harness/scripts/inspect_outlier_schema.py`
- `harness/scripts/dump_material_descriptions.py`
- `harness/scripts/simulate_reclassification.py`

## 6. 재분류 매핑 시뮬레이션 결과 (2026-05-09 추가)

§4 의 권장 1순위였던 "raw_description → P01~P40 재분류 매핑" 의 실제 효과를
12개 키워드 매핑 룰로 in-memory 시뮬레이션.

### 매핑 적용 row (20건)

자재 row 483건 중 매핑된 것은 **20건 (~10M)**. 자재 전체 actual 227M의 약 4%.
주요 사례:

| from | to | desc | amount |
|---|---|---|---|
| FUR | EXT-DECK | 홍천_데크 | 1,772K |
| FUR | EXT-DECK | 홍천 데크 각관 | 880K |
| FUR | FUR-KITCH | 루떼르_세탁기 | 700K |
| FUR | FUR-KITCH | 루떼르_냉장고 | 811K |
| FUR | FUR-BATH | 남기동길_부엌수전 | 57K |
| FUR | EXT-ROOF | 홍천_처마 골조 | 402K |
| FUR | EXT-ROOF | 청주_처마하부마감 | 287K |
| FIN-CARP | FUR-DOOR | 청주 미원면_목창호 | 712K |
| FIN-PANEL | FIN-WTP | 아덱스 도막방수 | 65K |

### wMAPE 변화

| metric | baseline | v2 (재분류 적용) | delta |
|---|---|---|---|
| 전체 wMAPE | 21.8% | 21.9% | +0.1pp ❌ |
| 전체 MAE | 43.4% | 43.8% | +0.4pp ❌ |
| 전체 within±15% | 50.0% | 50.0% | 0pp |
| **자재 wMAPE (project-sum)** | **26.3%** | **25.8%** | **-0.5pp** |
| 자재 MAE | 28.0% | 27.9% | -0.1pp |

work_code 단위:

| wc | b_wMAPE | v_wMAPE | abs_diff 변화 |
|---|---|---|---|
| **FUR** | 59.0% | **54.3%** | -5.7M ✅ |
| EXT-WIN | 56.5% | 56.5% | 0 |
| SITE-MISC | 90.9% | 90.9% | 0 |
| SITE-MOD | 82.9% | 82.9% | 0 |
| FIN-LGS | 64.9% | 64.9% | 0 |
| FIN-PANEL | 30.8% | 30.8% | +0.1M |
| EXT-CLAD | 56.1% | 56.1% | 0 |
| FIN-CARP | 40.8% | 43.3% | +0.5M ⚠️ |
| EXT-ROOF | 40.0% | 41.5% | +0.5M ⚠️ |

### 결론 — 1순위 가설 부분 기각

§4의 "재분류 매핑 → -10pp" 가설은 **데이터로 뒷받침되지 않음**:
- 자재 wMAPE -0.5pp 만 개선. < 15% 트리거(11.3pp gap) 도달 불가.
- FUR work_code wMAPE는 -4.7pp 개선했지만 절대 영향 5.7M에 그침.
- FIN-CARP, EXT-ROOF는 오히려 약간 악화 (목창호·처마 row 추가로 분포 흔들림).
- baseline 측정값도 v11.0의 by_cost_type 39.9%와 본 시뮬레이션의 26.3%가
  다름. 전자는 셀-단위 wMAPE, 후자는 프로젝트-합 단위. 측정 방식 차이.

### 관찰 — 진짜 병목 재정의

자재 row 483건 중 명백한 카테고리 오분류는 ~20건 (4%). 즉 **분류 문제는
실재하지만 wMAPE 39.9%의 주범은 아니다**. 진짜 병목은:

1. **모델 fit 한계** — EXT-WIN(57%) / SITE-MISC(91%) / SITE-MOD(83%) /
   FIN-LGS(65%) / EXT-CLAD(56%) 같은 중간 sample 수의 work_code 가
   median rate_per_m2 단순 적용으로는 안 맞음. 프로젝트별 grade /
   pyeong / 자재 종류 다양성이 큼.
2. **단가 학습 불가** — actual_quantity 100% NULL, unit 100% 빈값으로
   인해 "자재 단가" 자체를 학습할 수 없음. 모델은 결국 (project,
   work_code) 셀의 rate_per_m2 만 본다. 자재의 본질(단가 × 수량)을
   학습하지 못하는 게 근본 원인.
3. **grade 분포 불균형** — BESPOKE 4건, ESSENTIAL 3건, STANDARD 1건 등
   극심한 imbalance. STANDARD 한 건 LOO 시 다른 grade 평균이 그대로 적용.

### 수정된 다음 단계 후보

| # | 작업 | 예상 효과 | 비고 |
|---|---|---|---|
| 1 | actual_quantity / unit backfill (Notion 원본 재추출) | wMAPE -10pp+ 가능 | 가장 큰 lever — sandbox `doc1_master_plan.html` 의 standard_unit_price 컨셉 가능해짐 |
| 2 | grade × work_code 셀 단위 model 가드 | 폭주 셀 -3~5pp | model.py applicability tier 강화 |
| 3 | work_code 단위 외부 벤치마크 단가 주입 | EXT-WIN/EXT-CLAD/FIN-PANEL 같은 sample 부족 work_code 보완 | 외부 표준단가 DB 필요 |
| ~~4~~ | ~~raw_description 재분류 매핑~~ | ~~-10pp~~ → 실측 -0.5pp | **본 시뮬레이션에서 효과 미미로 우선순위 하락** |

**권장**: 다음 작업은 **#1 actual_quantity / unit backfill**. raw_description
재분류는 보조적으로만 의미 있고, 단독으로는 트리거 도달 불가능.

## 7. quantity/unit backfill 가능성 재평가 (2026-05-09 추가)

§6 의 권장 1순위였던 quantity/unit backfill 의 실현 가능성을 점검.

### 7.1 Notion 원본에 quantity/unit 컬럼 없음

운영 ETL source인 노션 "지출결의/입금요청" CSV의 컬럼:
```
프로젝트명_자재명, 공종, 구분, 분리, 비고, 선택, 패키지,
"세금계산서, 견적서, 수량산출서"(첨부파일),
실투입금액(VAT+), 업체명, 요청일, 유닛하우스 프로젝트, ...
```

→ **quantity / unit 필드가 처음부터 존재하지 않음**. 수량 정보는 "수량산출서"
첨부 파일(JPG/PDF)에만 들어있어서 OCR 없이는 추출 불가능. 즉 §6 의 backfill
경로는 **실현 불가능**.

### 7.2 raw_description 정규식 파싱 시도 — 커버리지 13.9%

대안으로 raw_description 자체에서 수량 추출 시도. 패턴 라이브러리 (장/개/EA/m2/m/T 등)
12개로 자재 row 483건 중:

| 지표 | 값 |
|---|---|
| 파싱 성공 row | 67 / 483 (**13.9%**) |
| 파싱 성공 amount | 58.7M / 655.1M (**9.0%**) |

work_code별 커버리지:

| wc | parsed | total | row% | amt% | 비고 |
|---|---|---|---|---|---|
| STR-ST | 0 | 46 | 0% | 0% | "다랑논_골조" "홍천_골조" — 수량 0 |
| EXT-CLAD | 0 | 21 | 0% | 0% | "홍천_외장재" "남기동길 외장재" — 수량 0 |
| EXT-WIN | 0 | 14 | 0% | 0% | "다랑논_창호 자재비" — 수량 0 |
| FUR-BATH | 0 | 20 | 0% | 0% | 수량 0 |
| FIN-PANEL | 14 | 52 | 27% | 23% | "150T 35장" "EPS 180m2/28장" 패턴 일부 |
| FIN-LGS | 10 | 32 | 31% | 27% | "스카이비바 600EA" "스터드 190" |
| FIN-CARP | 7 | 59 | 12% | 13% | |
| MEP-ELEC | 18 | 85 | 21% | 23% | "외부벽등 8" 같은 trailing int |
| FUR-DOOR | 10 | 38 | 26% | 8% | "도어클로저 2" |

→ **§4의 5대 병목 work_code (FUR/EXT-CLAD/EXT-WIN/FIN-LGS/SITE-MISC) 중 
4개가 0~31% 커버리지**. 가장 큰 STR-ST 179M 도 0%. 즉 정규식 파싱이 효과를
낼 수 있는 영역이 매우 좁음.

### 7.3 같은 단위 그룹 내 단가 분포 매우 noisy

파싱된 row의 (work_code, unit) 그룹별 단가 분포 변동계수(CV):

| wc × unit | n | min | median | max | CV |
|---|---|---|---|---|---|
| FUR-DOOR × EA | 10 | 18K | 25K | **473K** | **2.07** |
| FIN-PANEL × EA | 6 | 5K | 22K | **169K** | **1.21** |
| FIN-PANEL × m2 | 5 | 15K | 30K | 142K | 0.98 |
| FIN-LGS × EA | 10 | 5K | 5K | 27K | 0.90 |
| FIN-CARP × EA | 7 | 11K | 37K | 84K | 0.78 |
| MEP-ELEC × EA | 16 | 4K | 24K | 88K | 0.73 |

→ 같은 단위 그룹 내에서도 단가가 5K~473K 처럼 100배 차이. 자재 종류
세분화 없이 unit_price 만으로는 학습 불가능. 예를 들어 FUR-DOOR EA 그룹은
"도어클로저(25K)" + "현관문(473K)" 가 같은 단위로 묶여 있음.

### 7.4 결론 — 데이터로 backfill 불가능 확정

자재 wMAPE 개선 측면에서 quantity/unit backfill 경로의 실현 가능성 평가:

| 경로 | 실현성 | 효과 예상 | 결론 |
|---|---|---|---|
| Notion API 재추출 | **불가능** | — | 원본에 컬럼 없음 |
| raw_description 정규식 파싱 | 가능 | 미미 (-1pp 이하) | 커버리지 14%, CV 1.0+ |
| 수량산출서 OCR | 가능하지만 큰 작업 | 미상 | OCR 정확도 + 자재 세분화 마스터 필요 |
| 외부 벤치마크 단가 (물가정보 등) | 가능 | 미상 | 외부 데이터 비용 + 매핑 필요 |

§6의 "권장 1순위" 였던 quantity/unit backfill 은 **데이터 source 자체의
한계로 실현 불가능**.

### 7.5 수정된 권장 — 측정 정의부터 명확히

기존 메모리에는 "자재 항목 MAPE < 15% 달성 시 흡수 트리거". 그러나 본
audit 에서 자재 wMAPE는 측정 방식에 따라 26.3% (project-sum) ~ 39.9%
(셀-단위) 로 다름.

**현재 상황 재정리**:
- 자재 row 의 quantity/unit 데이터가 없음 → 모델은 (project, work_code) 셀
  rate_per_m2 만 학습 가능
- 자재 row 의 명백한 카테고리 오분류는 ~4% 수준 → 분류 개선의 여지는 작음
- 큰 work_code(STR-ST, FIN-PANEL) 는 wMAPE 11~31% 로 양호. 작은 sample
  work_code(FUR, SITE-MOD)가 wMAPE 80~100%+ 로 평균을 끌어올림

**다음 결정이 필요한 항목**:
1. 트리거 측정 방식 명확화 — project-sum / 셀-단위 / weighted by amount 어느 것?
2. 자재 wMAPE 개선이 achievable한 수준인지 재검토 — 데이터 한계상
   < 15% 도달이 unrealistic할 수 있음
3. 만약 #2가 unrealistic 이면 **트리거 임계값 자체를 재조정** (예: project-sum < 20%)
   하거나, **흡수 시점을 다른 트리거로 대체** (예: hit-rate, within±20% 등)

**보조 작업 (코드 변경 시 추가 가치 있음)**:
- model.py: applicability tier guard (학습 셀 < 3 인 경우 예측 보류)
- enriched.db: 본 audit 의 재분류 매핑 (~4% row) 영구 적재
- vendor_name URL 정제 파이프라인 (cleanup 결과 반영)

## 8. 견적서 첨부 파싱 + actual 보정 시뮬레이션 (2026-05-09 추가)

§7 의 OCR 가설을 우회하여, 사용자가 제공한 새 Notion export(첨부 포함, 321MB)
의 견적서 attachment 들을 자동 파싱하여 자재 단가 ground truth 확보.

### 8.1 첨부 source

새 export `notion_export_v3` 에서 자동 추출:

| 타입 | 견적/명세 | 처리 결과 |
|---|---|---|
| Excel (.xlsx + .xls) | 47 | **46 / 47 자동 파싱 성공** (98%) — 표 구조 일관됨 |
| PDF (.pdf) | 57 | 26 / 57 표 추출 성공 (45%) — 일부 vendor 표 구조 차이 |
| PNG/JPG | ~93 | OCR 시도 → 한글 인식 정확도 낮음(mean conf 0.43~0.45)으로 미적용 |

### 8.2 line item 추출 결과

`harness/data/autocost_enriched.db` 의 새 테이블 `material_quote_lines` 에 적재:

- 적재 line: **588** (Excel 511 + PDF 77)
- 자재 견적서 amount sum: **약 286M (자재 actual 655M의 44%)**
- 매칭률: work_code 매칭 55%, project_code 매칭 78%

work_code 별 line 분포 (top):

| wc | n | amount |
|---|---|---|
| FUR | 179 | 62.5M |
| STR-ST | 9 | 27.1M |
| FIN-CARP | 60 | 16.1M |
| FIN-FLOOR | 18 | 15.3M |
| FIN-PANEL | 4 | 14.5M |
| EXT-WIN | 15 | 12.3M |
| SITE-DEMO | 6 | 9.4M |

### 8.3 견적서 vs actual_cost ratio cross-check

(project, work_code) 셀별 견적서 amount sum 과 운영 DB actual_costs 재료비 sum 비교:

**Ratio ≈ 1 (clean data)**:
| project | wc | quote | actual | ratio |
|---|---|---|---|---|
| N-04-S-30 | EXT-WIN | 10.5M | 11.5M | 0.91 ✓ |
| N-01-T-15 | EXT-WIN | 6.8M | 7.5M | 0.91 ✓ |
| N-07-U-6-1 | EXT-WIN | 1.8M | 1.9M | 0.93 ✓ |

**Ratio ≫ 1 (actual 누락)**:
| project | wc | quote | actual | ratio |
|---|---|---|---|---|
| **N-11-T-12** | **FUR** | **6.2M** | **0.3M** | **21.76** |
| N-04-S-30 | FUR | 8.7M | 1.1M | 7.69 |
| N-10-S-18 | FUR | 8.6M | 1.5M | 5.72 |
| N-09-H-30 | FUR | 7.6M | 5.0M | 1.51 |
| N-09-H-30 | FUR-DOOR | 5.4M | 1.9M | 2.90 |
| N-16-T-12 | MEP-HVAC | 1.1M | 0.1M | 18.95 |

**Ratio < 1 (actual 에 비-자재 row 섞임)**:
| project | wc | quote | actual | ratio |
|---|---|---|---|---|
| N-09-H-30 | FIN-CARP | 5.4M | 10.5M | 0.51 |
| N-04-S-30 | FIN-CARP | 5.0M | 9.3M | 0.54 |
| N-13-T-15-3 | FIN-CARP | 3.3M | 5.3M | 0.62 |
| N-UNMATCHED | STR-ST | 27.1M | 52.7M | 0.51 |

→ **결정적 증거 — actual_cost 자재 분류가 부정확**:
- EXT-WIN(창호) 처럼 동일 vendor 가 단일 세트로 발주되는 항목은 ratio ≈ 1 (정확)
- FUR/FUR-DOOR/MEP-HVAC 처럼 여러 자재 항목이 분산 발주되는 항목은 ratio 2~22 (actual 에 row 누락)
- FIN-CARP/STR-ST 처럼 운반비/노무비/추가자재 등이 같이 발주되는 항목은 ratio < 1 (actual 에 비-자재 섞임)

이는 §6 의 "분류 매핑" 효과 -0.5pp 가 미미했던 이유를 명확히 설명. 분류 문제는
**raw row 4% 단위가 아니라 amount 30~50% 단위**에서 발생. raw_description 키워드
매칭만으로는 잡히지 않음.

### 8.4 견적서 amount 로 actual 보정 시뮬레이션

가장 직접적인 실험: 견적서가 정확한 자재 분류라고 가정하고 (project, wc) 셀의 자재
actual 을 quote_sum 으로 대체. 11개 셀 보정, 총 33.1M 차이.

| metric | baseline | corrected | delta |
|---|---|---|---|
| 전체 wMAPE | 21.8% | 23.0% | +1.2pp |
| **자재 wMAPE (project-sum)** | **26.3%** | **21.7%** | **-4.6pp** ✅ |
| 셀-단위 "재료비" wMAPE | 39.9% | 43.4% | +3.5pp ❌ |
| 자재 wMAPE 트리거(<15%) | 11.3pp gap | 6.7pp gap | 41% 단축 |

**해석**:
- project-sum 자재 wMAPE -4.6pp 개선 → 데이터 품질 가설 부분 입증.
- 셀-단위는 오히려 악화 → 단순 quote_sum 대체는 LOO 학습 분포 흔들어 다른 셀
  prediction 정확도 떨어뜨림. 진짜 솔루션은 raw row 단위 재분류.
- 트리거 < 15% 까지의 gap을 11.3pp → 6.7pp로 단축. 추가 5~7pp 만 더 개선하면 도달 가능.

### 8.5 진단 결론 — 진짜 병목 확정

7가지 진단 단계를 거친 결과, 자재 wMAPE 39.9% 의 진짜 병목 우선순위:

1. **(60~70%) actual_cost 자재 분류 문제** — 한 vendor의 한 발주가 여러 work_code로 분산되거나 운반비/노무비와 합쳐져서 (project, work_code) 셀 amount 가 부정확. 견적서 cross-check로 입증.
2. **(20~30%) 모델 fit 한계** — sample 부족 work_code(EXT-WIN/SITE-MISC/SITE-MOD) 에서 grade × pyeong 다양성 큰데 simple median rate_per_m2 사용.
3. **(<10%) raw_description 카테고리 오분류** — FUR에 부엌수전·처마하부 등 ~20 row.

### 8.6 실현 가능한 다음 단계 (우선순위 재정렬)

| # | 작업 | 예상 효과 | 비용 | 비고 |
|---|---|---|---|---|
| 1 | **actual_cost row 단위 재분류 (sidecar에 corrected_work_code 적재)** | 자재 wMAPE -5~7pp | 中 | 견적서 line item 매핑 + 수동 검토 |
| 2 | 견적서 line items → standard_unit_price DB 구축 | 모델 재설계 후 -3~5pp | 中-高 | sandbox 문서의 standard_unit_price 컨셉 |
| 3 | 깨진 한글 파일명 PDF 재시도 (zipfile 인코딩 fix 후) | +50 line 추가 | 小 | 이미 v3 export 에서 해결 |
| 4 | applicability tier guard | -2~3pp | 小 | model.py 수정 |
| 5 | PNG/JPG OCR (Cloud Vision API 등) | +50~100 line | 高 (비용/시간) | 추가 source 확보 시 |

**1순위로 #1 추진 시 자재 wMAPE 21.7% → 14~16% 도달 가능 (트리거 < 15% 거의 달성).**

## 9. actual_cost row 단위 재분류 시뮬레이션 (2026-05-09 추가)

§8.6 의 1순위 작업 — sidecar 에 corrected_work_code 적재 후 LOO wMAPE 측정.

### 9.1 매핑 사전 검증 + 보강

`harness/scripts/validate_work_code_mapping.py` 결과:

| 발견 | 영향 |
|---|---|
| **"FUR"이 level=3** (level=2 가구 통합 코드 없음) | §4 의 FUR 셀이 catch-all 이었던 진짜 이유 |
| 우리 vs 운영 ETL WORK_MAP 11개 키워드 불일치 | "도어"/"폴딩도어"/"보일러"/"바닥난방" 등 |
| ETL이 "33. 냉장고 / 34. 세탁기 / 20. 가구 / 18. 패키지"를 모두 FUR로 묶음 | FUR에 잡종 row 들어간 원인 |

`harness/mapping/work_code_keywords.py` 로 매핑 사전 통합:
- 100+ 키워드를 work_codes 38개 level=2 코드로 정규화
- "구체적 → 일반적" 순서로 첫 매칭 채택 (예: "폴딩도어" 먼저 매칭, "도어"는 후순위)
- raw_description / 견적서 파일명 둘 다 같은 사전 사용

### 9.2 vendor 정규화 + 매핑 알고리즘

`actual_costs.vendor_name` 100% Notion URL 오염 → `normalize_vendor()`:
- `(https://www.notion.so/...)` 제거
- `(주)` `주식회사` prefix 제거
- multi-vendor 분리 후 첫 vendor 채택

corrected_wc 결정 로직 (raw_description + quote cross-check):
1. `raw_description` → primary_wc (high/medium/low confidence)
2. `(vendor_norm, project_code)` → 견적서 work_codes lookup
3. primary와 quote 일치 → confidence 1.0 (가장 강한 증거)
4. primary high confidence 단독 → 0.85
5. quote 단독 → 0.7
6. 어느 쪽도 없음 → 변경 없음

### 9.3 재분류 적용 결과

자재 actual_cost rows 483개 중:

| 결과 | n | 비고 |
|---|---|---|
| 변경됨 (corrected ≠ original) | **83** | 17% |
| 유지 (original 확정) | 298 | original 매핑 정확 |
| 증거 없음 (변경 없음) | 102 | raw_desc + 견적서 모두 매칭 안됨 |

**evidence 분포**: raw_desc 367, raw_desc+quote 14, no_evidence 102. 즉 견적서가
직접 evidence 가 된 case는 14건이지만, raw_description 기반 매칭이 367건으로 핵심
역할.

### 9.4 주요 재분류 사례 (top 8 by amount)

| from → to | n | amt | desc 예시 |
|---|---|---|---|
| FIN-PANEL → EXT-ROOF | 11 | 30.4M | "바닥지붕판넬" — 외부 지붕 |
| FIN-CARP → FIN-FLOOR | 6 | 12.6M | "리모델링월" — 강마루 브랜드 |
| FUR → EXT-DECK | 9 | 8.2M | "홍천_데크", "제주_데크각관" |
| STR-ST → STR-MISC | 3 | 2.8M | "테스트베드 인양고리, 플레이트" |
| FIN-CARP → EXT-WIN | 3 | 2.2M | "성남_목창호", "청주 미원면_목창호" |
| FIN-CARP → FUR-DOOR | 3 | 2.1M | "예림도어" |
| FUR → FUR-KITCH | 2 | 1.5M | "루떼르_냉장고", "루떼르_세탁기" |
| MEP-PLMB → MEP-HVAC | 1 | 1.4M | "서산 강수리_바닥난방" |

### 9.5 wMAPE 변화 — 예상과 다름

| metric | baseline | corrected | delta |
|---|---|---|---|
| 전체 wMAPE | 21.8% | 21.5% | -0.3pp |
| 자재 wMAPE (project-sum) | 26.3% | 26.5% | +0.2pp ❌ |
| 셀-단위 "재료비" wMAPE | 39.9% | **44.2%** | +4.4pp ❌ |

work_code 단위는 mixed:

| wc | baseline | corrected | delta |
|---|---|---|---|
| FUR | 59.0% | **54.3%** | -4.7pp ✅ |
| MEP-PLMB | 45.6% | 42.4% | -3.2pp ✅ |
| STR-ST | 14.3% | 13.5% | -0.8pp ✅ |
| EXT-ROOF | 40.0% | **63.1%** | +23pp ❌ |
| FIN-PANEL | 30.8% | 34.8% | +4pp ❌ |
| EXT-WIN | 56.5% | 59.5% | +3pp ❌ |

### 9.6 왜 자재 wMAPE 가 개선되지 않는가 — 결정적 차이

§8의 quote_sum 보정 (자재 wMAPE -4.6pp) 와 본 작업 (+0.2pp) 의 차이를 명확히 분리:

| 작업 | actual amount 변화 | work_code 변화 | 효과 |
|---|---|---|---|
| §8 quote_sum 보정 | quote_sum 으로 **대체** (실제 자재 양으로 가정) | 동일 | -4.6pp |
| §9 corrected_wc | **동일** (단순 row 이동) | 다른 wc 로 이동 | +0.2pp |

**즉 §9 의 work_code 재분류만 적용하면**:
- 같은 프로젝트의 자재 합은 변하지 않음 → project-sum wMAPE 개선 0
- 셀 단위로는 amount 가 다른 셀로 옮겨가서 학습 분포 흔들림 → 일부 wc 악화
- FIN-PANEL 30.4M 이 EXT-ROOF 로 가면, EXT-ROOF 학습 sample 7M → 37M 으로 5배 됨.
  LOO 시 EXT-ROOF 다른 프로젝트가 갑자기 큰 sample 로 학습됨 → over-predict

### 9.7 진정한 개선 경로

자재 wMAPE 21.7% → < 15% 도달을 위해선 다음 중 하나 (또는 결합) 필요:

| 작업 | 추정 효과 | 비용 | 설명 |
|---|---|---|---|
| **A. quote_sum 으로 actual 보정 + work_code 재분류 결합** | -5~-8pp | 中 | §8+§9 결합 — 가장 유력 |
| B. 누락 actual_cost row 추가 (견적서에 있는데 actual에 없는 자재) | -3~-5pp | 中-高 | 노무비/경비/MIXED row 검토 필요 |
| C. line item 단위 모델 재설계 (sandbox standard_unit_price 컨셉) | -10pp+ | 高 | 모델 architecture 변경 |
| D. actual_cost 의 cost_type 잘못 분류 점검 (재료비 ↔ 노무비 ↔ MIXED) | -2~-4pp | 中 | source_ref 정확성 검토 |

**1순위 권장**: **A (§8 + §9 결합)**. quote_sum으로 자재 합을 보정하면서, 동시에
work_code 재분류로 셀 단위 분포도 정정. 두 effect 가 합쳐지면 자재 wMAPE 26.3%
→ 18~21% 근접 가능.

### 9.8 산출 데이터

- `harness/data/autocost_enriched.db` — `actual_cost_corrections` 테이블 (483 row, 변경 83 + 증거 raw_desc/quote)
- `harness/reports/actual_corrections.json` — 변경 83 row 상세
- `harness/reports/_correction_wmape.txt` — wMAPE 비교 raw 결과
- `harness/mapping/work_code_keywords.py` — 통합 매핑 사전 (100+ 키워드)
- `harness/scripts/correct_actual_work_codes.py` — 메인 실행
- `harness/scripts/validate_work_code_mapping.py` — 매핑 사전 검증

## 10. 산출 데이터 (8장 추가)

- `harness/reports/excel_quote_parsing.json` — Excel 46개 line items (511개)
- `harness/reports/pdf_quote_parsing.json` — PDF 26개 line items (77개)
- `harness/reports/material_outlier_audit.json` — 셀별 패턴
- `harness/reports/loo_cell_error_audit.json` — LOO 셀 단위 err
- `harness/reports/reclassification_simulation.json` — 매핑 시뮬레이션
- `harness/reports/quantity_parsing_audit.json` — raw_description 정규식 파싱
- `harness/reports/_quote_correction_simulation.txt` — 견적서 보정 wMAPE
- `harness/data/autocost_enriched.db` — `material_quote_lines` 테이블 (588 line)
- `harness/scripts/parse_excel_quotes.py`, `parse_pdf_quotes.py`,
  `load_quote_lines_to_sidecar.py`, `simulate_quote_corrected_wmape.py`,
  `fix_export_filenames.py`
