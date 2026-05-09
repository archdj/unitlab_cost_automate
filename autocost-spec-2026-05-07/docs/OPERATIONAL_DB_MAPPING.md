# OPERATIONAL_DB_MAPPING — 운영 DB 자산 인벤토리

운영 DB `C:/Users/PC/unitlab-cost-analysis/db/cost_analysis.db` (SQLite, read-only) 의 실제 상태를
명세서 10개 기능에 매핑한다. M0 데이터 계약 확정 작업의 기준 문서.

> 조회 시점: 2026-05-07.
> 본 폴더는 운영 DB를 read-only 로 참조한다 — 쓰기는 운영 메인 repo (`unitlab-cost-analysis`) 에서 한다.

## 1. 테이블 인벤토리 (행 수)

| 테이블 | 행 수 | 명세서 활용 |
|---|---|---|
| `projects` | 27 | F6 프로젝트 조건 |
| `module_types` | 17 | F6 등급/평형 입력 옵션 |
| `work_codes` | 147 | F9 공종 마스터 (대 6 / 중 21 / 소 73 +) |
| `materials` | 3,356 | F9 자재 마스터 |
| `material_aliases` | 250 | F1.2.1 동의어 매핑 (= 본 폴더의 `material_synonyms`) |
| `actual_costs` | **931** | F1, F2 학습 데이터 |
| `bim_quantities` | 2,455 | F2 입력 (옵션 — IFC 추후) |
| `loss_factors` | 6 | F2, F6.1.2 로스율 (적음 — 보강 필요) |
| `unit_prices` | 18 | F2 단가 보조 (적음 — 보강 필요) |
| `cost_predictions` | 181 | F2 예측 결과 + F8 사후 검증 (`error_pct`) |
| `audit_log` | **0** | F10 (스키마 존재, 미사용 → M2부터 활성화) |
| `ml_model_info` | — | **F8 모델 버전 메타 (신규 만들 필요 없음!)** |
| `notion_export_costs` | — | F4.1 노션 가져오기 보관 |
| `bim_unit_conversions` | — | F1.2.2 단위 변환 |
| `quote_module_catalog`, `quote_option_catalog`, `saved_estimates` | — | F1.1.3 옵션 / F3.2 리포트 |
| `curation_logs` | — | F1.3 정제 규칙 변경 이력 |
| `ifc_jobs` | — | F8 재학습 큐 패턴 참고 |
| `ifc_project_link_reviews`, `partial_ifc_workcode_reviews` | — | F1.3.1 리뷰 워크플로 패턴 참고 |

## 2. 발견된 데이터 품질 이슈 (M0 quality gate 대상)

### 2.1 actual_costs 결측

샘플 1행:
```
actual_quantity = None
unit            = None
unit_price      = None
material_id     = None
total_amount    = 7,860,347   ← 총액만 있음
```

> 영향: F2.1.2 항목별 분해 / F7.1 영향 변수 분석에서 단가·수량이 필요한데 결측.
> 대응: M0 종료 전에 `harness/scripts/profile_actual_costs.py` 로 결측률 측정 →
> 노션 원본에서 보강 가능한 행 추정 → 보강 가이드 작성.

### 2.2 promotion_status enum 불일치

- 스키마 정의: `candidate / validated / promoted / rejected`
- 실제 값: 931행 전부 `approved` ← **스키마에 없는 값**

> 영향: F1 정제 / F2 학습 입력 필터링 로직이 둘 중 어느 enum 을 기준으로 할지 모호.
> 대응: 운영 메인에 enum 통일 요청 (별도 이슈) — 본 폴더는 `approved | promoted` 둘 다 학습 입력으로 받기로 임시 결정.

### 2.3 vendor_name 오염

샘플:
```
vendor_name = '권혁 (https://www.notion.so/...?pvs=21), 주식회사 ㅇㅇㅇ (https://...)'
```

> URL 이 vendor_name 에 끼어 있음. F1 정제 단계에서 정규식으로 분리 + vendor 마스터 후보 분리.

### 2.4 source_ref 형식 비표준

- 스키마 의도: Notion 페이지/블록 ID
- 실제 값: 한글 텍스트 (예: `'비용'`)

> F4.1.1 노션 워크스페이스 연결 후 ETL 재실행 시 정상 ID 로 채워야 함.

### 2.5 loss_factors / unit_prices 부족

- `loss_factors` 6행 / `unit_prices` 18행
- 147 work_codes 대비 커버리지 낮음 → F2 신뢰구간 / F6.1.2 로스율 입력 기본값 부족.

> M0 ~ M1 사이에 보강 계획 필요. 기존 `cost-analysis-program-plan/WORKCODE_MATERIAL_MAPE_PLAN.md` 와 연계.

## 3. 명세서 기능별 활용 매핑

