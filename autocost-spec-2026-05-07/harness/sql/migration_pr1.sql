-- PR-1: 운영 cost_analysis.db 흡수 마이그레이션 — schema 변경 + 기존 데이터 정규화.
-- 적용 순서:
--   1. (BACKUP) 운영 DB 사전 백업 (cost_analysis.before_pr1.<datestamp>.db)
--   2. 본 SQL 적용 (DDL ALTER + 데이터 UPDATE)
--   3. harness/scripts/migrate_sidecar_to_op.py 실행 (projects 메타 백필)
--   4. agents/notion_etl.py 패치 적용 (notion_etl_patch.md 참조)
--
-- Idempotency: 모든 ALTER는 IF NOT EXISTS (sqlite는 직접 지원 안 하므로 PRAGMA로 우회 — 적용 시점에 컬럼 존재 확인).
-- Reversibility: 백업본 복원으로 rollback. ALTER 컬럼 자체 DROP은 SQLite 제약 (테이블 재생성 필요).

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. actual_costs 컬럼 추가
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE actual_costs ADD COLUMN cost_type TEXT;
ALTER TABLE actual_costs ADD COLUMN package   TEXT;

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. actual_costs.cost_type 정규화 백필
--    기존 source_ref가 노션 '선택' 한글 값을 담고 있음 (재료/노무/경비/...).
--    표준 enum (MAT/LAB/EXP/MIXED/ETC/EXCL/RECUR/OTHER)으로 정규화.
--
--    참고: 운영 ETL이 향후 source_ref를 진짜 page_id로 회복 시, 본 cost_type
--    컬럼은 별도로 유지되며 ETL이 직접 채움 (notion_etl_patch.md).
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE actual_costs
SET cost_type = CASE TRIM(source_ref)
    WHEN '재료'             THEN 'MAT'
    WHEN '재료비'           THEN 'MAT'
    WHEN '노무'             THEN 'LAB'
    WHEN '노무비'           THEN 'LAB'
    WHEN '경비'             THEN 'EXP'
    WHEN '재료+노무'        THEN 'MIXED'
    WHEN '재료비+노무비'    THEN 'MIXED'
    WHEN '제작+현장설치 비' THEN 'MIXED'
    WHEN '기타'             THEN 'ETC'
    WHEN '합계제외'         THEN 'EXCL'
    WHEN '정기이체'         THEN 'RECUR'
    ELSE 'OTHER'
END
WHERE cost_type IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. projects 메타 컬럼 추가 (NULL allowed; migrate_sidecar_to_op.py가 백필)
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE projects ADD COLUMN progress_stage    TEXT;  -- 시안/인허가/제작 중/현장 설치/준공 대기/완료/...
ALTER TABLE projects ADD COLUMN customer_type     TEXT;  -- B2C / B2B / B2G / B2B 글로벌
ALTER TABLE projects ADD COLUMN permit_type       TEXT;  -- 주택 / 근생 / 숙박 / 야영장 / 쇼룸 / ...
ALTER TABLE projects ADD COLUMN product_type      TEXT;  -- 유닛하우스 / 유닛포인트 / 유닛빌드
ALTER TABLE projects ADD COLUMN contract_stage    TEXT;  -- 초기/협의/계약 진행 중/계약 완료/드롭
ALTER TABLE projects ADD COLUMN module_size_text  TEXT;  -- T-12 / S-30 / U-9 / H-30 / ...

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. 인덱스 (학습 query 가속)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_actual_costs_cost_type ON actual_costs(cost_type);
CREATE INDEX IF NOT EXISTS idx_actual_costs_proj_ct   ON actual_costs(project_id, cost_type);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. 검증 query (수동 실행 — 마이그레이션 직후 결과 확인)
-- ─────────────────────────────────────────────────────────────────────────────
-- SELECT cost_type, COUNT(*) FROM actual_costs GROUP BY cost_type ORDER BY 2 DESC;
--   기대: MAT 483, EXP 156, LAB 142, MIXED 137+1, ETC 12, OTHER (있으면 EOF source_ref 확인)
--
-- SELECT COUNT(*) FROM projects WHERE notion_page_id IS NOT NULL;
--   migrate_sidecar_to_op.py 실행 후 19+ 기대.
