-- autocost_enriched.db — sidecar SQLite with write access.
-- 운영 DB cost_analysis.db는 read-only 유지. 학습 데이터 재구성 + write 필요한 메타는 여기.
-- 노션 ExportBlock zip + MCP 보완으로 채워진다 (harness/scripts/build_enriched_db.py).

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. actual_costs_enriched : 1420 cost rows from 노션 입금요청 DB
--    cost_type 컬럼이 노션의 '선택' 속성 (재료비/노무비/경비/MIXED/...) 직접 매핑.
--    수량/단위/단가는 노션 source 자체에 부재 → 컬럼에 두지 않음.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS actual_costs_enriched (
  enriched_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  notion_page_id   TEXT UNIQUE,                  -- 노션 행 page id (32hex 또는 dashed UUID)
  raw_title        TEXT,                          -- '프로젝트명_자재명' (노션 title)
  cost_type        TEXT NOT NULL,                 -- 'MAT' / 'LAB' / 'EXP' / 'MIXED' / 'ETC' / 'EXCL' / 'RECUR' / 'OTHER'
  cost_type_raw    TEXT,                          -- 노션 '선택' 원본 값 (재료비/노무비/...)
  work_code_text   TEXT,                          -- 노션 '공종' 원본 값 ('01. 골조' 등). work_codes 매핑은 학습 시.
  total_amount     INTEGER,                       -- 노션 '입금액(VAT+)' 원화 (정수)
  settlement_date  TEXT,                          -- 노션 '입금일' (YYYY-MM-DD or NULL)
  request_date     TEXT,                          -- 노션 '요청일' (YYYY-MM-DD or NULL)
  status_code      TEXT,                          -- 노션 '구분' (입금완료/진행 전/입금 대기중/검토중)
  project_notion_id TEXT,                         -- 노션 '유닛하우스 프로젝트' relation page id (FK→projects_master)
  project_name_raw TEXT,                          -- 노션 relation render (디버깅용)
  vendor_notion_id TEXT,                          -- 노션 '업체명' relation page id (FK→vendors_master)
  vendor_name_raw  TEXT,                          -- 노션 relation render (URL 혼입 가능)
  package          TEXT,                          -- 노션 '패키지' (선택, 예: '데크', '커튼')
  parent_notion_id TEXT,                          -- 노션 '상위 항목' relation
  remark           TEXT,                          -- 노션 '비고'
  source_zip_id    TEXT,                          -- 빌드 시 사용된 zip (재현용)
  fetched_at       TEXT DEFAULT (datetime('now')) -- ETL 실행 시각
);
CREATE INDEX IF NOT EXISTS idx_ace_cost_type        ON actual_costs_enriched(cost_type);
CREATE INDEX IF NOT EXISTS idx_ace_project          ON actual_costs_enriched(project_notion_id);
CREATE INDEX IF NOT EXISTS idx_ace_work_code_text   ON actual_costs_enriched(work_code_text);
CREATE INDEX IF NOT EXISTS idx_ace_status           ON actual_costs_enriched(status_code);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. vendors_master : 노션 '고객/업체 DB' 429행
--    업체 정보 정규화. 입금요청.업체명 relation의 target.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendors_master (
  vendor_notion_id TEXT PRIMARY KEY,
  name             TEXT,
  business_no      TEXT,
  bank_account     TEXT,
  bank_name        TEXT,
  account_holder   TEXT,
  category         TEXT,                          -- 노션의 업체 구분 (있다면)
  raw_payload      TEXT,                          -- 원본 row JSON (lossless)
  fetched_at       TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. projects_master : 노션 '영업 프로젝트' DB의 16개 unitlab 프로젝트
--    M0에서는 입금요청에서 추출한 distinct project_notion_id + name으로 stub.
--    상세 메타(설치주소/평형/모듈타입)는 후속으로 MCP fetch.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects_master (
  project_notion_id TEXT PRIMARY KEY,
  name              TEXT,
  module_code_hint  TEXT,                         -- name에서 파싱한 모듈 코드 (예: 'T-12', 'S-30')
  address           TEXT,                          -- 후속 MCP fetch
  customer_type     TEXT,                          -- B2G/B2C/B2B
  product_type      TEXT,                          -- 유닛하우스/유닛포인트/유닛빌드
  permit_type       TEXT,                          -- 인허가 유형
  contract_stage    TEXT,                          -- 계약 단계
  progress_stage    TEXT,                          -- 진행 단계
  cost_row_count    INTEGER,                      -- 입금요청에서 join된 행수 (요약)
  cost_total        INTEGER,                      -- 입금요청 총액 합 (요약)
  raw_payload       TEXT,                          -- MCP fetch 원본 JSON
  fetched_at        TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. model_versions : F8 모델 버전 메타 (sidecar 동안). 흡수 시 ml_model_info로 이전.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_versions (
  version_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  version           TEXT UNIQUE,
  trained_at        TEXT DEFAULT (datetime('now')),
  data_range_start  TEXT,
  data_range_end    TEXT,
  metrics_json      TEXT,                          -- LOO MAPE total + cost_type별 4종 + hit-rate
  status            TEXT CHECK(status IN ('active','archived','failed')),
  created_by        TEXT DEFAULT 'admin',
  notes             TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_one_active
  ON model_versions(status) WHERE status = 'active';

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. etl_runs : refresh-data endpoint 실행 이력 (Q14)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS etl_runs (
  run_id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ran_at           TEXT DEFAULT (datetime('now')),
  source           TEXT,                            -- 'zip:<id>' or 'mcp'
  added_rows       INTEGER,
  updated_rows     INTEGER,
  removed_rows     INTEGER,
  model_version_before TEXT,
  model_version_after  TEXT,
  material_mape_before FLOAT,
  material_mape_after  FLOAT,
  activated        INTEGER,                        -- 0/1
  message          TEXT
);
