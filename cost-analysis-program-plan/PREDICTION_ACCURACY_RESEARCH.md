# 원가 예측 정확도 개선 조사

분석 대상: `C:\Users\PC\unitlab-cost-analysis`

작성일: 2026-05-05

## 1. 현재 모델 상태

현재 브런치의 예측 모델은 `ml_pipeline.py`의 `v9.0-hybrid` 계열이다.

구조:

- 실제 원가를 `area_actual`, `option_actual`, `site_actual`로 분리
- 면적, 등급, 모듈 prefix, BIM 존재 여부, BIM 수량/밀도 등을 feature로 사용
- 먼저 구조화 산식으로 기본 원가를 계산
- KNN/Ridge/Ensemble이 구조화 산식의 잔차를 보정
- 최종 원가 = 공법/면적 원가 + 옵션 원가 + 현장 원가

현재 `ml_model_info` 기준:

- `v9.0-hybrid-ridge`
- 학습 샘플: 9개 프로젝트
- LOO MAPE: 약 28.6%

주의할 점:

- 프로젝트 단위 학습 샘플이 너무 적다.
- 실제 원가 라인 수는 931건이지만, 모델이 배우는 독립 샘플은 프로젝트/모듈 단위다.
- 예측 오차가 특정 프로젝트에서 크게 터진다.
- `PROCURE` 발주 CSV는 현재 DB의 `actual_costs`에 반영되지 않았다.

## 2. 외부 조사 요약

건설 원가 예측 연구는 ML 적용이 늘고 있지만, 핵심은 모델 자체보다 입력 변수와 검증 방식이다.

- scikit-learn 문서는 모델 성능 평가와 하이퍼파라미터 튜닝에 cross-validation을 쓰고, 모델 선택과 평가를 분리해야 한다고 설명한다.
- nested cross-validation은 작은 데이터에서 하이퍼파라미터 선택으로 인한 과대평가를 줄이는 데 필요하다.
- BIM 기반 원가 예측 연구는 총면적뿐 아니라 벽 면적, 개수, 둘레 등 BIM 속성을 함께 쓰면 개략 견적보다 더 빠르고 정확한 예측이 가능하다고 본다.
- construction cost ML review는 원가 예측 문제가 다차원적이고, ML 연구가 증가하고 있지만 데이터 구성과 변수 선택이 성능을 좌우한다고 정리한다.
- scikit-learn의 permutation importance는 어떤 feature가 검증 성능에 실제로 기여하는지 확인하는 방법이다.
- quantile regression 기반 prediction interval은 점 예측 하나 대신 상한/하한 범위를 제공할 수 있다.

참고 자료:

- scikit-learn Model Selection: https://scikit-learn.org/stable/model_selection
- scikit-learn Nested CV example: https://sklearn.org/1.7/auto_examples/model_selection/plot_nested_cross_validation_iris.html
- scikit-learn Permutation Importance: https://scikit-learn.org/dev/modules/permutation_importance.html
- scikit-learn Quantile Regression Intervals: https://scikit-learn.org/1.5/auto_examples/ensemble/plot_gradient_boosting_quantile.html
- BIM properties cost prediction paper: https://www.mdpi.com/2345206
- Construction cost ML taxonomy review: https://link.springer.com/article/10.1007/s41062-024-01705-0

## 3. 정확도 개선 방향

### 3.1 학습 단위를 늘려야 한다

지금 가장 큰 병목은 모델이 배우는 프로젝트 수다.

실제 원가 931건은 많아 보이지만, 같은 프로젝트 안의 라인들은 독립 샘플이 아니다. 현재 모델의 실질 학습 샘플은 9개 수준이다.

개선 방법:

- 프로젝트별 총액 예측만 하지 말고 `프로젝트 x 공종` 단위로 학습 데이터를 만든다.
- 공종별 예측 후 합산한다.
- 단, train/test split은 반드시 프로젝트 단위로 묶는다.
- 같은 프로젝트의 공종 라인이 train과 test에 동시에 들어가면 누수다.

추천 데이터셋 구조:

| grain | target | 설명 |
|---|---|---|
| project | total_cost | 전체 원가 검증용 |
| project_workcode | workcode_cost | 실제 학습 주력 |
| project_workcode_material | material_cost | 자재 매핑이 안정화된 후 |
| project_vendor_workcode | vendor_cost | 업체 효과 분석용 |

### 3.2 총액 예측보다 구성요소 예측이 맞다

모듈 건축 원가는 합산 구조다. 총액 하나를 바로 맞히면 노이즈가 크다.

