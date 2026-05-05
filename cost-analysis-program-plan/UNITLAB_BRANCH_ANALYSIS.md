# UnitLab 원가분석 브런치 분석

분석 대상: `https://github.com/archdj/unitlab.git`

브런치: `원가분석-프로그램`

로컬 경로: `C:\Users\PC\unitlab-cost-analysis`

분석일: 2026-05-05

## 1. 결론

이 브런치는 원가분석 프로그램의 초안 수준이 아니라, 실제 데이터베이스와 파이프라인, FastAPI 백엔드, Vite 프론트엔드까지 포함한 실행 가능한 원가분석 작업물이다.

다만 현재 상태는 "실제 원가 분석"과 "파생 단가", "예측 견적"이 한 DB와 API 안에 같이 들어 있다. 사용자가 요구한 "추천/우선순위 제거, 무조건 현실 데이터 기반" 기준으로 쓰려면 다음 구분을 제품과 리포트에서 반드시 분리해야 한다.

- 실제 데이터: 결제/집행 원가, BIM 추출 수량, IFC 파일, 자재/공종 매핑 원본
- 파생 데이터: 공종별 단가, BIM 기반 단가, 손실/할증률
- 예측 데이터: rule, BIM, ML 기반 `cost_predictions`

현재 그대로 운영 화면에 노출하면 사용자가 예측값을 실제 집행 원가로 오해할 수 있다.

## 2. 현재 포함 데이터

SQLite DB: `db/cost_analysis.db`

현재 테이블 건수:

| 테이블 | 건수 | 의미 |
|---|---:|---|
| `actual_costs` | 931 | 실제 집행 원가. 현재 전부 `NOTION / approved` |
| `bim_quantities` | 3,745 | IFC에서 추출한 BIM 수량 |
| `materials` | 2,899 | 자재 마스터 |
| `material_aliases` | 250 | 자재 별칭 매핑 |
| `work_codes` | 147 | 공종 코드 |
| `projects` | 26 | 프로젝트 |
| `project_modules` | 9 | 프로젝트-모듈 연결 |
| `ifc_files` | 17 | IFC 원본 파일 메타 |
| `unit_prices` | 35 | 파생 단가 |
| `loss_factors` | 6 | BIM 대비 실집행 보정률 |
| `cost_predictions` | 216 | 예측 원가 |
| `audit_log` | 0 | 변경 이력 없음 |

실제 원가 현황:

- `actual_costs`: 931건
- 총액: 1,642,728,277원
- 소스: `NOTION`
- 상태: `approved`
- 현재 DB에는 `PROCURE` 소스 actual cost가 없음

## 3. 브런치의 주요 구성

### 데이터 파이프라인

- `migrate_notion.py`: Notion 원천 DB를 원가 DB로 이관
- `parse_ifc_all.py`: IFC 파일에서 BIM 수량 추출
- `import_procure.py`: 발주 CSV를 `actual_costs`로 적재
- `compute_analytics.py`: 단가, BIM 단가, loss factor, prediction 생성
- `ml_pipeline.py`: hybrid residual ML 예측 생성
- `gap_analysis.py`: 예측과 실제 원가 차이 분석

### 데이터베이스

- `db/migrations/001_schema.sql`: 핵심 스키마
- `db/migrations/002_seed_work_codes.sql`: 기본 공종 코드
- `db/migrations/003_unitlab_work_codes.sql`: UnitLab 공종 코드
- `db/cost_analysis.db`: 현재 분석 DB
- `source_notion.db`: Notion 원천 DB

### 웹 애플리케이션

- `web/backend/main.py`: FastAPI API
- `web/frontend/src/pages/*.jsx`: 대시보드, 프로젝트, 단가, loss factor, BIM viewer, 견적, 예측 화면

## 4. 실제 데이터 기반으로 인정 가능한 부분

다음은 원천 데이터 또는 원천 데이터에서 직접 산출된 데이터로 볼 수 있다.

- `actual_costs`: 결제/집행 원가 기반. 현재 931건 모두 승인 상태
- `bim_quantities`: IFC 파일에서 추출된 수량
- `ifc_files`: IFC 원본 파일 메타와 해시
- `materials`, `material_aliases`: 자재 마스터와 별칭
- `work_codes`: 원가 분석 기준이 되는 공종 체계
- 발주 CSV: 파일은 존재하고 import 스크립트도 있으나, 현재 DB에는 반영되지 않음

현실 데이터 기반 프로그램의 1차 화면은 위 데이터만 사용해야 한다.

## 5. 파생/예측으로 분리해야 하는 부분

다음은 실제 데이터가 아니라 계산 결과다.

