# 유닛랩 노션-only 원가 예측 모델 (v10.0-notion)

IFC 없이 Notion 실원가만으로 동작하는 견적 모델. IFC는 추후 옵션으로 붙임.

## 디렉토리

```
unitlab-notion-cost/
├── README.md
├── docs/
│   └── MODEL_SPEC.md             # 모델 정의·학습·예측 산식
├── src/
│   ├── data_access.py            # 기존 운영 DB(read-only)에서 actual_costs/projects/module_types 로드
│   ├── notion_cost_model.py      # 학습 + 예측 코어
│   ├── backtest.py               # LOO 검증 (총액 / 공종별 / 비용유형별 MAPE)
│   └── server.py                 # FastAPI (선택 — 단독 운영용)
└── reports/                       # backtest 결과 JSON·CSV
```

## 데이터 출처

운영 DB: `C:/Users/PC/unitlab-cost-analysis/db/cost_analysis.db` (read-only)

다음 테이블만 사용:
- `actual_costs` — 실원가 (Notion ETL 결과)
- `projects` — 프로젝트 메타
- `module_types` — 모듈 정의 (등급/평형/면적)
- `project_modules` — 프로젝트 ↔ 모듈 연결
- `work_codes` — 공종 트리

**IFC 관련 테이블은 사용하지 않습니다** (`bim_quantities`, `ifc_files`, `bim_unit_conversions`, `unit_prices` 등).

## 실행

```powershell
# 학습 + 예측 결과 저장
python src/notion_cost_model.py train

# Leave-One-Out backtest
python src/backtest.py

# 단독 API (FastAPI)
python -m uvicorn src.server:app --port 8001
```

## 핵심 차이 (v9.0 vs v10.0-notion)

| 항목 | v9.0-hybrid-ridge (기존) | v10.0-notion (이 폴더) |
|---|---|---|
| 입력 | 면적 + BIM coverage | 면적 + 평형 + 등급 |
| breakdown 단위 | area / option / site / total | **공종 × 비용유형** |
| IFC 필요 여부 | 부분적으로 사용 | **전혀 안 씀** |
| 학습 데이터 | 26개 프로젝트 | 동일 26개 (BIM 유무 무관) |
| 신뢰구간 | 전체 1개 | **공종별 ±X%** |
| 유사 사례 | 없음 | **모듈/평형/등급 유사 weighting** |

## 다음 단계

자세한 설계는 [`docs/MODEL_SPEC.md`](docs/MODEL_SPEC.md) 참고.
