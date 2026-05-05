# 리포트 포맷

## required_columns_report.json

필수 컬럼 누락 여부를 확인한다.

```json
{
  "results": [
    {
      "file": "payments.csv",
      "status": "missing_columns",
      "required_columns": ["payment_id", "project_id"],
      "actual_columns": ["payment_id"],
      "missing_columns": ["project_id"]
    }
  ]
}
```

## data_profile.json

데이터 파일별 컬럼, 샘플 행, 빈 값 상태를 확인한다.

```json
{
  "file_count": 1,
  "profiles": [
    {
      "file": "payments.csv",
      "type": "csv",
      "columns": ["payment_id", "project_id"],
      "sampled_rows": 20,
      "non_empty_in_sample": {
        "payment_id": 20,
        "project_id": 20
      }
    }
  ]
}
```

## calculation_exclusion_report.csv

계산에서 제외된 항목과 사유를 남긴다.

필수 컬럼:

```text
source_type,source_id,reason,detail,required_action
```

예시:

```text
payment,pay-001,missing_quantity,quantity is empty,check source payment row
bim,GUID-001,mapping_candidate,material mapping is not confirmed,review mapping
```

