"""Enrich projects_master with project metadata fetched from Notion '영업 프로젝트' DB via MCP.

이 스크립트는 일회성 — MCP fetch 결과를 하드코딩된 dict로 받아 projects_master에 업데이트.
실시간 sync가 필요하면 build_enriched_db.py 다음 단계로 자동화 (Phase 2).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_PATH = Path(__file__).resolve().parents[2] / "harness" / "data" / "autocost_enriched.db"


# 2026-05-09 MCP fetch 결과 (Top 16 학습 가능 프로젝트)
PROJECTS_META = [
    {
        "id": "a0f70068-977e-4973-94fa-8ede90e56b95",
        "name": "강원 홍천군 영귀미면 노천리 산315-9 T-15",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "근생,세컨하우스", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "T-15",
    },
    {
        "id": "14657166-9988-8036-af98-e6672b0f2287",
        "name": "청주 루떼르 포레 모델하우스 S-18",
        "address": None, "customer_type": "B2B", "product_type": None,
        "permit_type": "쇼룸", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": None,
    },
    {
        "id": "35b9ff33-08dd-4814-8c81-3bff8f20e3bf",
        "name": "청주 상당구 미원면 중리 산 52-13 T-12",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "근생,세컨하우스", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "T-12",
    },
    {
        "id": "22957166-9988-803a-810e-d33fcfd5cb0a",
        "name": "경기 화성시 쌍학리 667-5_주택 S-18(박공)",
        "address": "경기도 화성시 쌍학리 677-5", "customer_type": "B2C",
        "product_type": "유닛하우스", "permit_type": "주택",
        "contract_stage": "계약 완료", "progress_stage": "제작 중",
        "module_size": "S-18",
    },
    {
        "id": "30d57166-9988-809f-a333-c7242e4dd293",
        "name": "테스트베드",
        "address": None, "customer_type": None, "product_type": "유닛빌드",
        "permit_type": None, "contract_stage": None,
        "progress_stage": None, "module_size": None,
    },
    {
        "id": "36794ad5-8b65-45f2-be0b-81b1a77f746b",
        "name": "남곡리 쇼룸 T-12",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "주택", "contract_stage": None,
        "progress_stage": "완료", "module_size": "T-12",
    },
    {
        "id": "6595c62c-a870-4ebc-89e3-acff6053a3dc",
        "name": "밀양 다랑협동조합 쉐어하우스 S-33",
        "address": None, "customer_type": "B2G", "product_type": "유닛하우스",
        "permit_type": "숙박", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "S-30",  # name says S-33 but property says S-30
    },
    {
        "id": "2b157166-9988-8076-9dde-dd020a7b4777",
        "name": "서산 부석면 강수리 277",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "세컨하우스,근생", "contract_stage": "계약 완료",
        "progress_stage": "제작 중", "module_size": "U-9",
    },
    {
        "id": "25557166-9988-8084-a922-fb419edc0aef",
        "name": "[쇼룸] 남곡리 T-12, U-10",
        "address": None, "customer_type": "B2B",
        "product_type": "유닛하우스,유닛포인트", "permit_type": "단지 분양",
        "contract_stage": "계약 완료", "progress_stage": "완료",
        "module_size": "10평:20EA",
    },
    {
        "id": "4e011b87-d69d-48ca-969e-3ce0795f435f",
        "name": "제주도 안덕면 서광리 80-5 H-30",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "주택", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "H-30",
    },
    {
        "id": "4b566046-ea7e-4a2a-bfc7-cb62948970c1",
        "name": "밀양 남기동길 43-2 T-15-3",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "주택", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "T-12",  # name says T-15-3 but property says T-12
    },
    {
        "id": "20657166-9988-800a-bd68-efbee1b1f10a",
        "name": "충남_금산군_추부면_마전리_683-152_주택_T-12",
        "address": "충남 금산군 추부면 마전리 683-152", "customer_type": "B2C",
        "product_type": "유닛하우스", "permit_type": "주택,세컨하우스",
        "contract_stage": "계약 완료", "progress_stage": "준공 대기",
        "module_size": "T-12",
    },
    {
        "id": "1e557166-9988-80ee-b136-c5be4409791d",
        "name": "경기 성남시 수정구 상적동 2-1 T-12",
        "address": "경기도 성남시 수정구 상적동 2-1", "customer_type": "B2C",
        "product_type": "유닛하우스", "permit_type": "근생,세컨하우스",
        "contract_stage": "계약 완료", "progress_stage": "준공 대기",
        "module_size": "T-12",
    },
    {
        "id": "89dd576f-9788-48e7-853b-fae404539073",
        "name": "용인 수지 에스테라고 카페 1동 U-6",
        "address": None, "customer_type": "B2B", "product_type": "유닛포인트",
        "permit_type": "야영장", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "U-6",
    },
    {
        "id": "56801c3e-9dd7-4cf6-b449-a8877b7c183d",
        "name": "용인 수지 에스테라고 카페 2동 U-6",
        "address": None, "customer_type": "B2B", "product_type": "유닛포인트",
        "permit_type": "야영장", "contract_stage": "계약 완료",
        "progress_stage": "완료", "module_size": "U-6",
    },
    {
        "id": "29b57166-9988-8000-85bc-d7e644efcae4",
        "name": "양평군 원덕리 346-34_근생_s-18",
        "address": None, "customer_type": "B2C", "product_type": "유닛하우스",
        "permit_type": "근생", "contract_stage": "계약 완료",
        "progress_stage": "시안", "module_size": "S-15",  # name says s-18 but property says S-15
    },
]


def main() -> int:
    con = sqlite3.connect(DB_PATH)
    updated = 0
    for p in PROJECTS_META:
        # module_code_hint priority: notion property '프로젝트 규모' > existing parsed hint
        cur = con.execute(
            """
            UPDATE projects_master
            SET address          = ?,
                customer_type    = ?,
                product_type     = ?,
                permit_type      = ?,
                contract_stage   = ?,
                progress_stage   = ?,
                module_code_hint = COALESCE(?, module_code_hint),
                raw_payload      = ?,
                fetched_at       = datetime('now')
            WHERE project_notion_id = ?
            """,
            (
                p["address"], p["customer_type"], p["product_type"],
                p["permit_type"], p["contract_stage"], p["progress_stage"],
                p["module_size"],
                json.dumps(p, ensure_ascii=False),
                p["id"],
            ),
        )
        updated += cur.rowcount
    con.commit()

    # Verify
    print(f"PROJECTS_META: {len(PROJECTS_META)}")
    # 학습 가능 컷오프 — unitlab-notion-cost/src/data_access.py:PROJECT_COST_THRESHOLD와 동기.
    threshold = 49_000_000
    print()
    print(f"=== projects_master with metadata (cost_total >= {threshold//1_000_000}M) ===")
    print(f'{"name":<45} {"mod":>8} {"prog":>10} {"type":<20} {"perm":<25}')
    rows = list(con.execute("""
        SELECT name, module_code_hint, progress_stage, customer_type,
               product_type, permit_type, cost_total
        FROM projects_master
        WHERE cost_total >= ?
        ORDER BY cost_total DESC
    """, (threshold,)))
    for r in rows:
        name = (r[0] or "")[:44]
        mod  = (r[1] or "?")[:8]
        prog = (r[2] or "?")[:10]
        ct   = (r[3] or "?")[:5]
        pt   = (r[4] or "?")[:14]
        perm = (r[5] or "?")[:25]
        print(f"{name:<45} {mod:>8} {prog:>10} {ct + '/' + pt:<20} {perm:<25}")
    print()
    print(f"learning-eligible projects: {len(rows)}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
