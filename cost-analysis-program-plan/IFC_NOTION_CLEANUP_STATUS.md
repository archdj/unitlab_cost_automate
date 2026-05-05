# IFC-Notion 연결 정리 진행 상태

작성일: 2026-05-05

대상 DB: `C:\Users\PC\unitlab-cost-analysis\db\cost_analysis.db`

## 1. 진행한 작업

### 1.1 연결 검증 하네스 생성

스크립트:

`cost-analysis-program-plan/harness/scripts/validate_ifc_notion_alignment.py`

리포트:

`cost-analysis-program-plan/harness/reports/ifc_notion_alignment_report.json`

역할:

- IFC 파일이 로컬에 존재하는지 확인
- DB의 `ifc_files.file_path`가 현재 경로인지 확인
- IFC가 프로젝트에 연결되어 있는지 확인
- IFC module과 project module이 같은지 확인
- 연결된 프로젝트에 Notion 실제원가가 있는지 확인
- BIM 공종과 Notion 실제원가 공종 overlap을 확인

### 1.2 경로/해시 정리 계획 생성

스크립트:

`cost-analysis-program-plan/harness/scripts/prepare_ifc_notion_cleanup_plan.py`

산출물:

- `harness/reports/ifc_path_repair_plan.json`
- `harness/reports/ifc_project_module_repair_plan.json`
- `harness/reports/ifc_project_link_review_template.csv`
- `harness/sql/ifc_project_link_reviews_schema.sql`

### 1.3 안전한 IFC 경로/해시 반영

스크립트:

`cost-analysis-program-plan/harness/scripts/apply_safe_ifc_path_repairs.py`

반영 기준:

- 로컬 IFC 파일명과 DB 파일명이 정확히 일치
- 해시가 일치하거나 DB 해시가 비어 있음
- fuzzy/manual review 항목 제외

반영 결과:

- 14개 IFC의 `file_path`, `file_hash`, `file_size_mb` 갱신
- DB 백업 생성:

`C:\Users\PC\unitlab-cost-analysis\db\cost_analysis.before_ifc_path_repair.20260505_092802.db`

### 1.4 IFC 연결 승인 테이블 생성

스크립트:

`cost-analysis-program-plan/harness/scripts/seed_ifc_project_link_reviews.py`

DB 테이블:

`ifc_project_link_reviews`

적재 결과:

- 17개 IFC 연결 검토 행 inserted
- 상태는 전부 `pending`

## 2. 현재 검증 결과

경로/해시 정정 후 재검증 결과:

```text
IFC records: 17
Local IFC files: 15

review: 13
fail: 4

safe_to_use_for_prediction: false
```

경고 변화:

```text
이전:
- previous machine path: 17
- missing file hash: 8

현재:
- previous machine path: 3
- missing file hash: 2
```

즉, 안전하게 정리 가능한 경로/해시는 대부분 정리됐다.

## 3. 아직 남은 문제

### 3.1 로컬 파일 확인 필요

다음 IFC는 DB에는 있으나 현재 로컬 IFC 폴더에서 동일 파일을 찾지 못했다.

| ifc_file_id | DB 파일명 | 상태 |
|---:|---|---|
| 5 | `용인 남곡리 10평 쇼룸_수정_250817(Recovery).ifc` | 로컬 동일 파일 없음 |
| 11 | `Unit Lab Template T Haus_2_240213.ifc` | 로컬 동일 파일 없음, 실제원가 없음 |
| 14 | `양평군_원덕리346-34_근생_s-18_260319.ifc` | `260325` 파일과 유사, 수동 확인 필요 |

### 3.2 project_modules 누락/충돌

수정 계획:

`harness/reports/ifc_project_module_repair_plan.json`

자동 반영하지 않은 이유:

- 일부 IFC module은 파일명 기반 fallback으로 생성된 모듈이다.
- 잘못 승인하면 평형/면적 기준 원가가 꼬인다.

현재 제안:

```text
insert_project_module_from_ifc_module: 6개
manual_review_module_conflict: 1개
manual_review: 1개
```

충돌 케이스:

```text
N-21-서산-부석면-강수리-277
- IFC module: ST-STD-2025 / 49.0m2 / 14.8평
- 기존 project_module: T-9-STD / 29.75m2 / 9평
```

이건 자동 수정하면 안 된다. 실제 평형/모듈 원천 확인이 필요하다.

### 3.3 BIM 공종과 Notion 원가 공종 overlap 낮음

현재 14개 IFC 연결에서 BIM 공종과 Notion actual 공종의 overlap이 낮게 나온다.

이건 반드시 나쁜 연결이라는 뜻은 아니다.

가능한 이유:

