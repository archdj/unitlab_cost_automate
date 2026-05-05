# reports

검증 스크립트와 분석 스크립트의 결과가 저장되는 폴더다.

생성 예정 파일:

```text
data_profile.json
required_columns_report.json
mapping_status_report.json
calculation_exclusion_report.json
unit_price_report.csv
bim_cost_application_report.csv
```

리포트 해석 원칙:

- `missing_file`: 해당 파일이 아직 없음
- `missing_columns`: 필수 컬럼 누락
- `not_profiled`: 아직 해당 파일 형식의 프로파일러 없음
- `unmatched`: 매핑 불가
- `candidate`: 계산 제외, 검토 필요
- `confirmed`: 계산 가능
- `rule_matched`: 계산 가능, 단 규칙명 기록 필수

