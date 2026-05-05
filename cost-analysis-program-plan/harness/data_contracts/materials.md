# 데이터 계약서: materials

자재 표준 DB다.

## 필수 컬럼

| 표준 컬럼 | 설명 |
|---|---|
| material_id | 자재 ID |
| material_name | 표준 자재명 |
| unit | 표준 단위 |

## 권장 컬럼

| 표준 컬럼 | 설명 |
|---|---|
| standard_code | 표준 자재 코드 |
| spec | 규격 |
| category | 자재 분류 |
| aliases | 별칭 |
| manufacturer | 제조사 |

## 검증 규칙

- `material_id`는 중복되면 안 된다.
- `material_name`과 `unit`은 비어 있으면 안 된다.
- 같은 자재명이 서로 다른 단위를 갖는 경우 검토 대상으로 표시한다.

