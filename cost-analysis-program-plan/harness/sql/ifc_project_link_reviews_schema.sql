-- IFC/Notion alignment review schema. Review and apply manually.
CREATE TABLE IF NOT EXISTS ifc_project_link_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ifc_file_id INTEGER NOT NULL REFERENCES ifc_files(ifc_file_id),
    db_file_name TEXT,
    candidate_file_name TEXT,
    current_project_code TEXT,
    approved_project_code TEXT,
    current_module_code TEXT,
    approved_module_code TEXT,
    approval_status TEXT NOT NULL DEFAULT 'pending',
    reviewer TEXT,
    notes TEXT,
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ifc_review_ifc_file
    ON ifc_project_link_reviews(ifc_file_id);

CREATE INDEX IF NOT EXISTS idx_ifc_review_status
    ON ifc_project_link_reviews(approval_status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ifc_review_unique_pending
    ON ifc_project_link_reviews(ifc_file_id, approval_status);
