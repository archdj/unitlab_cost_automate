from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_INBOX = ROOT / "data_inbox"
REPORTS = ROOT / "reports"


REQUIRED_COLUMNS = {
    "payments.csv": [
        "payment_id",
        "project_id",
        "vendor_id",
        "payment_date",
        "item_name_raw",
        "quantity",
        "unit",
        "amount_basis",
    ],
    "bim_quantities.csv": [
        "project_id",
        "element_guid",
        "category",
        "quantity",
        "unit",
    ],
    "materials.csv": [
        "material_id",
        "material_name",
        "unit",
    ],
    "vendors.csv": [
        "vendor_id",
        "vendor_name",
    ],
}


def read_columns(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames or []


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    results = []

    for filename, required in REQUIRED_COLUMNS.items():
        path = DATA_INBOX / filename
        if not path.exists():
            results.append({
                "file": filename,
                "status": "missing_file",
                "required_columns": required,
                "actual_columns": [],
                "missing_columns": required,
            })
            continue

        actual = read_columns(path)
        actual_set = set(actual)
        missing = [col for col in required if col not in actual_set]
        results.append({
            "file": filename,
            "status": "ok" if not missing else "missing_columns",
            "required_columns": required,
            "actual_columns": actual,
            "missing_columns": missing,
        })

    out_path = REPORTS / "required_columns_report.json"
    out_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

