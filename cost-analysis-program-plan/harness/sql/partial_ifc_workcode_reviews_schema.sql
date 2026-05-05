-- Partial IFC work-code review schema.
-- These rows are candidates only; do not use them in total estimate until approved.
CREATE TABLE IF NOT EXISTS partial_ifc_workcode_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ifc_file_id INTEGER NOT NULL REFERENCES ifc_files(ifc_file_id),
    project_code TEXT,
    module_code TEXT,
    normalized_work_code TEXT NOT NULL,
    bim_unit TEXT,
    partial_use_status TEXT NOT NULL,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    actual_amount INTEGER,
    bim_quantity REAL,
    actual_amount_per_bim_quantity REAL,
    estimated_target_unit TEXT,
    estimated_quantity REAL,
    estimated_amount_per_unit REAL,
    estimation_source TEXT,
    cost_types TEXT,
    reason TEXT,
    reviewer TEXT,
    notes TEXT,
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_partial_ifc_workcode_unique_pending
    ON partial_ifc_workcode_reviews(ifc_file_id, normalized_work_code, bim_unit, approval_status);

CREATE INDEX IF NOT EXISTS idx_partial_ifc_workcode_status
    ON partial_ifc_workcode_reviews(approval_status);

