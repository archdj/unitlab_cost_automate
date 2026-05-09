"""Build sidecar autocost_enriched.db from Notion ExportBlock zip.

운영 DB cost_analysis.db는 read-only 유지. 노션 source의 1420 입금요청 + 429 vendor + 16 projects를
별도 SQLite에 적재해 학습 데이터로 사용한다.

사용:
    python harness/scripts/build_enriched_db.py [zip_path]
    # zip_path 생략 시 Downloads 폴더에서 가장 최근 ExportBlock-*.zip 자동 선택.

Schema: harness/sql/enriched_schema.sql
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "harness" / "sql" / "enriched_schema.sql"
DEFAULT_DB = REPO_ROOT / "harness" / "data" / "autocost_enriched.db"
DEFAULT_DOWNLOADS = Path.home() / "Downloads"


# ─────────────────────────────────────────────────────────────────────────────
# 노션 '선택' (cost_type) 정규화
# ─────────────────────────────────────────────────────────────────────────────
COST_TYPE_MAP = {
    "재료비":         "MAT",
    "노무비":         "LAB",
    "경비":           "EXP",
    "재료비+노무비":  "MIXED",
    "제작+현장설치 비": "MIXED",
    "기타":           "ETC",
    "합계제외":       "EXCL",
    "정기이체":       "RECUR",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
RE_PAGE_ID = re.compile(r"notion\.so/[\w\-]*?-?([0-9a-f]{32})", re.I)
RE_AMOUNT  = re.compile(r"[-\d,]+")
RE_DATE    = re.compile(r"^(\d{4})/(\d{2})/(\d{2})")


def find_zip(arg: str | None) -> Path:
    if arg:
        p = Path(arg)
        if not p.exists():
            sys.exit(f"zip not found: {p}")
        return p
    # auto: pick newest ExportBlock-*.zip in Downloads, prefer ones with most rows
    candidates = sorted(
        DEFAULT_DOWNLOADS.glob("*ExportBlock*.zip"),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if not candidates:
        sys.exit(f"no ExportBlock-*.zip in {DEFAULT_DOWNLOADS}")
    return candidates[0]


def open_inner_zip(outer: Path) -> zipfile.ZipFile:
    """ExportBlock zip은 nested zip 1단계. 내부 zip을 메모리에 열어 반환."""
    with zipfile.ZipFile(outer) as z1:
        inner_names = [n for n in z1.namelist() if n.lower().endswith(".zip")]
        if not inner_names:
            # Some exports don't nest
            return zipfile.ZipFile(outer)
        return zipfile.ZipFile(io.BytesIO(z1.read(inner_names[0])))


def find_csv(z: zipfile.ZipFile, predicate) -> str | None:
    csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
    matches = [n for n in csvs if predicate(n)]
    if not matches:
        return None
    # prefer _all.csv (all properties)
    for n in matches:
        if n.endswith("_all.csv"):
            return n
    return matches[0]


def parse_amount(s: str) -> int | None:
    s = (s or "").strip()
    if not s:
        return None
    m = RE_AMOUNT.search(s.replace("₩", ""))
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_date(s: str) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    m = RE_DATE.match(s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def parse_relation(cell: str) -> tuple[str | None, str | None]:
    """노션 relation 셀은 'Name (https://www.notion.so/<slug>-<id>?pvs=21)' 형태.
    여러 relation이 ', '로 join된 경우 첫 번째 사용."""
    cell = (cell or "").strip()
    if not cell:
        return None, None
    # 첫 번째 'Name (URL)' pair만 추출. URL이 없으면 전체 텍스트가 name.
    m = re.match(r"^(.+?) \((http[^)]+)\)", cell)
    if m:
        name = m.group(1)
        page_id_match = RE_PAGE_ID.search(m.group(2))
    else:
        name = cell
        page_id_match = None
    page_id = None
    if page_id_match:
        raw = page_id_match.group(1)
        page_id = f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    return name or None, page_id


def parse_module_hint(project_name: str) -> str | None:
    """프로젝트명에서 모듈 코드 추출. 예: '청주 루떼르 포레 모델하우스 S-18' → 'S-18'."""
    if not project_name:
        return None
    # pattern: T-12, T-15, T-15-3, S-18, S-30, U-6, U-6-1, H-30, U-10
    m = re.search(r"\b([THSUH]-\d+(?:-\d+)?)\b", project_name)
    return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Cost rows
# ─────────────────────────────────────────────────────────────────────────────
def parse_cost_csv(z: zipfile.ZipFile) -> list[dict]:
    name = find_csv(z, lambda n: "입금요청" in n)
    if not name:
        return []
    text = z.read(name).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for idx, row in enumerate(reader):
        sel = (row.get("선택") or "").strip()
        cost_type = COST_TYPE_MAP.get(sel, "OTHER")
        proj_name, proj_id = parse_relation(row.get("유닛하우스 프로젝트", ""))
        vend_name, vend_id = parse_relation(row.get("업체명", ""))
        parent_id = None
        if row.get("상위 항목"):
            _, parent_id = parse_relation(row["상위 항목"])
        out.append({
            "title":            (row.get("프로젝트명_자재명") or "").strip(),
            "cost_type":        cost_type,
            "cost_type_raw":    sel or None,
            "work_code_text":   (row.get("공종") or "").strip() or None,
            "total_amount":     parse_amount(row.get("입금액(VAT+)") or ""),
            "settlement_date":  parse_date(row.get("입금일") or ""),
            "request_date":     parse_date(row.get("요청일") or ""),
            "status_code":      (row.get("구분") or "").strip() or None,
            "project_notion_id": proj_id,
            "project_name_raw": proj_name,
            "vendor_notion_id": vend_id,
            "vendor_name_raw":  vend_name,
            "package":          (row.get("패키지") or "").strip() or None,
            "parent_notion_id": parent_id,
            "remark":           (row.get("비고") or "").strip() or None,
            "csv_row_index":    idx,
        })
    return out


def insert_costs(con: sqlite3.Connection, rows: list[dict], zip_id: str) -> int:
    con.execute("DELETE FROM actual_costs_enriched")
    # surrogate page id: zip_id + csv_row_index (stable within a zip)
    payload = [
        (
            f"{zip_id}:{r['csv_row_index']:05d}", r["title"], r["cost_type"], r["cost_type_raw"], r["work_code_text"],
            r["total_amount"], r["settlement_date"], r["request_date"], r["status_code"],
            r["project_notion_id"], r["project_name_raw"],
            r["vendor_notion_id"], r["vendor_name_raw"],
            r["package"], r["parent_notion_id"], r["remark"], zip_id,
        )
        for r in rows
    ]
    con.executemany(
        """
        INSERT INTO actual_costs_enriched (
            notion_page_id, raw_title, cost_type, cost_type_raw, work_code_text,
            total_amount, settlement_date, request_date, status_code,
            project_notion_id, project_name_raw,
            vendor_notion_id, vendor_name_raw,
            package, parent_notion_id, remark, source_zip_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        payload,
    )
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Vendors
# ─────────────────────────────────────────────────────────────────────────────
def parse_vendor_csv(z: zipfile.ZipFile) -> list[dict]:
    name = find_csv(z, lambda n: "업체DB" in n or "업체 DB" in n or "고객" in n)
    if not name:
        return []
    text = z.read(name).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        # vendor's own page id is encoded in nothing useful from CSV.
        # Use 'Name'(title col) + idx for surrogate. Title col is usually first.
        title_col = next(iter(row.keys()))
        title = (row.get(title_col) or "").strip()
        # Try to extract page id from a URL column if any (usually no URL in vendor CSV)
        out.append({
            "name":           title,
            "business_no":    (row.get("사업자번호") or row.get("주민등록번호/사업자 번호") or "").strip() or None,
            "bank_account":   (row.get("계좌번호") or "").strip() or None,
            "bank_name":      (row.get("은행명") or "").strip() or None,
            "account_holder": (row.get("통장명") or "").strip() or None,
            "category":       (row.get("구분") or row.get("업체 구분") or "").strip() or None,
            "raw_payload":    json.dumps({k: v for k, v in row.items() if v}, ensure_ascii=False),
        })
    return out


