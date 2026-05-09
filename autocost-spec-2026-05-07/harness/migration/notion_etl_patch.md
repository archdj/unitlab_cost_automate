# PR-1 Notion ETL 패치 명세

대상: 운영 메인 repo (`archdj/unitlab` `원가분석-프로그램` branch) 의 `agents/notion_etl.py`.

본 명세는 PR-1 schema 변경(migration_pr1.sql) + 1회 백필(migrate_sidecar_to_op.py) 후, 향후 ETL 실행이 새 컬럼을 정확히 채우도록 변경할 사항을 정의한다.

---

## 변경 1 — `actual_costs.cost_type` 직접 적재

### 현재 동작 (문제)
운영 ETL이 노션 '선택' 컬럼 한글 값을 `actual_costs.source_ref`에 적재 중. 이는:
- `source_ref`의 본래 의도(노션 page_id)와 어긋남
- 한글이라 학습 query에서 직접 사용 어려움

### 변경 후
1. `source_ref`는 **노션 page_id** 로 회복 — `notion_page.id` (UUID 형태) 적재.
2. 노션 '선택' 한글 → `cost_type` 신 컬럼에 enum 정규화 적재.

### 매핑 테이블 (`COST_TYPE_MAP`)
```python
COST_TYPE_MAP = {
    "재료비":           "MAT",
    "재료":             "MAT",   # 운영 기존 변형
    "노무비":           "LAB",
    "노무":             "LAB",
    "경비":             "EXP",
    "재료비+노무비":    "MIXED",
    "재료+노무":        "MIXED",
    "제작+현장설치 비": "MIXED",
    "기타":             "ETC",
    "합계제외":         "EXCL",
    "정기이체":         "RECUR",
}
```
unknown 한글 값 → `"OTHER"` (logging 권장).

source: `unitlab_autocost/autocost-spec-2026-05-07/harness/scripts/build_enriched_db.py:COST_TYPE_MAP`.

---

## 변경 2 — `actual_costs.package` 추가 적재

노션 '패키지' select 속성 → `package` 컬럼에 그대로 (예: `데크`, `어닝`, `IOT`, `커튼`, `처마`, `방충망`, `프라이버시`, `베리어프리`, `공조`).

값 없을 시 NULL.

---

## 변경 3 — `projects.notion_page_id` + 메타 6 컬럼 적재

### 트리거
ETL이 신규 프로젝트 노션 페이지를 처리할 때, 또는 정기 sync 시.

### 적재 source — 노션 영업 프로젝트 DB
- collection ID: `78b1f791-7b1e-4bf0-b3f4-5e6f47e7a01d`
- 페이지별 properties → 운영 projects 컬럼 매핑:

| 노션 property | 운영 컬럼 | 비고 |
|---|---|---|
| (페이지 id) | `notion_page_id` | UUID format |
| `진행 단계` (select) | `progress_stage` | `시안/인허가 도서/착공 도서/제작 대기/제작 중/현장 설치/준공 대기/완료/제품개발 필요/제안` |
| `고객 유형` (multi-select) | `customer_type` | `B2C/B2B/B2G/B2B 글로벌`. multi이면 콤마 join |
| `인허가 유형` (multi-select) | `permit_type` | `주택/근생/숙박/세컨하우스/야영장/쇼룸/단지 분양/체류형쉼터` 등 |
| `제품 유형` (multi-select) | `product_type` | `유닛하우스/유닛포인트/유닛빌드` |
| `계약 단계` (select) | `contract_stage` | `초기/협의/계약 진행 중/계약 완료/드롭` |
| `프로젝트 규모` (text) | `module_size_text` | `T-12 / S-30 / U-9 / H-30 / S-15 / 10평 : 20 EA` 등 |

### 매칭
신규 프로젝트는 `notion_page_id` 가 unique key. 기존 projects 행의 `notion_page_id`로 매칭(없으면 신규 INSERT).

---

## 변경 4 — `actual_costs.source_ref` 회복

PR-1 마이그레이션에서 `source_ref`의 한글 값을 신 `cost_type` 컬럼으로 정규화 복사함. 향후 ETL은 `source_ref`에 **노션 page_id** 적재 (table actual_costs에서 receipt_id가 별도 UUID이므로 source_ref는 노션 본래 ID 의도 회복).

> **호환성 주의**: 운영 ETL이 source_ref를 cost_type 의도로 잘못 사용한 코드 path가 있다면 그 path들도 함께 수정. 마이그레이션 후엔 `cost_type` 컬럼이 정확.

---

## 변경 5 — `LEARNABLE_COST_TYPES` / 학습 입력 필터

학습 query에서 cost_type 필터 적용 위치:

```python
# unitlab_autocost/unitlab-notion-cost/src/data_access.py:LEARNABLE_COST_TYPES (PR-2에서 흡수)
LEARNABLE_COST_TYPES = ("MAT", "LAB", "EXP", "MIXED", "ETC")  # RECUR/EXCL/OTHER 제외
```

`promotion_status` enum 통일과 별개로, `cost_type IN (...)` 필터가 학습 데이터 정의의 일부.

---

## 변경 6 — 추가 데이터 source

운영 ETL이 현재 처리 안 하는 노션 DB (PR-1.5 이후 통합 가능):

| 노션 collection | 용도 |
|---|---|
| `a662b420-258d-4b04-bea4-abc29a4b0cbd` (고객/업체 DB) | vendors 마스터 — PR-1.5에서 통합 |
| `1b057166-9988-810c-975b-000bd8946838` (계산서 발행 요청) | 매출 계산서 — PR-2 이후 검토 |

---

## 검증 (ETL 변경 후)

```sql
-- cost_type 분포 확인 — 운영 DB와 sidecar(autocost_enriched.db) 동일해야:
SELECT cost_type, COUNT(*) FROM actual_costs GROUP BY cost_type ORDER BY 2 DESC;
-- 기대 (sidecar 기준): MAT 607, EXP 199, MIXED 172 (162+10), LAB 173, ETC 125, RECUR 48, EXCL 50

-- projects 메타 채워진 비율:
SELECT COUNT(*) FROM projects WHERE notion_page_id IS NOT NULL;
-- 기대: 16+ (학습 가능 프로젝트 + 영업 중 프로젝트)
```

---

## Out of scope (별도 PR)

- PR-1.5: vendors 마스터 신설 + actual_costs.vendor_id FK
- PR-2: 모델 코드(`unitlab-notion-cost/src/`) → 운영 메인 흡수
- PR-3: 프론트 통합 + `/api/refresh-data` 이전
- PR-4: unitlab_autocost archive