분리해야 할 비용:

- 공장 제작 원가
- 현장 공사 원가
- 운반/양중
- 기초/토공
- 창호
- 가구/옵션
- 설비/전기
- 외장/마감
- 예외성 비용

각 항목의 driver가 다르다.

예:

- 철골: BIM 길이, 중량, 부재 수
- 판넬: 면적, 개구부, 외피 면적
- 창호: 개수, 면적, 사양
- 가구: 개수, 옵션 패키지
- 현장비: 지역, 거리, 양중 조건, 현장 기간

현재처럼 총액 예측을 유지하더라도, 내부 breakdown은 반드시 공종별로 계산해야 한다.

### 3.3 BIM feature를 더 현실화해야 한다

현재 `parse_ifc_all.py`는 IFC 객체 타입을 공종으로 매핑한다.

예:

- `IfcBeam`, `IfcColumn` -> `STR-ST`
- `IfcWall` -> `FIN-PANEL-001`
- `IfcWallStandardCase` -> `FIN-LGS`
- `IfcDoor` -> `FUR-DOOR-003`
- `IfcWindow` -> `EXT-WIN`

정확도를 올리려면 타입만으로 부족하다.

추가 feature:

- 부재 길이/면적/체적
- 개수
- 단위면적당 수량
- 외피 면적
- 창호 면적과 창호 개수
- 문 개수
- 벽체 타입별 면적
- 패널 타입/두께/재질
- 철골 규격별 길이 또는 중량
- 층고, 모듈 폭/길이
- 설비 fixture 개수
- BIM 수량 추출 방식 신뢰도

그리고 각 feature에는 출처가 붙어야 한다.

- IFC quantity
- IFC property
- 파일명/수동 메타
- Notion/발주 DB
- 사람이 승인한 매핑

### 3.4 가격 시점 보정이 필요하다

실제 결제 데이터는 결제일이 다르면 같은 공종도 단가가 다르다.

필요한 feature:

- 결제월
- 발주월
- 납품월
- 프로젝트 착공/준공 시점
- 철강/목재/판넬 등 자재 가격 지수
- 업체별 단가 변경 이력

최소 구현:

- 모든 실제 원가를 기준월 원가로 환산한 `normalized_amount`를 만든다.
- 모델 target은 `total_amount`가 아니라 `normalized_amount`를 사용한다.
- 예측 결과는 다시 예측월 가격으로 환산한다.

### 3.5 업체/지역/현장 조건을 별도 변수로 둬야 한다

현재 모델은 현장비를 면적 비율로 다루지만, 현장 원가는 면적보다 조건 영향이 크다.

추가해야 할 변수:

- 지역
- 운송 거리
- 크레인 필요 여부
- 진입로 제약
- 기초 형태
- 현장 체류 일수
- 업체
- 업체-공종 조합
- 하자/재시공/추가발주 여부

이 데이터가 없으면 현장비 예측은 구조적으로 흔들린다.

### 3.6 예외 프로젝트를 학습에서 분리해야 한다

현재 gap 분석에서 오차가 큰 프로젝트가 있다.

예:

- 실제 원가가 작거나 일부만 입력된 프로젝트
- 쇼룸/팝업/해외/개발성 프로젝트
- BIM은 있으나 실제 원가가 없는 프로젝트
- 프로젝트 코드/면적이 없는 프로젝트
- `N-UNMATCHED`

이 프로젝트들은 모델을 망가뜨릴 수 있다.

필요한 상태값:

- `complete_actual_cost`
- `complete_bim`
- `standard_module`
- `non_standard_project`
- `exclude_from_training_reason`

### 3.7 검증 방식을 바꿔야 한다

현재 LOO는 작은 데이터에서 유용하지만, 모델 선택까지 같이 하면 성능이 과대평가될 수 있다.

필요한 검증:

- Leave-One-Project-Out
- GroupKFold by project
- 모듈 타입별 holdout
- 시간 기준 backtest
- 예측월 기준 future-only test
- nested CV로 모델 선택/평가 분리

측정 지표:

- MAE
- MdAPE
- MAPE
- WAPE
- 공종별 MAE
- 프로젝트별 총액 오차
- ±10%, ±20%, ±30% 이내 비율
- prediction interval coverage

### 3.8 feature importance 리포트가 필요하다

모델을 바꾸기 전에 어떤 입력이 실제로 예측에 도움이 되는지 봐야 한다.

추가 리포트:

