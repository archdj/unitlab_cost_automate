# AI 기반 원가 예측 프로그램 (spec 2026-05-07)

다운로드 폴더 명세서 `AI 기반 원가 예측 프로그램_기능명세서_2026-05-07.md` 기준 기획 묶음.

| | |
|---|---|
| **카테고리** | 생산성 / 업무 |
| **타겟** | 건설/제조 프로젝트 관리자, 원가 분석 담당자 |
| **사용자 역할** | Admin |
| **디바이스** | Web |
| **명세서 작성일** | 2026-05-07 |

> **상태 (2026-05-07)**: M0+M1 MVP 동작. 명세서 §1.5 김대리 시나리오 (모듈 선택 → 예측 → 근거 + 결과 표시) 가 web UI 에서 실행됨.

## 빠른 시작

```powershell
pip install -r requirements.txt

# M0 quality gate (운영 DB 데이터 품질 측정)
python harness/scripts/profile_actual_costs.py
python harness/scripts/measure_alias_coverage.py
python harness/scripts/clean_vendor_names.py

# Web UI + API 서버
python -m uvicorn src.api:app --port 8765
# 브라우저: http://127.0.0.1:8765
```

운영 DB 위치 override: `set AUTOCOST_DB=path\to\cost_analysis.db`.

## 동작 확인 결과 (2026-05-07)

| 항목 | 결과 |
|---|---|
| 운영 DB 연결 | ✅ `actual_costs` 931행 |
| GET /api/modules | ✅ 9개 모듈 (학습 가능 면적 보유) |
| POST /api/predict (T-15-STD ×1) | ✅ 136M원 (CI 120M~155M), breakdown 66행 |
| 근거 패널 (F7) | ✅ top_features 5 / similar_projects 3 / data_quality |
| GET /api/profile, /api/coverage (M0) | ✅ 결측률·매핑 커버리지 정량화 |
| Web UI (HTML/CSS/JS) | ✅ 정적 자산 200 응답 |
| **POST /api/upload (F4 dry-run)** | ✅ CSV/XLSX/노션 ExportBlock zip 자동 인식 + 헤더 매핑 + 검증 |

### F4 업로드 검증 결과 (실제 파일 3종)

| 파일 | 결과 | 매핑된 표준 필드 |
|---|---|---|
| `unitlab-cost-analysis/유닛랩 시공 발주관리 - 발주리스트 (1).csv` (941행) | 562 정상 / 379 거부 | 자재명·수량·단위·업체명·납품일·프로젝트명·규격 |
| `unitlab-cost-analysis/2502_최신 견적서.xlsx` (시트 3) | 갑지 0/66 → "모델내역" 시트 선택 필요 | 첫 시트는 견적서 표지(메타). UI 에서 시트 링크로 재시도 가능 |
| `Downloads/...ExportBlock....zip` (노션) | **1369/1415 정상** | 자동 중첩 zip 풀기 → 입금액·업체명·계산서·프로젝트명 |

운영 DB 는 변경하지 않는다 (read-only). 결과는 응답 JSON 으로만 반환.

### M0 발견 (운영 DB 데이터 품질)

- `actual_quantity / unit / unit_price / material_id / invoice_no` **100% 결측** — `total_amount` 만 있음
- `vendor_name` 87.8% 가 Notion URL 혼입 (예: `'한미운수 (https://www.notion.so/...)'`)
- 모든 931행 `promotion_status='approved'` (스키마 정의 enum 미사용)
- `material_aliases` 250개 있지만 `raw_description` 직매칭 0% — 자재명+동사 형태(`'우레탄판넬 운반비'`) → 룰 강화 필요

---

## 디렉토리

