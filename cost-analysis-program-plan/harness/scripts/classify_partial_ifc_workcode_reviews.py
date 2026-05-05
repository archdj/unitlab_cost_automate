from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
REPORT = ROOT / "cost-analysis-program-plan" / "harness" / "reports" / "partial_ifc_workcode_classification.json"

MIN_APPROVED_SAMPLES = 2
MAX_RATIO_FROM_APPROVED_MEDIAN = 3.0
MIN_RATIO_FROM_APPROVED_MEDIAN = 0.2


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def conversion_lookup(con: sqlite3.Connection) -> dict[tuple, dict]:
    return {
        (r["ifc_element_type"], r["normalized_work_code"], r["source_unit"]): {
            "target_unit": r["target_unit"],
            "multiplier": float(r["multiplier"]),
            "source_note": r["source_note"],
        }
        for r in con.execute(
            "SELECT ifc_element_type, normalized_work_code, source_unit, target_unit, multiplier, source_note FROM bim_unit_conversions"
        )
    }


def estimate_quantity(
    con: sqlite3.Connection,
    ifc_file_id: int,
    normalized_work_code: str,
    bim_unit: str | None,
    work_unit: str | None,
    maps: dict[int, dict],
    conversions: dict[tuple, dict],
) -> dict | None:
    """Sum BIM lines for this (ifc_file_id, normalized_work_code, bim_unit) bucket
    and convert each (ifc_element_type, source_unit) to work_unit using lookup.
    Returns None if no usable conversion exists or target units disagree."""
    if not work_unit:
        return None
    rows = con.execute(
        """
        SELECT b.ifc_element_type, b.unit AS source_unit, SUM(b.quantity) qty
        FROM bim_quantities b
        WHERE b.ifc_file_id = ?
        GROUP BY b.ifc_element_type, b.unit
        """,
        (ifc_file_id,),
    ).fetchall()

    total_qty = 0.0
    sources: list[str] = []
    matched = 0
    for r in rows:
        if bim_unit is not None and r["source_unit"] != bim_unit:
            continue
        conv = conversions.get((r["ifc_element_type"], normalized_work_code, r["source_unit"]))
        if conv is None:
            continue
        if conv["target_unit"] != work_unit:
            continue
        total_qty += float(r["qty"] or 0) * conv["multiplier"]
        sources.append(conv["source_note"])
        matched += 1

    if matched == 0 or total_qty <= 0:
        return None
    return {
        "target_unit": work_unit,
        "estimated_quantity": round(total_qty, 4),
        "estimation_source": "; ".join(sorted(set(sources))),
        "matched_element_lines": matched,
    }


def workcode_maps(con: sqlite3.Connection) -> dict[int, dict]:
    rows = [dict(r) for r in con.execute(
        "SELECT work_code_id, work_code, parent_code_id, level, category, work_name_ko FROM work_codes"
    ).fetchall()]
    by_id = {row["work_code_id"]: row for row in rows}
    cache: dict[int, dict] = {}

    def normalized(row_id: int) -> dict:
        if row_id in cache:
            return cache[row_id]
        cur = by_id[row_id]
        while cur["level"] > 2 and cur.get("parent_code_id") and by_id.get(cur["parent_code_id"]):
            cur = by_id[cur["parent_code_id"]]
        cache[row_id] = cur
        return cur

    return {
        row_id: {
            **row,
            "normalized_work_code": normalized(row_id)["work_code"],
            "normalized_work_name": normalized(row_id)["work_name_ko"],
        }
        for row_id, row in by_id.items()
    }