- permutation importance
- feature별 결측률
- feature별 train/test 분포 차이
- 프로젝트별 residual
- 공종별 residual
- 고오차 프로젝트의 원인 분해

중요한 점:

- 성능이 낮은 모델의 feature importance는 신뢰하면 안 된다.
- feature importance는 검증셋 또는 cross-validation 기준으로 계산해야 한다.

### 3.9 점 예측 대신 범위를 내야 한다

원가 예측은 단일 숫자보다 범위가 현실적이다.

필요 출력:

- 예상 원가
- 하한
- 상한
- 유사 사례
- 근거 공종 breakdown
- BIM 커버리지
- 학습 샘플 수
- 최근 검증 오차

구현 후보:

- quantile regression
- conformal prediction
- 프로젝트 유형별 empirical residual interval

현재 데이터 규모에서는 복잡한 확률 모델보다, 프로젝트 유형별 residual 기반 구간이 더 현실적이다.

## 4. 현재 브런치에 바로 적용할 수 있는 작업

### 4.1 예측 데이터셋 리포트 생성

먼저 모델 개선 전에 데이터셋 리포트가 필요하다.

만들 파일:

- `reports/prediction_dataset_report.json`

포함 내용:

- 학습 대상 프로젝트
- 제외 프로젝트와 제외 이유
- 프로젝트별 실제 원가 완성도
- BIM 존재 여부
- 면적 존재 여부
- 공종별 실제 원가
- 공종별 BIM 수량
- 결측 feature 목록
- target 분포

### 4.2 `project_workcode` 학습 테이블 추가

현재 `actual_costs`와 `bim_quantities`를 직접 조인하지 말고, 예측용 마트 테이블을 만든다.

예:

- `ml_project_workcode_features`

컬럼:

- `project_id`
- `work_code_id`
- `actual_amount`
- `bim_quantity`
- `bim_unit`
- `floor_area_m2`
- `quantity_per_m2`
- `cost_per_m2`
- `vendor_count`
- `payment_month`
- `source_coverage`
- `is_trainable`
- `exclude_reason`

### 4.3 모델을 두 단계로 바꾼다

1단계: 공종별 원가 예측

- target: `project_workcode.actual_amount`
- feature: BIM 수량, 면적, 모듈 타입, 공종, 지역, 업체, 시점

2단계: 프로젝트 총액 합산

- 공종별 예측 합계
- 옵션/현장/예외비 별도 합산
- 불확실성도 공종별로 합산

### 4.4 baseline을 고정한다

모델 개선 여부를 보려면 baseline이 필요하다.

baseline:

- 동일 모듈 최근 사례 median
- 공종별 원/m2 median
- BIM 수량 x 공종별 median unit price
- 유사 사례 k개 가중 평균

ML은 이 baseline보다 좋아야 유지한다.

### 4.5 예측 화면 표시 방식 변경

현재 예측값을 숫자 하나로 크게 보여주면 안 된다.

표시해야 할 정보:

- 예측값
- 예측 구간
- 실제 데이터 기반 여부
- 파생 계산 여부
- ML 예측 여부
- 학습 샘플 수
- 유사 사례
- 고오차 가능 경고
- BIM 커버리지

## 5. 권장 구현 순서

1. `PROCURE` CSV를 dry-run으로 검증하고 미매핑 리포트를 만든다.
2. `actual_costs`의 프로젝트/공종/업체/시점 매핑 완성도를 리포트한다.
3. `project_workcode` 예측 마트 테이블을 만든다.
4. 공종별 baseline 예측을 만든다.
5. GroupKFold/Leave-One-Project-Out 검증 하네스를 만든다.
6. 공종별 Ridge/Huber/Quantile 모델을 붙인다.
7. feature importance와 residual 리포트를 만든다.
8. 예측 결과를 구간과 근거 breakdown으로 표시한다.

## 6. 핵심 판단

지금 정확도를 올리는 최단 경로는 "더 강한 ML 모델"이 아니다.

현재 데이터에서는 다음이 먼저다.

- 학습 샘플 수를 프로젝트 x 공종 단위로 늘리기
- 같은 프로젝트 데이터가 train/test에 섞이지 않게 막기
- 발주 CSV와 결제 데이터를 실제 원가 DB에 반영하기
- BIM 수량을 타입 기반이 아니라 수량/스펙/자재 기반 feature로 만들기
- 총액 예측이 아니라 공종별 예측 후 합산하기
- 예측값 하나가 아니라 범위와 근거를 출력하기

이렇게 해야 사용자가 말한 "현실 데이터 기반" 원가 예측으로 갈 수 있다.