```
autocost-spec-2026-05-07/
├── README.md                       # 이 파일
├── PLAN.md                         # 프로젝트 개요/배경/KPI/리스크
├── ROADMAP.md                      # 10개 기능 → 마일스톤 분배
├── .gitignore
│
├── docs/                           # 기능 묶음별 상세 SPEC
│   ├── OPERATIONAL_DB_MAPPING.md   # ★ 운영 DB 인벤토리 + 명세서 매핑 (M0 산출물)
│   ├── MODEL_SPEC.md               # F2 예측 모델 + F7 Explainability + F8 학습/버전
│   ├── DATA_INGEST_SPEC.md         # F1 정제 + F4 업로드(Notion/Excel)
│   ├── UI_SPEC.md                  # F3 시각화·리포트 + F6 프로젝트 조건 입력
│   ├── MASTER_DATA_SPEC.md         # F9 공종/자재/단위 마스터
│   └── AUTH_AUDIT_SPEC.md          # F5 사용자/권한 + F10 감사 로그
│
├── src/                            # 모델·앱 코드 (M0+M1 구현됨)
│   ├── config.py                   # 운영 DB 경로 + 모델 파라미터
│   ├── db.py                       # read-only DB + 프로파일/커버리지
│   ├── model.py                    # Pool 기반 예측 (v10-notion 패턴)
│   ├── explain.py                  # F7 근거 (영향 변수/유사/품질)
│   ├── loaders.py                  # F4 CSV/XLSX/노션 ExportBlock zip 파서 + 검증
│   ├── api.py                      # FastAPI: /api/health, /modules, /predict, /profile, /coverage, /upload
│   └── web/                        # Admin SPA (vanilla HTML/CSS/JS)
│       ├── index.html
│       ├── app.js
│       └── style.css
│
├── harness/                        # 데이터 정제·검증 일회성 스크립트 묶음
│   ├── README.md
│   ├── scripts/
│   │   ├── profile_actual_costs.py     # M0: 결측·이상치
│   │   ├── measure_alias_coverage.py   # M0: 매핑 커버리지
│   │   └── clean_vendor_names.py       # M0: vendor URL 분리 미리보기
│   ├── sql/                        # 보조 테이블 스키마 (예정)
│   ├── mapping/                    # 동의어/단위 매핑 CSV 템플릿
│   ├── data_contracts/             # 입력 데이터 계약 (notion/excel)
│   └── reports/                    # 검증 결과 JSON 산출물
│
├── reports/                        # 모델 backtest/예측 결과 (예정)
└── requirements.txt                # fastapi / uvicorn / pydantic
```

## 기존 3폴더와의 관계

이 폴더는 명세서 기반 **신규 기획 스캐폴드**다. 운영 코드는 다음 3곳에서 이미 일부 구현되어 있다.

| 명세서 기능 | 기존 구현 위치 |
|---|---|
| F1 데이터 정제 | `cost-analysis-program-plan/harness/scripts/` (profile_data, classify_*) |
| F1·F4 노션 ETL | `unitlab-cost-analysis/agents/notion_etl.py` |
| F2 예측 모델 | `unitlab-notion-cost/src/notion_cost_model.py` (v10.0-notion) |
| F2 backtest | `unitlab-notion-cost/src/backtest.py` (LOO) |
| F4 IFC export 보조 | `cost-analysis-program-plan/BIM_IFC_EXPORT_SETUP.md` |
| F9 마스터 데이터 | `unitlab-cost-analysis/db/migrations/002_seed_work_codes.sql`, `003_unitlab_work_codes.sql` |

→ 신규 작업은 각 SPEC 문서 하단 **작업 항목** 섹션에 정리.

## 다음 단계 (M2 진입 전)

1. **데이터 품질 보강** — actual_costs 의 수량/단위/material_id 결측을 노션 원본에서 보강 (운영 메인 ETL 수정 필요).
2. **alias 매칭 룰 강화** — `raw_description` 의 자재명+동사 패턴을 토큰화해서 `material_aliases` 부분 매칭. F1.2.1 동의어 매핑 UI 와 연계.
3. **F4 노션/엑셀 업로드** — 운영 메인의 `agents/notion_etl.py` 와 새 폴더의 `src/excel_loader.py` (예정) 통합.
4. **F8 모델 버전 관리** — `cost_predictions` 결과를 운영 DB 에 저장 (현재는 메모리만), `ml_model_info` 테이블에 버전 등록.
5. **F5/F10 권한·감사** — 운영 React 와 통합되는 시점에 추가.

[`docs/OPERATIONAL_DB_MAPPING.md`](docs/OPERATIONAL_DB_MAPPING.md) §5 다음 액션 참고.
