-- BIM unit conversion lookup.
-- Used to estimate a defined unit (m2/ton/m3/LS) from a raw BIM unit (EA/m)
-- when the IFC export lacks explicit IfcElementQuantity values.
-- Estimates are coarse and require domain review before being trusted as evidence.
CREATE TABLE IF NOT EXISTS bim_unit_conversions (
    conversion_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ifc_element_type TEXT NOT NULL,
    normalized_work_code TEXT NOT NULL,
    source_unit TEXT NOT NULL,
    target_unit TEXT NOT NULL,
    multiplier REAL NOT NULL,
    source_note TEXT,
    is_default INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bim_unit_conv_unique
    ON bim_unit_conversions(ifc_element_type, normalized_work_code, source_unit, target_unit);
