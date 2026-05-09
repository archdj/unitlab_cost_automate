"""PR-1 마이그레이션 — sidecar projects_master → 운영 projects 메타/notion_page_id 백필.

전제: harness/sql/migration_pr1.sql 이미 적용 (운영 projects에 메타 컬럼 추가됨).

매칭 전략:
  1. project_name 정규화(공백·특수문자 제거 + lowercase) 후 exact match.
  2. fallback: substring containment (둘 중 하나가 다른 하나에 포함).
  3. fallback: MANUAL_OVERRIDES (도메인 지식 기반 수동 매핑).

unmatched는 콘솔 출력 + reports/migration_pr1_unmatched.json. 운영 팀 수동 검토.

DRY-RUN 기본. 실 적용은 --apply.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_DB = REPO_ROOT / "harness" / "data" / "autocost_enriched.db"
OPERATIONAL_DB = Path("C:/Users/PC/unitlab-cost-analysis/db/cost_analysis.db")
REPORT_PATH = REPO_ROOT / "harness" / "reports" / "migration_pr1_unmatched.json"


# 도메인 지식 기반 수동 매핑 (자동 normalize 매칭 실패 케이스).
# 적용 전 운영 팀 검토 권장.
MANUAL_OVERRIDES: dict[str, str] = {
    # sidecar project_notion_id → 운영 project_name (정확)
    # "6595c62c-a870-4ebc-89e3-acff6053a3dc": "밀양 다랑협동조합 쉐어하우스 (S-30)",
    #   ↑ 노션은 'S-33' 이름, 운영은 '(S-30)'. 같은 프로젝트로 알려졌으나 운영 팀 확인 필요.
}

# Skip from migration (학습/운영 통합 비대상)
SKIP_NOTION_IDS = {
    "30d57166-9988-809f-a333-c7242e4dd293",  # 테스트베드 (R&D)
    # "제목 없음" placeholder는 자동 매칭 실패 → unmatched로 분류
}


def norm(s: str | None) -> str:
    """공백·하이픈·괄호·언더스코어 등 제거 + lowercase."""
    if not s:
        return ""
    return re.sub(r"[\s\-\(\)_\[\]]+", "", s).lower()


def find_op_match(si_name: str, op_by_norm: dict[str, dict]) -> dict | None:
    sn = norm(si_name)
    if sn in op_by_norm:
        return op_by_norm[sn]
    # substring containment (두 normalized 이름 길이 ≥ 8 보호)
    for op_norm, op_row in op_by_norm.items():
        if op_norm and len(op_norm) >= 8 and (op_norm in sn or sn in op_norm):
            return op_row
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실 적용 (없으면 dry-run)")
    parser.add_argument("--op-db", default=str(OPERATIONAL_DB), help="운영 DB 경로")
    args = parser.parse_args()

    op_db = Path(args.op_db)
    if not op_db.exists():
        sys.exit(f"운영 DB 없음: {op_db}")
    if not SIDECAR_DB.exists():
        sys.exit(f"sidecar DB 없음: {SIDECAR_DB}")

    si = sqlite3.connect(SIDECAR_DB)
    si.row_factory = sqlite3.Row

    op_uri = f"file:{op_db.as_posix()}" + ("" if args.apply else "?mode=ro")
    op = sqlite3.connect(op_uri, uri=True)
    op.row_factory = sqlite3.Row

    # 운영 PR-1 DDL 적용 여부 검증
    cols = {r["name"] for r in op.execute("PRAGMA table_info(projects)")}
    required = {"progress_stage", "customer_type", "permit_type", "product_type",
                "contract_stage", "module_size_text", "notion_page_id"}
    missing = required - cols
    if missing:
        sys.exit(f"운영 projects에 PR-1 컬럼 부재: {missing}\nmigration_pr1.sql 먼저 적용 필요.")

    op_projects = list(op.execute(
        "SELECT project_id, project_code, project_name, notion_page_id FROM projects"
    ))
    op_by_norm = {norm(r["project_name"]): dict(r) for r in op_projects}
    op_by_name = {r["project_name"]: dict(r) for r in op_projects}

    si_projects = list(si.execute("""
        SELECT project_notion_id, name, raw_payload, module_code_hint
        FROM projects_master ORDER BY cost_total DESC
    """))

    matched_rows = []
    unmatched_rows = []
    for r in si_projects:
        nid = r["project_notion_id"]
        if nid in SKIP_NOTION_IDS:
            continue
        if nid in MANUAL_OVERRIDES:
            op_match = op_by_name.get(MANUAL_OVERRIDES[nid])
        else:
            op_match = find_op_match(r["name"], op_by_norm)
        if not op_match:
            unmatched_rows.append({"project_notion_id": nid, "sidecar_name": r["name"]})
            continue

        try:
            payload = json.loads(r["raw_payload"]) if r["raw_payload"] else {}
        except (TypeError, json.JSONDecodeError):
            payload = {}

        matched_rows.append({
            "op_project_id":  op_match["project_id"],
            "op_project_name": op_match["project_name"],
            "si_name":        r["name"],
            "notion_page_id": nid,
            "progress_stage": payload.get("progress_stage"),
            "customer_type":  payload.get("customer_type"),
            "permit_type":    payload.get("permit_type"),
            "product_type":   payload.get("product_type"),
            "contract_stage": payload.get("contract_stage"),
            "module_size_text": payload.get("module_size") or r["module_code_hint"],
        })

    # 출력
    print(f"sidecar projects:  {len(si_projects)}")
    print(f"  skipped (R&D/placeholder): {sum(1 for r in si_projects if r['project_notion_id'] in SKIP_NOTION_IDS)}")
    print(f"  matched: {len(matched_rows)}")
    print(f"  unmatched: {len(unmatched_rows)}")
    print()
    if unmatched_rows:
        print("=== UNMATCHED (수동 검토 필요) ===")
        for u in unmatched_rows:
            print(f"  {u['project_notion_id']}  {u['sidecar_name']}")
        print(f"  (저장: {REPORT_PATH})")
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(unmatched_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print()

    if not args.apply:
        print("=== DRY-RUN (--apply 없음). 적용 예시 5건: ===")
        for m in matched_rows[:5]:
            print(f"  UPDATE projects #{m['op_project_id']:>3} ({m['op_project_name'][:35]}):")
            print(f"    notion_page_id   = '{m['notion_page_id']}'")
            print(f"    progress_stage   = {m['progress_stage']!r}")
            print(f"    customer_type    = {m['customer_type']!r}")
            print(f"    permit_type      = {m['permit_type']!r}")
            print(f"    product_type     = {m['product_type']!r}")
            print(f"    module_size_text = {m['module_size_text']!r}")
        print()
        print(f"적용하려면 --apply 추가. 적용 전 운영 DB 백업 필수.")
        return 0

    # 적용
    cur = op.cursor()
    for m in matched_rows:
        cur.execute("""
            UPDATE projects
               SET notion_page_id   = COALESCE(?, notion_page_id),
                   progress_stage   = COALESCE(?, progress_stage),
                   customer_type    = COALESCE(?, customer_type),
                   permit_type      = COALESCE(?, permit_type),
                   product_type     = COALESCE(?, product_type),
                   contract_stage   = COALESCE(?, contract_stage),
                   module_size_text = COALESCE(?, module_size_text)
             WHERE project_id = ?
        """, (
            m["notion_page_id"], m["progress_stage"], m["customer_type"],
            m["permit_type"], m["product_type"], m["contract_stage"],
            m["module_size_text"], m["op_project_id"],
        ))
    op.commit()
    print(f"적용 완료: projects 업데이트 {len(matched_rows)}건.")

    # 검증
    n_with_notion = op.execute(
        "SELECT COUNT(*) FROM projects WHERE notion_page_id IS NOT NULL"
    ).fetchone()[0]
    print(f"검증: projects.notion_page_id 채워진 행 = {n_with_notion}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
