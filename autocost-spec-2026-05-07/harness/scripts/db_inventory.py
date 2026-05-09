"""DB inventory dump.

운영 DB(`unitlab-cost-analysis/db/cost_analysis.db`)와 sidecar
(`autocost-spec-2026-05-07/harness/data/autocost_enriched.db`) 두 개의
schema·row count·결측률을 한 번에 dump.

산출:
- docs/db_inventory_2026-05-10.md (사람용 종합 리포트)
- docs/db_inventory_2026-05-10.csv (테이블/컬럼 단위 sheet)

사용:
    python autocost-spec-2026-05-07/harness/scripts/db_inventory.py
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OP_DB = REPO_ROOT.parent / "unitlab-cost-analysis" / "db" / "cost_analysis.db"
SIDECAR_DB = REPO_ROOT / "autocost-spec-2026-05-07" / "harness" / "data" / "autocost_enriched.db"
OUT_MD = REPO_ROOT / "docs" / "db_inventory_2026-05-10.md"
OUT_CSV = REPO_ROOT / "docs" / "db_inventory_2026-05-10.csv"


def connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def list_tables(con: sqlite3.Connection) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]


def table_columns(con: sqlite3.Connection, table: str) -> list[dict]:
    return [{
        "cid": r["cid"],
        "name": r["name"],
        "type": r["type"],
        "notnull": bool(r["notnull"]),
        "default": r["dflt_value"],
        "pk": bool(r["pk"]),
    } for r in con.execute(f"PRAGMA table_info({table})")]


def row_count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def null_rate(con: sqlite3.Connection, table: str, col: str, total: int) -> float | None:
    if total == 0:
        return None
    n = con.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL").fetchone()[0]
    return round(n / total, 4)


def file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 2) if path.exists() else 0.0


def collect_db(label: str, path: Path) -> dict:
    if not path.exists():
        return {"label": label, "path": str(path), "exists": False, "tables": []}
    con = connect_ro(path)
    tables = []
    for t in list_tables(con):
        cols = table_columns(con, t)
        n = row_count(con, t)
        for c in cols:
            c["null_rate"] = null_rate(con, t, c["name"], n) if n > 0 else None
        tables.append({"name": t, "rows": n, "columns": cols})
    con.close()
    return {
        "label": label,
        "path": str(path),
        "exists": True,
        "size_mb": file_size_mb(path),
        "tables": tables,
    }


def render_md(dbs: list[dict]) -> str:
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# DB 구성 인벤토리 (2026-05-10)",
        "",
        f"_생성: {today} · `harness/scripts/db_inventory.py` 자동 생성_",
        "",
        "이 repo는 SQLite 두 개에 의존한다:",
        "",
        "| 라벨 | 경로 | 역할 |",
        "|---|---|---|",
        "| **운영 DB** | `unitlab-cost-analysis/db/cost_analysis.db` (sister directory) | 진실 source. PR-1 schema 변경 적용 완료 (cost_type/package/projects 메타). |",
        "| **sidecar enriched** | `autocost-spec-2026-05-07/harness/data/autocost_enriched.db` | 노션 zip 1차 재파싱. 운영 ETL 결손 회수 (931→1420 cost rows). 운영 DB 통합 후 폐기 예정. |",
        "",
        "운영 DB binary는 git에서 제외(`.gitignore`의 `*.db`). schema/migration은 `unitlab-cost-analysis/db/migrations/`에서 관리.",
        "",
        "---",
        "",
    ]
    for db in dbs:
        lines.append(f"## {db['label']}")
        lines.append("")
        if not db["exists"]:
            lines.append(f"⚠️ 파일 없음: `{db['path']}`")
            lines.append("")
            continue
        lines.append(f"- 경로: `{db['path']}`")
        lines.append(f"- 크기: {db['size_mb']} MB")
        lines.append(f"- 테이블 수: {len(db['tables'])}")
        lines.append("")
        lines.append("### 테이블 요약")
        lines.append("")
        lines.append("| 테이블 | 행 수 | 컬럼 수 | 비고 |")
        lines.append("|---|---:|---:|---|")
        for t in db["tables"]:
            note = ""
            if t["rows"] == 0:
                note = "(빈 테이블)"
            lines.append(f"| `{t['name']}` | {t['rows']:,} | {len(t['columns'])} | {note} |")
        lines.append("")
        lines.append("### 컬럼 상세 (NULL률 ≥ 50%만)")
        lines.append("")
        any_high = False
        for t in db["tables"]:
            if t["rows"] == 0:
                continue
            high_null = [c for c in t["columns"] if c["null_rate"] is not None and c["null_rate"] >= 0.5]
            if not high_null:
                continue
            any_high = True
            lines.append(f"#### `{t['name']}` ({t['rows']:,} 행)")
            lines.append("")
            lines.append("| 컬럼 | 타입 | NULL률 |")
            lines.append("|---|---|---:|")
            for c in sorted(high_null, key=lambda x: -x["null_rate"]):
                lines.append(f"| `{c['name']}` | {c['type'] or '?'} | {c['null_rate']*100:.1f}% |")
            lines.append("")
        if not any_high:
            lines.append("없음.")
            lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## CSV (테이블 × 컬럼 평면)")
    lines.append("")
    lines.append("같은 데이터를 `db_inventory_2026-05-10.csv`에 저장. 컬럼:")
    lines.append("")
    lines.append("`db, table, rows, col_idx, col_name, col_type, notnull, pk, null_rate`")
    return "\n".join(lines) + "\n"


def render_csv(dbs: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["db", "table", "rows", "col_idx", "col_name", "col_type", "notnull", "pk", "null_rate"])
        for db in dbs:
            if not db["exists"]:
                continue
            for t in db["tables"]:
                for c in t["columns"]:
                    w.writerow([
                        db["label"],
                        t["name"],
                        t["rows"],
                        c["cid"],
                        c["name"],
                        c["type"] or "",
                        int(c["notnull"]),
                        int(c["pk"]),
                        f"{c['null_rate']:.4f}" if c["null_rate"] is not None else "",
                    ])


def main() -> None:
    dbs = [
        collect_db("운영 DB (cost_analysis.db)", OP_DB),
        collect_db("sidecar enriched (autocost_enriched.db)", SIDECAR_DB),
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_md(dbs), encoding="utf-8")
    render_csv(dbs, OUT_CSV)
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_CSV}")
    for db in dbs:
        if db["exists"]:
            tables = len(db["tables"])
            rows = sum(t["rows"] for t in db["tables"])
            print(f"  {db['label']}: {tables} tables, {rows:,} rows total, {db['size_mb']} MB")
        else:
            print(f"  {db['label']}: missing")


if __name__ == "__main__":
    main()
