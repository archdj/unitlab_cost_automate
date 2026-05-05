from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
SCHEMA = ROOT / "cost-analysis-program-plan" / "harness" / "sql" / "bim_unit_conversions_schema.sql"


# Default conversion factors for modular construction (T-15 class units).
# Each row converts (ifc_element_type, source_unit) -> target_unit using `multiplier`.
# All values are coarse domain estimates marked is_default=1; refine per project.
DEFAULTS: list[tuple] = [
    # IfcWall -> FIN-PANEL (sandwich panel m2): module side panel ~6 m2 per element
    ("IfcWall", "FIN-PANEL", "EA", "m2", 6.0,
     "default: module side panel ~6 m2 per IfcWall element"),
    # IfcWallStandardCase -> FIN-LGS (LGS partition m2): interior partition ~2.5 m2/element
    ("IfcWallStandardCase", "FIN-LGS", "EA", "m2", 2.5,
     "default: interior LGS partition ~2.5 m2 per element"),
    # IfcCovering -> FIN-INS (insulation m2): one face of insulation ~5 m2
    ("IfcCovering", "FIN-INS", "EA", "m2", 5.0,
     "default: insulation per face ~5 m2 per IfcCovering"),
    # IfcSlab -> FIN-PANEL or STR-ST: slab panel ~floor footprint share
    ("IfcSlab", "FIN-PANEL", "EA", "m2", 12.0,
     "default: slab panel ~12 m2 per IfcSlab element"),

    # IfcBeam -> STR-ST (steel ton): per element ~30 kg
    ("IfcBeam", "STR-ST", "EA", "ton", 0.030,
     "default: steel beam ~30 kg per element"),
    # IfcBeam length -> STR-ST ton: H-150x75 unit weight ~14 kg/m
    ("IfcBeam", "STR-ST", "m", "ton", 0.014,
     "default: H-150x75 unit weight ~14 kg/m"),
    # IfcColumn -> STR-ST ton: H-150x150 ~31.5 kg/m * 2.5 m = ~79 kg
    ("IfcColumn", "STR-ST", "EA", "ton", 0.079,
     "default: steel column H-150 ~79 kg per element"),
    # IfcMember -> STR-ST ton: small truss/brace ~20 kg
    ("IfcMember", "STR-ST", "EA", "ton", 0.020,
     "default: secondary member ~20 kg per element"),
    # IfcPlate -> STR-ST ton: connection plate ~10 kg
    ("IfcPlate", "STR-ST", "EA", "ton", 0.010,
     "default: connection plate ~10 kg per element"),
    # IfcSlab -> STR-ST ton (deck plate alternative): ~100 kg per slab
    ("IfcSlab", "STR-ST", "EA", "ton", 0.100,
     "default: deck slab ~100 kg per element"),

    # IfcFlowTerminal -> MEP-ELEC LS: 100 fixtures ~= 1 LS bundle
    ("IfcFlowTerminal", "MEP-ELEC", "EA", "LS", 0.01,
     "default: 100 electrical terminals ~= 1 LS bundle"),

    # IfcDoor / IfcWindow already EA; pass-through (informational only)
    # IfcFurnishingElement -> FUR (no defined unit) — skipped.
]


def main() -> None:
    schema = SCHEMA.read_text(encoding="utf-8")
    con = sqlite3.connect(DB)
    inserted = 0
    skipped = 0
    try:
        con.executescript(schema)
        for row in DEFAULTS:
            ifc_type, work_code, src, tgt, mult, note = row
            exists = con.execute(
                """
                SELECT 1 FROM bim_unit_conversions
                WHERE ifc_element_type=? AND normalized_work_code=? AND source_unit=? AND target_unit=?
                """,
                (ifc_type, work_code, src, tgt),
            ).fetchone()
            if exists:
                skipped += 1
                continue
            con.execute(
                """
                INSERT INTO bim_unit_conversions(
                    ifc_element_type, normalized_work_code, source_unit, target_unit,
                    multiplier, source_note, is_default
                ) VALUES(?,?,?,?,?,?,1)
                """,
                (ifc_type, work_code, src, tgt, mult, note),
            )
            inserted += 1
        con.commit()
    finally:
        con.close()
    print({"inserted": inserted, "skipped": skipped})


if __name__ == "__main__":
    main()