### F1 데이터 정제

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F1.1 자재 원가 추출 | `actual_costs` + `materials` 조인 | 추출 규칙 표 (`cost_extraction_rules` 신규) |
| F1.2.1 동의어 매핑 | **`material_aliases` 그대로 사용** | work_code 별 동의어는 신규 (`work_aliases`) |
| F1.2.2 단위 변환 | `bim_unit_conversions` 그대로 사용 | (없음) |
| F1.3.1 누락/이상치 탐지 | (스크립트만) | `harness/scripts/profile_actual_costs.py` |
| F1.3.2 정제 규칙 편집/재처리 | `curation_logs` 패턴 차용 | `cost_extraction_rules` 버전 관리 |

### F2 예측 모델

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F2.1 예측 실행 | `actual_costs`(학습) + `module_types` + `projects` | `src/predict.py` 어댑터 |
| 예측 결과 보관 | **`cost_predictions` 그대로 사용** (`predicted_total/breakdown/model_version/error_pct`) | (없음) |
| 사후 검증 (KPI) | `cost_predictions.error_pct` 직접 활용 | (없음) |

### F4 업로드

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F4.1 노션 가져오기 | `notion_export_costs` (스테이징) → `actual_costs` (정규) | `agents/notion_etl.py` 재사용 |
| F4.2 엑셀 업로드 | (없음) | `src/excel_loader.py` 신규 |
| F4.2.3 유효성 검사 | (없음) | `harness/scripts/validate_upload.py` 신규 |

### F6 프로젝트 조건

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F6.1 입력 폼 옵션 | `work_codes` + `module_types` + `projects.region` | (없음 — UI 만) |
| F6.1.2 로스율 가정 | `loss_factors` (work_code 별 default) | (없음) |
| F6.2 조건 템플릿 | (없음) | `project_condition_templates` 신규 |

### F7 Explainability

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F7.1.1 영향 변수 랭킹 | `cost_predictions.input_features` (JSON 스냅샷) | `src/explain.py` 신규 |
| F7.1.2 유사 프로젝트 | `cost_predictions.similar_cases` (JSON KNN ID) | `src/explain.py` 신규 |
| 데이터 품질 지표 | `actual_costs` 프로파일 결과 | M0 산출물 활용 |

### F8 학습/버전 관리

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F8.1 재학습 큐 | `ifc_jobs` 패턴 차용 (job 테이블 디자인) | `model_training_jobs` 신규 |
| F8.2 모델 버전 메타 | **`ml_model_info` 그대로 사용** | (없음) |
| F8.2 버전 활성화/롤백 | `ml_model_info` 에 `is_active` 컬럼이 있다는 가정으로 재사용 | (확인 후 없으면 추가) |

### F9 마스터 데이터

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| 공종/자재 마스터 | `work_codes`(147) + `materials`(3,356) | (없음) |
| 동의어 매핑 | `material_aliases`(250) + `work_codes` 트리 | `work_aliases` 신규 |
| 단위 마스터 | `bim_unit_conversions` | `units` 별도 마스터 (검토) |

### F10 데이터 보안 + 감사

| 명세 항목 | 운영 DB 자산 | 신규 필요 |
|---|---|---|
| F10.1 감사 로그 | **`audit_log`(0행, 스키마만) 활성화** | 트리거 또는 미들웨어 |
| F10.1.1 로그 필터/검색 | `audit_log` 인덱스 (`changed_at`, `table_name+record_id`) | 조회 UI |

## 4. 신규 만들 보조 테이블 (정리)

다음만 신규로 필요 — 나머지는 운영 DB 자산 재사용.

| 테이블 | 용도 | 명세서 항목 |
|---|---|---|
| `cost_extraction_rules` | F1.1.1 추출 규칙 + 버전 관리 | F1.1.1, F1.3.2 |
| `work_aliases` | F1.2.1 공종 동의어 (material_aliases 와 동형) | F1.2.1 |
| `project_condition_templates` | F6.2 조건 템플릿 저장 | F6.2 |
| `model_training_jobs` | F8.1 재학습 작업 큐 | F8.1 |
| `users`, `role_permissions`, `user_roles` | F5 사용자/권한 (운영 DB 에 없음) | F5 |
| `ml_model_info.is_active` | F8.2 활성화 (있으면 재사용, 없으면 컬럼 추가) | F8.2 |
| `units` (선택) | F9 단위 마스터 — 현재 `bim_unit_conversions` 로 대체 가능 | F9 (미정) |

스키마 파일은 `harness/sql/` 에 추가.

## 5. 다음 액션

1. `harness/scripts/profile_actual_costs.py` 작성 → §2.1 결측률 정량화 → `harness/reports/actual_costs_profile.json`
2. 운영 메인 측에 `promotion_status` enum 통일 요청 (§2.2)
3. `harness/scripts/clean_vendor_names.py` 작성 → §2.3 vendor 정리 (read-only 이므로 결과만 리포트)
4. `harness/data_contracts/notion_actual_costs.md` 와 `excel_construction.md` 를 본 매핑 기준으로 재작성
5. `docs/MODEL_SPEC.md`, `MASTER_DATA_SPEC.md`, `AUTH_AUDIT_SPEC.md` 의 "신규 작업 항목" 을 본 표로 축소

## 6. 노션 source 검증 (2026-05-09)

