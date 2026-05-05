# unitlab_autocost

유닛랩 모듈러 건축 자동 견적·원가분석 시스템.

운영 메인 시스템(`archdj/unitlab` repo의 `원가분석-프로그램` branch)을 보완하는 **격리된 모델 코드 + 기획·진단 자료** 묶음.

---

## 디렉토리

```
unitlab_autocost/
├── unitlab-notion-cost/       # v10.0-notion 모델 (IFC 없이 동작)
│   ├── src/                   # 학습/예측/백테스트/서버 코어
│   ├── docs/MODEL_SPEC.md     # 모델 명세
│   └── README.md
│
└── cost-analysis-program-plan/  # 기획·진단 + 데이터 정제 harness
    ├── *.md                   # BIM_IFC_EXPORT_SETUP, ROADMAP_*, WORKCODE_MATERIAL_MAPE_PLAN 등
    └── harness/               # audit / calibrate / classify / seed 스크립트
        ├── scripts/
        ├── sql/               # 보조 테이블 스키마
        ├── data_contracts/
        └── mapping/
```

## 메인 운영 repo

운영 백엔드(FastAPI)·프론트엔드(React)·운영 DB는 별도 repo:

> https://github.com/archdj/unitlab.git (branch `원가분석-프로그램`)

이 repo의 코드는 운영 DB(`unitlab-cost-analysis/db/cost_analysis.db`)를 **read-only**로 참조한다.

## 빠른 시작

### v10.0-notion 모델 (IFC 없이 견적)
```powershell
cd unitlab-notion-cost
python src/notion_cost_model.py predict --module T-15-STD --quantity 1
python src/backtest.py                                # LOO 검증
python -m uvicorn src.server:app --port 8001          # 단독 API
```

### IFC quantity audit
```powershell
cd cost-analysis-program-plan
python harness/scripts/audit_ifc_quantities.py path\to\file.ifc
```

### NOTION 단가 기반 자동 보정
```powershell
python harness/scripts/calibrate_bim_unit_conversions.py
```

## 핵심 결과 (2026-05-05 기준)

- **v10.0-notion LOO**: 중앙값 13.2%, ±20% 5/8 (n=8)
- **v11.0-ensemble (v9-knn × v10 conditional)**: 중앙값 13.0%, ±20% 6/8
- **IFC quantity 충실도**: 새 9개 IFC verdict 99.3% (이전 15.8%)
- **단위 mismatch**: 19건 → 0건 (NOTION m² 잘못된 자동 산출 제거)

## 다음 단계 후보

자세한 내용은:
- [`cost-analysis-program-plan/ROADMAP_WORKCODE_ACCURACY.md`](cost-analysis-program-plan/ROADMAP_WORKCODE_ACCURACY.md)
- [`cost-analysis-program-plan/WORKCODE_MATERIAL_MAPE_PLAN.md`](cost-analysis-program-plan/WORKCODE_MATERIAL_MAPE_PLAN.md)
- [`cost-analysis-program-plan/BIM_IFC_EXPORT_SETUP.md`](cost-analysis-program-plan/BIM_IFC_EXPORT_SETUP.md)
