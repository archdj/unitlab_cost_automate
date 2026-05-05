from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_INBOX = ROOT / "data_inbox"
REPORTS = ROOT / "reports"


def sniff_csv(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        columns = reader.fieldnames or []
        rows = []
        for idx, row in enumerate(reader):
            if idx < 20:
                rows.append(row)
            else:
                break

    non_empty = {col: 0 for col in columns}
    for row in rows:
        for col in columns:
            if str(row.get(col, "")).strip():
                non_empty[col] += 1

    return {
        "file": path.name,
        "type": "csv",
        "columns": columns,
        "sampled_rows": len(rows),
        "non_empty_in_sample": non_empty,
        "sample_rows": rows[:5],
    }


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)

    profiles = []
    for path in sorted(DATA_INBOX.glob("*")):
        if path.suffix.lower() == ".csv":
            profiles.append(sniff_csv(path))
        else:
            profiles.append({
                "file": path.name,
                "type": path.suffix.lower().lstrip(".") or "unknown",
                "status": "not_profiled",
                "note": "Only CSV profiling is implemented in this first harness.",
            })

    output = {
        "data_inbox": str(DATA_INBOX),
        "file_count": len(profiles),
        "profiles": profiles,
    }

    out_path = REPORTS / "data_profile.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