운영 DB의 결측·이상 컬럼이 ETL 손실인지 노션 source 자체의 부재인지 확인하기 위해 노션 ExportBlock zip 2개를 직접 점검.

### 6.1 노션 actual cost DB = "지출결의/입금요청"

zip: `9d26bfdc-...ExportBlock-2552712d-...zip` (1.4 MB, nested zip 1단계)

CSV 산출:
- `_all.csv`: 1415행, 34 컬럼 (전체 properties 펼침)
- 기본 CSV: 1415행, 23 컬럼 (기본 view)

핵심 컬럼 결측률·distinct 값:

| 컬럼 | 채워짐 | distinct | 의미 |
|---|---|---|---|
| `프로젝트명_자재명` | 99.2% | 1228+ | 행 title (자재명 포함) |
| `입금액(VAT+)` | 97.5% | 868+ | → `actual_costs.total_amount` |
| `실투입금액(VAT+)` | 97.6% | 742+ | 잔금 차감 후 실투입 |
| `공종` | 94.2% | 31 (+ `미해당` 215행) | → `work_code` 매핑 source |
| `업체명` | 89.8% | 377+ (URL 혼입) | → `vendor_name`, URL 분리 정제 필요 |
| `입금일` | 78.0% | 290+ | → `settlement_date` |
| `유닛하우스 프로젝트` | 76.3% | 16+ projects | → project relation |
| `요청일` | 63.4% | 642+ | 입금일과 보완 |
| **`구분`** | **91.7%** | **4 — `입금완료/진행 전/입금 대기중/검토중`** | **status 컬럼. cost_type 아님** |
| 패키지 / 상위 항목 / 하위 항목 | 3~32% | hierarchy 메타 |

**부재 컬럼**: `actual_quantity`, `unit`, `unit_price`, `material_id` 에 대응하는 노션 속성 **없음**. 단가·수량 정보는 `'세금계산서, 견적서,수량산출서'` (첨부 파일 칸)에 들어있을 가능성 — 직접 파싱 시 별도 작업.

### 6.2 "계산서 발행 요청" DB (참고)

zip: `d602220d-...ExportBlock-26b30a1e-...zip` (47 KB)

`1ae57166-9988-8086-a632-f8e3768ee575` 페이지 = 매출/계산서 발행 측 데이터. 115행, 23 컬럼. 자재 cost 학습엔 부적합 (반대 방향). 동일하게 `구분`은 status, `공종`은 0/115 비어 있음.

### 6.3 결론 / Plan 영향

| 발견 | Plan 영향 |
|---|---|
| 운영 DB 931행 vs 노션 1415행 → 운영 ETL이 ~1/3 손실 | sidecar에서 회수 가능. PLAN R7. |
| 16개 프로젝트 (운영 DB는 LOO에 8개) | 표본 약 2배 → 통계 신뢰도 +. KPI hit-rate 목표 ≥ 12/16. |
| cost_type 컬럼 노션에도 없음 | Q10 A 실패 → Q10 B (work_code 147개 수동 매핑) 강제. |
| 수량/단위/단가 노션에도 없음 | sidecar로 보강 불가. 첨부 파일 파싱 별도 PRD. PLAN R1 재작성. |
| `'공종'` 컬럼 31 distinct, 94.2% 채워짐 | work_code 매핑 source로 충분. |

### 6.4 노션 `경영지원/원가분석/` 폴더 (zip3, e32da8d7-...)

zip3에서 추가 검증된 사실:

- `경영지원/원가분석/<프로젝트명>/제목 없음 *.csv` 16개 — **지출결의 DB의 프로젝트별 sliced view** (자체 데이터 아님, 컬럼은 지출결의의 부분집합).
- 16개 프로젝트 명시 list:
  1. 기흥 쇼룸 (T-12-1)
  2. 밀양시 산외면 남기동길 43-2 15PY (T-15-3)
  3. 용인 수지 에스테라고 카페 1동 (U-6-1)
  4. 용인 수지 에스테라고 카페 2동 (U-6-1)
  5. 밀양 다랑협동조합 쉐어하우스 (S-30)
  6. 청주 루떼르 포레 모델하우스 (S-18)
  7. 제주도 안덕면 서광리 80-5 (H-30)
  8. 청주 상당구 미원면 중리 산 52-13 (T-12)
  9. 강원 홍천군 영귀미면 노천리 산315-9 (T-15)
  10. 농어촌 공사
  11. 화성 쌍학리
  12. 금산 추부면
  13. 서산
  14. 성남 수정구
  15. 용인 남곡리
  16. 테스트베드
- `경영지원/고객 업체 DB/업체DB ...csv` — **F9 vendor 마스터 source 후보**. 지출결의 `업체명` 컬럼의 387 distinct (URL 혼입)을 이 DB로 정규화 가능. F9 master data 보강 작업에서 노션 import 경로로 활용.
- 사용자 작업 흐름은 노션 `경영지원/원가분석/<프로젝트>` 페이지에서 시작 — F6 프로젝트 조건 입력 UI 디자인 시 참고.