- `unit_prices`
  - `NOTION / m2`: 실제 원가를 면적으로 나눈 공종별 면적 단가
  - `BIM / EA`, `BIM / m`: 실제 원가와 BIM 수량을 교차해 계산한 BIM 단가
- `loss_factors`
  - 현재 6개 공종 모두 `loss_ratio = 1.0`
  - notes를 보면 BIM물량 x 단가가 실집행과 거의 같게 맞춰진 결과라, 독립 검증된 손실률로 보기는 어렵다
- `cost_predictions`
  - rule, BIM, KNN, Ridge, Ensemble 등 여러 버전의 예측값
  - 실제 원가가 아니라 참고/시뮬레이션 값이다
- `/api/estimate`, `/api/quote/predict`
  - 실제 원가 조회 API가 아니라 견적/예측 API다

현실 데이터 기준에서는 이 데이터들을 "실제 원가"가 아니라 "실제 데이터 기반 계산값" 또는 "예측 참고값"으로 명확히 표시해야 한다.

## 6. 검증 결과

`python compute_analytics.py --dry-run` 결과:

- DB 변경 없이 현재 상태 출력 성공
- 실원가 합계: 931건, 16.43억원
- BIM 기반 단가 산출 공종: 6개
  - `FUR`
  - `EXT-WIN`
  - `FIN-PANEL`
  - `FIN-LGS`
  - `STR-ST`
  - `MEP-ELEC`
- loss factor: 6개 모두 1.000
- IFC 프로젝트 예측 원가가 출력됨

`python gap_analysis.py` 결과:

- DB 내 예측 모델 버전:
  - `v1.0-rule`
  - `v2.0-bim`
  - `v6.0-*`
  - `v7.0-*`
  - `v9.0-hybrid-*`
- `v2.0-bim`은 8개 실제 비교 프로젝트 기준 MAE 약 59.0%
- `v9.0-hybrid-ridge`는 전체 원가 기준 오차가 큰 프로젝트가 많음
- 별도 표시된 ML info 기준 `v9.0-hybrid-ridge`의 LOO MAPE는 약 28.6%, 학습 샘플은 9개

샘플 수가 작고 프로젝트별 편차가 커서 ML 예측은 운영 의사결정의 근거로 쓰기 어렵다. 화면에서는 숨기거나 "검증 중 참고값"으로만 노출해야 한다.

## 7. 코드상 주요 위험

### 7.1 발주 CSV가 현재 DB에 반영되지 않음

`import_procure.py`는 발주 CSV를 읽어 `actual_costs`에 `source_system='PROCURE'`로 넣는 구조다.

하지만 현재 DB 조회 결과:

- `NOTION / approved`: 931건
- `PROCURE`: 0건

즉 발주 데이터는 파일과 import 코드가 있지만, 현재 분석 DB에는 실제 원가로 들어와 있지 않다.

### 7.2 프로젝트/공종 매핑이 하드코딩

`import_procure.py`:

- `PROJ_MAP`으로 프로젝트명 일부를 프로젝트 코드에 매핑
- `PROCESS_WC`로 발주 CSV의 공정을 공종 코드에 매핑
- 매핑 실패 시 `N-UNMATCHED`로 들어감

실제 데이터 기반으로 쓰려면 매핑 실패 건수, 금액, 원본 행을 반드시 리포트해야 한다.

### 7.3 IFC 매핑이 타입 기반 휴리스틱

`parse_ifc_all.py`:

- `IfcBeam`, `IfcColumn`, `IfcSlab` 등을 `STR-ST`로 매핑
- `IfcWall`을 `FIN-PANEL-001`
- `IfcWallStandardCase`를 `FIN-LGS`
- `IfcDoor`를 `FUR-DOOR-003`
- `IfcWindow`를 `EXT-WIN`
- `IfcFlowTerminal`을 `MEP-ELEC`

이 방식은 BIM 객체 타입 기반이므로 빠르게 작동하지만, 자재 속성/패밀리/스펙 기반 검증은 아니다.

### 7.4 `compute_analytics.py`는 DB를 삭제 후 재생성

다음 작업은 기존 계산 결과를 삭제한다.

- `DELETE FROM unit_prices WHERE source='NOTION'`
- `DELETE FROM unit_prices WHERE source='BIM'`
- `DELETE FROM loss_factors`
- `DELETE FROM cost_predictions WHERE model_version LIKE 'v%'`

따라서 운영 데이터에서는 `--dry-run` 없이 실행하면 안 된다.

### 7.5 audit log가 비어 있음

스키마에는 `audit_log`가 있지만 현재 0건이다.

현실 데이터 기반 분석에서는 다음 이력이 필요하다.