def insert_vendors(con: sqlite3.Connection, rows: list[dict], zip_id: str) -> int:
    con.execute("DELETE FROM vendors_master")
    payload = [
        (f"{zip_id}:vendor:{idx:05d}", r["name"], r["business_no"], r["bank_account"], r["bank_name"],
         r["account_holder"], r["category"], r["raw_payload"])
        for idx, r in enumerate(rows)
    ]
    con.executemany(
        """
        INSERT INTO vendors_master (
            vendor_notion_id, name, business_no, bank_account, bank_name,
            account_holder, category, raw_payload
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        payload,
    )
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Projects (derived from cost rows)
# ─────────────────────────────────────────────────────────────────────────────
def insert_projects(con: sqlite3.Connection, cost_rows: list[dict]) -> int:
    con.execute("DELETE FROM projects_master")
    by_id = defaultdict(lambda: {"name": None, "rows": 0, "total": 0})
    for r in cost_rows:
        pid = r["project_notion_id"]
        if not pid:
            continue
        by_id[pid]["name"] = by_id[pid]["name"] or r["project_name_raw"]
        by_id[pid]["rows"] += 1
        by_id[pid]["total"] += r["total_amount"] or 0
    con.executemany(
        """
        INSERT INTO projects_master (
            project_notion_id, name, module_code_hint, cost_row_count, cost_total
        ) VALUES (?,?,?,?,?)
        """,
        [
            (pid, agg["name"], parse_module_hint(agg["name"] or ""), agg["rows"], agg["total"])
            for pid, agg in by_id.items()
        ],
    )
    return len(by_id)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def init_schema(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    return con


def short_zip_id(zip_path: Path) -> str:
    # First 8 chars of the trailing collection UUID in zip filename
    m = re.search(r"ExportBlock-([0-9a-f]{8})", zip_path.name, re.I)
    return m.group(1) if m else zip_path.stem[:8]


def main() -> int:
    zip_path = find_zip(sys.argv[1] if len(sys.argv) > 1 else None)
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB
    print(f"zip:    {zip_path}")
    print(f"db:     {db_path}")
    print()

    z = open_inner_zip(zip_path)
    cost_rows = parse_cost_csv(z)
    vendor_rows = parse_vendor_csv(z)

    if not cost_rows:
        print("WARN: 입금요청 CSV not found in zip")
        return 1

    print(f"parsed:")
    print(f"  cost rows:   {len(cost_rows)}")
    print(f"  vendor rows: {len(vendor_rows)}")
    proj_ids = {r['project_notion_id'] for r in cost_rows if r['project_notion_id']}
    print(f"  distinct projects (from cost): {len(proj_ids)}")
    print()

    con = init_schema(db_path)
    zip_id = short_zip_id(zip_path)
    n_costs    = insert_costs(con, cost_rows, zip_id)
    n_vendors  = insert_vendors(con, vendor_rows, zip_id)
    n_projects = insert_projects(con, cost_rows)
    con.commit()

    # Verification queries
    print("=== verification ===")
    print("by cost_type:")
    for ct, cnt, total in con.execute(
        "SELECT cost_type, COUNT(*) c, COALESCE(SUM(total_amount),0) t "
        "FROM actual_costs_enriched GROUP BY cost_type ORDER BY t DESC"
    ):
        print(f"  {ct:8} {cnt:>5} rows  ₩{total/1e6:>10.1f}M")

    print()
    print("by status_code:")
    for st, cnt in con.execute(
        "SELECT COALESCE(status_code,'(null)'), COUNT(*) FROM actual_costs_enriched "
        "GROUP BY status_code ORDER BY 2 DESC"
    ):
        print(f"  {st:14} {cnt}")

    print()
    print("top 5 projects by total:")
    for name, rows, total, mod in con.execute(
        "SELECT name, cost_row_count, cost_total, module_code_hint "
        "FROM projects_master ORDER BY cost_total DESC LIMIT 5"
    ):
        name_short = (name or '')[:40]
        print(f"  ₩{total/1e6:>7.1f}M  {rows:>4} rows  {mod or '?':6} {name_short}")

    print()
    print(f"summary: costs={n_costs}, vendors={n_vendors}, projects={n_projects}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
