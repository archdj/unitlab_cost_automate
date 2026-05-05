"""Auto-calibrate BIM unit conversion multipliers.

For each (normalized_work_code, target_unit) where:
  - a NOTION-source unit_price exists in `target_unit` (treated as baseline)
  - a BIM-source measured unit_price exists in source_unit (≠ target_unit)

we infer a correction ratio:

    desired_estimated_price (target_unit) ≈ NOTION price
    estimated_price = bim_measured_price / weighted_avg_multiplier
    → desired_avg_multiplier = bim_measured_price / NOTION_price
    → scale every contributing multiplier by (desired / current_avg)

Multipliers are scaled in `bim_unit_conversions`, with is_default=0 and a
source_note appended noting the calibration date and source.

Run:

    python cost-analysis-program-plan/harness/scripts/calibrate_bim_unit_conversions.py
    python unitlab-cost-analysis/compute_analytics.py --step 4 --yes

The second command regenerates BIM_ESTIMATED prices using the new multipliers.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def latest_prices(con: sqlite3.Connection) -> dict[tuple[str, str, str], float]:
    """(work_code, source, unit) → unit_price for currently effective rows."""
    out: dict[tuple[str, str, str], float] = {}
    for r in con.execute(
        """
        SELECT wc.work_code, up.source, up.unit, up.unit_price
        FROM unit_prices up
        JOIN work_codes wc ON up.work_code_id = wc.work_code_id
        WHERE up.effective_to IS NULL
        """
    ):
        out[(r[0], r[1], r[2])] = float(r[3] or 0)
    return out


def workcode_unit(con: sqlite3.Connection) -> dict[str, str | None]:
    return {
        r[0]: r[1]
        for r in con.execute("SELECT work_code, unit FROM work_codes")
    }


def matching_conversions(con: sqlite3.Connection, work_code: str, target_unit: str) -> list[dict]:
    return [
        {
            "conversion_id": r[0],
            "ifc_element_type": r[1],
            "source_unit": r[2],
            "multiplier": float(r[3]),
            "source_note": r[4],
            "is_default": int(r[5]),
        }
        for r in con.execute(
            """
            SELECT conversion_id, ifc_element_type, source_unit, multiplier, source_note, is_default
            FROM bim_unit_conversions
            WHERE normalized_work_code = ? AND target_unit = ?
            """,
            (work_code, target_unit),
        )
    ]


def weighted_avg_multiplier(
    con: sqlite3.Connection,
    work_code: str,
    source_unit: str,
    convs: list[dict],
) -> float | None:
    """Mirror step4c: total_target_qty / total_source_qty across all matched element types."""
    if not convs:
        return None
    by_elem = {c["ifc_element_type"]: c["multiplier"] for c in convs if c["source_unit"] == source_unit}
    if not by_elem:
        return None
    total_source = 0.0
    total_target = 0.0
    for r in con.execute(
        """
        SELECT bq.ifc_element_type, SUM(bq.quantity) qty
        FROM bim_quantities bq
        JOIN work_codes wc ON bq.work_code_id = wc.work_code_id
        WHERE bq.unit = ? AND (wc.work_code = ? OR wc.work_code LIKE ?)
        GROUP BY bq.ifc_element_type
        """,
        (source_unit, work_code, work_code + "-%"),
    ):
        elem, qty = r[0], float(r[1] or 0)
        if elem not in by_elem:
            continue
        total_source += qty
        total_target += qty * by_elem[elem]
    if total_source <= 0:
        return None
    return total_target / total_source


def calibrate() -> None:
    con = sqlite3.connect(DB)
    prices = latest_prices(con)
    wc_units = workcode_unit(con)

    # Find calibration candidates:
    # work_code with NOTION price in target_unit AND BIM measured in source_unit (≠ target)
    notion_targets: dict[str, tuple[str, float]] = {}  # work_code → (target_unit, notion_price)
    bim_measured: dict[str, tuple[str, float]] = {}    # work_code → (bim_unit, bim_price)

    for (wc, src, unit), price in prices.items():
        if src == "NOTION" and unit == wc_units.get(wc):
            notion_targets[wc] = (unit, price)
        elif src == "BIM":
            bim_measured[wc] = (unit, price)

    print(f"Calibration candidates: NOTION targets={len(notion_targets)}, BIM measured={len(bim_measured)}")
    print()

    today = date.today().isoformat()
    updated_rows = 0
    skipped: list[tuple[str, str]] = []
    report: list[tuple[str, str, float, float, float, float]] = []

    for wc, (target_unit, notion_price) in sorted(notion_targets.items()):
        if wc not in bim_measured:
            continue
        bim_unit, bim_price = bim_measured[wc]
        if bim_unit == target_unit:
            continue  # nothing to calibrate; already same unit
        if notion_price <= 0 or bim_price <= 0:
            skipped.append((wc, "non-positive price"))
            continue

        convs = matching_conversions(con, wc, target_unit)
        if not convs:
            skipped.append((wc, f"no conversion rows for {wc} {bim_unit}→{target_unit}"))
            continue

        current_avg = weighted_avg_multiplier(con, wc, bim_unit, convs)
        if current_avg is None or current_avg <= 0:
            skipped.append((wc, "could not compute current weighted multiplier"))
            continue

        # estimated_price = bim_price / current_avg
        # we want estimated_price ≈ notion_price → desired_avg = bim_price / notion_price
        desired_avg = bim_price / notion_price
        scale = desired_avg / current_avg

        for c in convs:
            if c["source_unit"] != bim_unit:
                continue
            new_mult = round(c["multiplier"] * scale, 6)
            note = c["source_note"] or ""
            calib_note = f"calibrated {today}: scaled by {scale:.3f} from NOTION {wc} {target_unit} {notion_price:,.0f}"
            new_note = f"{note} | {calib_note}" if note else calib_note
            con.execute(
                """
                UPDATE bim_unit_conversions
                   SET multiplier = ?, source_note = ?, is_default = 0
                 WHERE conversion_id = ?
                """,
                (new_mult, new_note, c["conversion_id"]),
            )
            updated_rows += 1

        report.append((wc, target_unit, current_avg, desired_avg, scale, notion_price))
        print(
            f"  {wc:10} bim={bim_price:>10,.0f}/{bim_unit} → notion={notion_price:>10,.0f}/{target_unit} "
            f"current_avg={current_avg:.4f} desired_avg={desired_avg:.4f} scale={scale:.3f}"
        )

    con.commit()
    con.close()

    print()
    print(f"Updated multiplier rows: {updated_rows}")
    if skipped:
        print(f"Skipped: {len(skipped)}")
        for wc, why in skipped:
            print(f"  - {wc}: {why}")


if __name__ == "__main__":
    calibrate()
