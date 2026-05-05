# 데이터 계약서: bim_quantities

BIM 객체별 물량 데이터다.

## 필수 컬럼

| 표준 컬럼 | 설명 |
|---|---|
| project_id | 프로젝트/현장 ID |
| element_guid | BIM 객체 GUID |
| category | BIM 카테고리 |
| quantity | 물량 |
| unit | 단위 |

## 권장 컬럼

| 표준 컬럼 | 설명 |
|---|---|
| family_name | BIM 패밀리명 |
| type_name | BIM 타입명 |
| level | 층/레벨 |
| zone | 구역 |
| material_name_raw | BIM 원본 자재명 |
| work_item_raw | BIM 원본 공종명 |
| raw_properties | 원본 속성 JSON |

## 검증 규칙

- `element_guid`는 프로젝트 내에서 유일해야 한다.
- `quantity`는 0보다 커야 한다.
- `unit`이 없으면 원가 적용에서 제외한다.
- 자재/공종 매핑이 확정되지 않으면 원가 계산에서 제외한다.

