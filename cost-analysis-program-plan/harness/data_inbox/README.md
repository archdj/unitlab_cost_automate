# data_inbox

여기에 실제 데이터 또는 익명화 샘플 데이터를 넣는다.

권장 파일명:

```text
payments.csv
bim_quantities.csv
materials.csv
vendors.csv
contracts.csv
invoices.csv
```

첫 번째 검증 스크립트는 CSV 기준으로 동작한다.

Excel, IFC, ERP export 파일은 원본 보관은 가능하지만, 1차 컬럼 검증을 하려면 CSV로 변환한 샘플이 필요하다.

원본 데이터를 바로 넣기 어렵다면 다음 방식으로 익명화한다.

- 업체명: `vendor-001`, `vendor-002`
- 프로젝트명: `project-001`
- 금액: 실제 비율은 유지하되 배율 적용
- 계약/증빙 번호: 임의 ID로 치환

