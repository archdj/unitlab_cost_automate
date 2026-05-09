# 데이터 정제·검증 하네스

명세서 F1 (정제), F4 (업로드), F9 (마스터 매핑) 을 책임지는 일회성 스크립트 묶음.

`cost-analysis-program-plan/harness/` 의 패턴을 그대로 따른다 (실제 결제 데이터 우선, 미매핑은 계산 제외).

## 폴더 구조

```text
harness/
├── README.md
├── data_contracts/     # 입력 데이터 필수/권장 컬럼
│   ├── notion_actual_costs.md
│   └── excel_construction.md
├── mapping/            # 동의어/단위 매핑 CSV 템플릿
│   ├── work_synonym_template.csv
│   └── unit_conversion_template.csv
├── reports/            # 검증/프로파일 결과 (gitignore 대상)
├── scripts/            # 정제·검증·시드 스크립트
└── sql/                # 보조 테이블 스키마
```

## 사용 순서

1. `data_contracts/` 의 필수 컬럼과 실제 노션·엑셀 컬럼을 비교한다.
2. `mapping/` 의 템플릿을 채운다 (`mapping_status` 는 `confirmed` 만 자동 적용).
3. `scripts/profile_ingested_data.py` 로 데이터 구조와 누락/이상치를 본다.
4. `reports/` 에 출력된 누락 컬럼·매핑 불가 항목을 검토한다.
5. `confirmed` 매핑만 F2 예측 입력으로 사용한다.

## 원칙

- 실제 결제 데이터가 없는 단가는 실적 단가로 인정하지 않는다.
- 매핑 상태가 `confirmed` 가 아니면 자동 반영하지 않는다.
- 모든 계산 결과는 결제 ID, 프로젝트 ID, 자재 ID, 모델 버전까지 역추적 가능해야 한다.