- 원천 파일 적재
- 매핑 수정
- 단가 계산
- 예측 생성
- 승인/반려
- 수동 보정

## 8. 현재 브런치를 어떻게 써야 하는가

### 8.1 1단계: 읽기 전용 분석기로 사용

현재 브런치는 곧바로 운영 견적 프로그램으로 쓰기보다, 먼저 읽기 전용 원가 분석기로 써야 한다.

사용 화면:

- 프로젝트별 실제 원가
- 공종별 실제 원가
- 업체별 실제 원가
- 자재별 실제 원가
- BIM 수량과 실제 원가 연결 상태
- 미매핑 데이터 목록
- 프로젝트별 원가 누락/과다/이상치

사용하지 말아야 할 화면:

- 자동 추천
- 예측 우선순위
- ML 견적 자동 확정
- 파생 단가를 실제 원가처럼 표시하는 화면

### 8.2 2단계: 데이터 계보를 추가

모든 숫자에 다음 분류가 붙어야 한다.

| 분류 | 의미 |
|---|---|
| `actual` | 결제/집행 원장 원본 |
| `bim_extracted` | IFC에서 추출한 수량 |
| `mapped` | 원본을 공종/자재/프로젝트에 매핑한 값 |
| `derived` | 실제 원가와 BIM/면적으로 계산한 단가 |
| `predicted` | 모델 또는 규칙으로 만든 예측값 |
| `manual_adjusted` | 사람이 보정한 값 |

### 8.3 3단계: 발주 CSV를 검증 후 반영

발주 CSV는 현재 파일과 스크립트가 있지만 DB에 반영되어 있지 않다.

먼저 해야 할 검증:

- 파일 인코딩 확인
- 컬럼명 확인
- 프로젝트명 매핑률
- 공정 매핑률
- 업체명 매핑률
- 금액 컬럼 존재 여부
- 수량/단위 변환 가능 여부
- `N-UNMATCHED` 발생 금액

그 다음에만 `PROCURE` 데이터를 `actual_costs`에 넣어야 한다.

## 9. 현실 데이터 기반 작업 하네스에 추가할 항목

기존 계획 폴더의 하네스에 다음 리포트를 추가하는 것이 맞다.

- `source_inventory_report.json`: 원천 파일/DB/테이블 목록
- `actual_cost_lineage_report.json`: 실제 원가 1건별 출처, 프로젝트, 공종, 업체, 금액
- `mapping_gap_report.json`: 프로젝트/공종/자재/업체 미매핑 목록
- `bim_mapping_report.json`: IFC 객체 타입별 공종 매핑 근거
- `derived_metric_report.json`: 단가/loss factor/예측값의 계산식과 입력 데이터
- `prediction_validation_report.json`: 예측값과 실제 원가 차이

이 리포트 없이는 원가분석 프로그램의 숫자를 신뢰하기 어렵다.

## 10. 다음 작업 기준

이 브런치를 기반으로 계속 진행한다면 작업 기준은 다음과 같다.

1. 실제 원가 화면과 예측 화면을 분리한다.
2. `PROCURE` CSV import를 실행하기 전에 dry-run 검증 모드를 만든다.
3. `N-UNMATCHED` 프로젝트와 미매핑 공종을 별도 리포트로 만든다.
4. `unit_prices`, `loss_factors`, `cost_predictions`는 모두 파생 테이블로 라벨링한다.
5. `compute_analytics.py`의 삭제/재생성 작업은 백업 또는 별도 산출 DB에서만 실행한다.
6. ML 예측은 학습 샘플과 오차율을 함께 표시하고, 실제 원가로 취급하지 않는다.
7. audit log를 실제로 쓰도록 import/계산/승인 흐름에 연결한다.

## 11. 운영 관점 판정

현재 상태로 가능한 것:

- 실제 결제 원가 DB 조회
- 프로젝트별 원가 집계
- 공종별 원가 집계
- IFC 기반 BIM 수량 조회
- BIM 수량과 실제 원가를 연결한 단가 산출
- 예측값과 실제값 차이 분석

현재 상태로 위험한 것:

- 예측값을 견적 확정값으로 사용
- 발주 CSV가 반영됐다고 가정
- BIM 객체 타입 매핑을 완전한 자재 매핑으로 간주
- loss factor 1.0을 검증된 현장 할증률로 간주
- ML 모델을 운영 견적 모델로 사용

이 브런치는 "현실 데이터 기반 원가분석 프로그램"의 기반으로는 쓸 수 있다. 단, 현재 제품의 첫 화면은 예측이 아니라 원천 데이터 검증과 실제 원가 분석이어야 한다.