def aggregate_actual(con: sqlite3.Connection, project_id: int, maps: dict[int, dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in con.execute(
        "SELECT work_code_id, SUM(total_amount) amount FROM actual_costs WHERE project_id=? GROUP BY work_code_id",
        (project_id,),
    ):
        key = maps[row["work_code_id"]]["normalized_work_code"]
        out[key] = out.get(key, 0) + int(row["amount"] or 0)
    return out


def aggregate_bim(con: sqlite3.Connection, ifc_file_id: int, maps: dict[int, dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in con.execute(
        "SELECT work_code_id, SUM(quantity) quantity FROM bim_quantities WHERE ifc_file_id=? GROUP BY work_code_id",
        (ifc_file_id,),
    ):
        key = maps[row["work_code_id"]]["normalized_work_code"]
        out[key] = out.get(key, 0.0) + float(row["quantity"] or 0)
    return out


def approved_benchmarks(con: sqlite3.Connection, maps: dict[int, dict]) -> dict[str, dict]:
    cases = con.execute(
        """
        SELECT f.ifc_file_id, f.project_id, p.project_code
        FROM ifc_project_link_reviews r
        JOIN ifc_files f ON r.ifc_file_id = f.ifc_file_id
        JOIN projects p ON f.project_id = p.project_id
        WHERE r.approval_status = 'approved'
        """
    ).fetchall()
    values: dict[str, list[dict]] = {}
    for case in cases:
        actual = aggregate_actual(con, case["project_id"], maps)
        bim = aggregate_bim(con, case["ifc_file_id"], maps)
        for code in sorted(set(actual) & set(bim)):
            if bim[code] <= 0 or actual[code] <= 0:
                continue
            values.setdefault(code, []).append({
                "project_code": case["project_code"],
                "amount_per_bim_quantity": actual[code] / bim[code],
                "actual_amount": actual[code],
                "bim_quantity": bim[code],
            })
    out = {}
    for code, samples in values.items():
        rates = [s["amount_per_bim_quantity"] for s in samples]
        out[code] = {
            "sample_count": len(samples),
            "median_amount_per_bim_quantity": median(rates),
            "min_amount_per_bim_quantity": min(rates),
            "max_amount_per_bim_quantity": max(rates),
            "samples": samples,
        }
    return out


def pending_partials(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        """
        SELECT p.review_id, p.ifc_file_id, p.project_code, p.module_code,
               p.normalized_work_code, p.bim_unit, p.actual_amount, p.bim_quantity,
               p.actual_amount_per_bim_quantity, p.cost_types, p.reason,
               p.partial_use_status,
               w.unit AS workcode_definition_unit,
               l.approval_status AS ifc_link_status
        FROM partial_ifc_workcode_reviews p
        JOIN ifc_project_link_reviews l ON p.ifc_file_id = l.ifc_file_id
        LEFT JOIN work_codes w ON w.work_code = p.normalized_work_code
        WHERE p.approval_status = 'pending'
        ORDER BY p.actual_amount DESC
        """
    ).fetchall()]


def classify(row: dict, benchmark: dict | None, estimate: dict | None = None) -> dict:
    wc_unit = row.get("workcode_definition_unit")
    bim_unit = row.get("bim_unit")
    unit_mismatch = bool(wc_unit and bim_unit and wc_unit != bim_unit)
    mixed_source = row.get("partial_use_status") == "needs_unit_review"

    if (mixed_source or unit_mismatch) and estimate and row["actual_amount"]:
        status = "estimated_partial"
        reason = (
            f"estimated quantity {estimate['estimated_quantity']} {estimate['target_unit']} from "
            f"{estimate['matched_element_lines']} BIM element line(s) using default conversions"
        )
        return {
            "review_id": row["review_id"],
            "ifc_file_id": row["ifc_file_id"],
            "project_code": row["project_code"],
            "module_code": row["module_code"],
            "normalized_work_code": row["normalized_work_code"],
            "bim_unit": bim_unit,
            "actual_amount": row["actual_amount"],
            "bim_quantity": row["bim_quantity"],
            "actual_amount_per_bim_quantity": row["actual_amount_per_bim_quantity"],
            "ifc_link_status": row["ifc_link_status"],
            "estimated_target_unit": estimate["target_unit"],
            "estimated_quantity": estimate["estimated_quantity"],
            "estimated_amount_per_unit": round(row["actual_amount"] / estimate["estimated_quantity"], 2),
            "estimation_source": estimate["estimation_source"],
            "classification": status,
            "reason": reason,
            "benchmark": benchmark,
        }

    if mixed_source:
        status = "needs_unit_review"
        reason = row.get("reason") or "BIM units mixed for this work code"
    elif unit_mismatch:
        status = "needs_unit_review"
        reason = f"BIM unit '{bim_unit}' does not match defined unit '{wc_unit}' and no conversion available"
    elif row["bim_quantity"] is None or row["bim_quantity"] <= 0:
        status = "rejected"
        reason = "no BIM quantity"
    elif row["actual_amount"] is None or row["actual_amount"] <= 0:
        status = "rejected"
        reason = "no actual amount"
    elif row["ifc_link_status"] == "needs_source_file":
        status = "rejected"
        reason = "source IFC is not verified"
    elif not benchmark or benchmark["sample_count"] < MIN_APPROVED_SAMPLES:
        status = "needs_benchmark"
        reason = "not enough approved benchmark samples for this work code"
    else:
        rate = float(row["actual_amount_per_bim_quantity"])
        med = float(benchmark["median_amount_per_bim_quantity"])
        ratio = rate / med if med else 0
        if MIN_RATIO_FROM_APPROVED_MEDIAN <= ratio <= MAX_RATIO_FROM_APPROVED_MEDIAN:
            status = "approved_partial"
            reason = "within approved benchmark range"
        else:
            status = "needs_rate_review"
            reason = f"rate ratio {ratio:.2f} outside allowed benchmark range"

    return {
        "review_id": row["review_id"],
        "ifc_file_id": row["ifc_file_id"],
        "project_code": row["project_code"],
        "module_code": row["module_code"],
        "normalized_work_code": row["normalized_work_code"],
        "bim_unit": row.get("bim_unit"),
        "actual_amount": row["actual_amount"],
        "bim_quantity": row["bim_quantity"],
        "actual_amount_per_bim_quantity": row["actual_amount_per_bim_quantity"],
        "ifc_link_status": row["ifc_link_status"],
        "estimated_target_unit": None,
        "estimated_quantity": None,
        "estimated_amount_per_unit": None,
        "estimation_source": None,
        "classification": status,
        "reason": reason,
        "benchmark": benchmark,
    }


def apply(con: sqlite3.Connection, classifications: list[dict]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    for item in classifications:
        con.execute(
            """
            UPDATE partial_ifc_workcode_reviews
               SET approval_status = ?,
                   reviewer = COALESCE(NULLIF(reviewer, ''), 'harness'),
                   notes = ?,
                   reviewed_at = ?,
                   estimated_target_unit = ?,
                   estimated_quantity = ?,
                   estimated_amount_per_unit = ?,
                   estimation_source = ?
             WHERE review_id = ?
            """,
            (
                item["classification"],
                item["reason"],
                now,
                item.get("estimated_target_unit"),
                item.get("estimated_quantity"),
                item.get("estimated_amount_per_unit"),
                item.get("estimation_source"),
                item["review_id"],
            ),
        )


def main() -> None:
    con = connect()
    maps = workcode_maps(con)
    benchmarks = approved_benchmarks(con, maps)
    conversions = conversion_lookup(con)

    classifications = []
    for row in pending_partials(con):
        estimate = estimate_quantity(
            con,
            row["ifc_file_id"],
            row["normalized_work_code"],
            row.get("bim_unit"),
            row.get("workcode_definition_unit"),
            maps,
            conversions,
        )
        classifications.append(
            classify(row, benchmarks.get(row["normalized_work_code"]), estimate)
        )
    try:
        apply(con, classifications)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    summary: dict[str, int] = {}
    amount: dict[str, int] = {}
    for item in classifications:
        summary[item["classification"]] = summary.get(item["classification"], 0) + 1
        amount[item["classification"]] = amount.get(item["classification"], 0) + int(item["actual_amount"] or 0)
    report = {
        "summary": summary,
        "amount_by_status": amount,
        "rules": {
            "min_approved_samples": MIN_APPROVED_SAMPLES,
            "allowed_rate_ratio": [MIN_RATIO_FROM_APPROVED_MEDIAN, MAX_RATIO_FROM_APPROVED_MEDIAN],
        },
        "classifications": classifications,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": summary, "amount_by_status": amount}, ensure_ascii=False, indent=2))
    print(str(REPORT))


if __name__ == "__main__":
    main()