- BIM은 하위 객체 공종이고 Notion은 상위 공종으로 들어감
- BIM에 없는 경비/노무/현장비가 Notion에 있음
- IFC parser의 `IFC_WORK_MAP`이 실제 공종 체계와 다름
- Notion 원가가 공종 분류상 다른 코드에 들어감

다음 작업에서는 상위 공종 기준으로 다시 overlap을 계산해야 한다.

## 4. 다음 작업 순서

### 4.1 수동 확인 대상 분리

`ifc_project_link_reviews`에서 다음 필드를 채워야 한다.

- `approved_project_code`
- `approved_module_code`
- `approval_status`
- `reviewer`
- `notes`

승인 상태:

| 상태 | 의미 |
|---|---|
| `approved` | 예측 입력 사용 가능 |
| `pending` | 아직 검토 중 |
| `rejected` | 예측 입력 제외 |
| `needs_source_file` | 원본 IFC 파일 필요 |
| `needs_module_confirmation` | 모듈/평형 확인 필요 |

### 4.2 project_modules 반영은 승인 후 실행

자동 반영 금지.

필요한 확인:

- 프로젝트 실제 평형
- IFC가 최종 설계 파일인지
- Notion 원가 프로젝트와 IFC 프로젝트가 같은지
- 모듈 타입/면적이 맞는지

### 4.3 공종 overlap 리포트 개선

현재는 정확히 같은 `work_code`만 비교한다.

개선:

- 상위 공종 기준 비교
- BIM-only 공종 목록
- Notion-only 공종 목록
- 금액 큰데 BIM 없는 공종
- BIM 수량 큰데 Notion 원가 없는 공종

### 4.4 승인된 IFC만 예측 엔진 입력으로 사용

예측 엔진은 다음 조건을 만족하는 데이터만 써야 한다.

```text
ifc_project_link_reviews.approval_status = 'approved'
AND ifc_files.file_path 로컬 존재
AND project_modules 연결 확인
AND actual_costs 존재
```

이 조건을 만족하지 않으면 예측에는 사용하지 않고 검토 리포트에만 표시한다.

## 5. 추가 진행 결과

### 5.1 자동 분류 완료

스크립트:

`cost-analysis-program-plan/harness/scripts/classify_ifc_link_reviews.py`

리포트:

`cost-analysis-program-plan/harness/reports/ifc_link_review_classification.json`

분류 결과:

```text
approved: 6
needs_module_confirmation: 7
needs_source_file: 3
needs_workcode_review: 1
pending: 0
```

approved 조건:

- 로컬 IFC 파일 존재
- Notion 실제원가 존재
- BIM 수량 존재
- project_modules 연결 존재
- 공종 overlap 및 금액 coverage가 최소 기준 이상

### 5.2 approved 입력셋 생성 및 검증

스크립트:

- `cost-analysis-program-plan/harness/scripts/build_approved_ifc_prediction_inputs.py`
- `cost-analysis-program-plan/harness/scripts/verify_ifc_cleanup_state.py`

리포트:

- `cost-analysis-program-plan/harness/reports/approved_ifc_prediction_inputs.json`
- `cost-analysis-program-plan/harness/reports/ifc_cleanup_verification.json`

검증 결과:

```text
approved_inputs: 6
approved_files_exist: true
approved_have_actuals: true
approved_have_bim: true
approved_have_project_module: true
safe_to_run_prediction_on_approved_inputs: true
```

approved 프로젝트:

```text
N-01-T-15
N-03-농어촌-공사
N-07-U-6-1
N-08-U-6-1
N-11-T-12
N-13-T-15-3
```

### 5.3 검증 데이터셋 생성

스크립트:

`cost-analysis-program-plan/harness/scripts/build_verified_evidence_dataset.py`

리포트:

`cost-analysis-program-plan/harness/reports/verified_evidence_dataset.json`

결과:

```text
verified_projects: 6
rows: 210
```

### 5.4 검증 통과 데이터만 쓰는 견적 하네스 생성

스크립트:

`cost-analysis-program-plan/harness/scripts/generate_verified_evidence_estimate.py`

샘플 입력:

`cost-analysis-program-plan/harness/examples/evidence_estimate_request.json`

샘플 출력:

`cost-analysis-program-plan/harness/reports/verified_evidence_estimate_sample.json`

T-15-STD 1동 샘플 결과:

```text
estimated_amount: 160,836,011원
source_case_count: 6
same_module_case_count: 2
component_count: 67
missing_required_count: 0
uses_only_approved_ifc_links: true
```

비용 성격별:

```text
노무비: 60,578,269원
재료비: 47,140,780원
재료비+노무비: 35,070,419원
기타: 8,365,692원
경비: 6,161,255원
제작+현장설치 비: 3,519,596원
```

검증:

```text
source_cases와 component source_cases는 모두 approved 프로젝트 6개 안에 있음.
미승인 IFC는 견적 산출에 사용되지 않음.
```
