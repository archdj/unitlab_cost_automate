"""운영 DB read-only 액세스. unitlab-notion-cost/data_access.py 기반."""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from .config import OPERATIONAL_DB, LEARNABLE_PROMOTION_STATUS

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def connect_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = Path(db_path) if db_path else OPERATIONAL_DB
    if not db_path.exists():
        raise FileNotFoundError(f"운영 DB 없음: {db_path}")
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


# ─────────────────────────────────────────────────────────────────────────────
# work_code 정규화 (level 3 → level 2)
# ─────────────────────────────────────────────────────────────────────────────

def workcode_normalize_map(con: sqlite3.Connection) -> dict[int, dict]:
    rows = [dict(r) for r in con.execute(
        "SELECT work_code_id, work_code, parent_code_id, level, category, "
        "       work_name_ko, unit FROM work_codes"
    )]
    by_id = {r["work_code_id"]: r for r in rows}

    def normalized(row_id: int) -> dict:
        cur = by_id[row_id]
        while cur["level"] > 2 and cur.get("parent_code_id") and by_id.get(cur["parent_code_id"]):
            cur = by_id[cur["parent_code_id"]]
        return cur

    return {
        wid: {
            "normalized_code": normalized(wid)["work_code"],
            "normalized_name": normalized(wid)["work_name_ko"],
            "category":        normalized(wid)["category"],
            "level":           by_id[wid]["level"],
            "definition_unit": normalized(wid)["unit"],
        }
        for wid in by_id
    }


# ─────────────────────────────────────────────────────────────────────────────
# 학습 샘플
# ─────────────────────────────────────────────────────────────────────────────

def load_actual_samples(con: sqlite3.Connection) -> list[dict]:
    """One row per (project, normalized_work_code, cost_type). 학습 입력."""
    norm = workcode_normalize_map(con)

    placeholders = ",".join("?" * len(LEARNABLE_PROMOTION_STATUS))
    raw = list(con.execute(f"""
        SELECT
          ac.project_id,
          ac.work_code_id,
          COALESCE(ac.source_ref, 'unknown') AS cost_type,
          SUM(ac.total_amount) AS amount,
          p.project_code,
          mt.module_code,
          mt.floor_area_m2,
          mt.pyeong,
          UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
          mt.structure_type
        FROM actual_costs ac
        JOIN projects p              ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ({placeholders})
        GROUP BY ac.project_id, ac.work_code_id, COALESCE(ac.source_ref, 'unknown')
    """, LEARNABLE_PROMOTION_STATUS))

    grouped: dict[tuple, dict] = {}
    for r in raw:
        nwc = norm[r["work_code_id"]]
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            continue
        key = (r["project_id"], nwc["normalized_code"], r["cost_type"])
        if key in grouped:
            grouped[key]["amount"] += int(r["amount"] or 0)
        else:
            grouped[key] = {
                "project_id":           r["project_id"],
                "project_code":         r["project_code"],
                "module_code":          r["module_code"],
                "normalized_work_code": nwc["normalized_code"],
                "work_name":            nwc["normalized_name"],
                "category":             nwc["category"],
                "cost_type":            r["cost_type"],
                "amount":               int(r["amount"] or 0),
                "floor_area_m2":        area,
                "pyeong":               float(r["pyeong"] or 0),
                "grade":                r["grade"],
                "structure_type":       r["structure_type"] or "STEEL",
            }

    samples = []
    for s in grouped.values():
        s["rate_per_m2"] = s["amount"] / s["floor_area_m2"] if s["floor_area_m2"] else 0
        if s["rate_per_m2"] <= 0:
            continue
        samples.append(s)
    return samples


def list_modules(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("""
        SELECT module_type_id, module_code, module_name,
               floor_area_m2, pyeong, structure_type,
               UPPER(COALESCE(finish_grade, 'UNKNOWN')) AS grade
        FROM module_types
        WHERE floor_area_m2 IS NOT NULL AND floor_area_m2 > 0
          AND module_code NOT LIKE 'IFC-%'
        ORDER BY floor_area_m2
    """)]


def list_projects(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("""
        SELECT p.project_id, p.project_code, p.project_name, p.region,
               SUM(ac.total_amount) AS actual_total,
               COUNT(ac.actual_cost_id) AS row_count,
               MIN(ac.settlement_date) AS first_date,
               MAX(ac.settlement_date) AS last_date
        FROM projects p
        LEFT JOIN actual_costs ac ON p.project_id = ac.project_id
        GROUP BY p.project_id
        ORDER BY actual_total DESC NULLS LAST
    """)]


def list_projects_for_backtest(con: sqlite3.Connection) -> list[dict]:
    """모듈 메타가 있고 actual_total > 100만원 인 프로젝트만 LOO 대상."""
    return [dict(r) for r in con.execute("""
        SELECT p.project_id, p.project_code, p.project_name,
               mt.module_code, mt.floor_area_m2, mt.pyeong,
               UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac          ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm  ON p.project_id = pm.project_id
        LEFT JOIN module_types mt     ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        GROUP BY p.project_id
        HAVING actual_total > 1000000
        ORDER BY actual_total DESC
    """)]


# ─────────────────────────────────────────────────────────────────────────────
# M0: 데이터 품질 프로파일
# ─────────────────────────────────────────────────────────────────────────────

NOTION_URL_RE = re.compile(r"https?://(www\.)?notion\.so/[^\s,)]+")


def profile_actual_costs(con: sqlite3.Connection) -> dict:
    """OPERATIONAL_DB_MAPPING.md §2 데이터 품질 이슈 정량화."""
    total = con.execute("SELECT COUNT(*) FROM actual_costs").fetchone()[0]

    null_counts = con.execute("""
        SELECT
          SUM(CASE WHEN actual_quantity IS NULL THEN 1 ELSE 0 END) AS quantity_null,
          SUM(CASE WHEN unit IS NULL OR unit = '' THEN 1 ELSE 0 END) AS unit_null,
          SUM(CASE WHEN unit_price IS NULL THEN 1 ELSE 0 END) AS unit_price_null,
          SUM(CASE WHEN material_id IS NULL THEN 1 ELSE 0 END) AS material_id_null,
          SUM(CASE WHEN vendor_name IS NULL OR vendor_name = '' THEN 1 ELSE 0 END) AS vendor_null,
          SUM(CASE WHEN invoice_no IS NULL OR invoice_no = '' THEN 1 ELSE 0 END) AS invoice_null,
          SUM(CASE WHEN total_amount <= 0 THEN 1 ELSE 0 END) AS amount_nonpositive
        FROM actual_costs
    """).fetchone()

    by_status = [dict(r) for r in con.execute("""
        SELECT promotion_status, COUNT(*) AS n, SUM(total_amount) AS sum_amount
        FROM actual_costs GROUP BY promotion_status
    """)]
    by_source = [dict(r) for r in con.execute("""
        SELECT source_system, COUNT(*) AS n
        FROM actual_costs GROUP BY source_system
    """)]

    # vendor_name 오염 (Notion URL 포함)
    vendor_polluted = 0
    for r in con.execute(
        "SELECT vendor_name FROM actual_costs WHERE vendor_name IS NOT NULL AND vendor_name != ''"
    ):
        if NOTION_URL_RE.search(r[0] or ""):
            vendor_polluted += 1

    return {
        "total_rows": total,
        "missing_rate": {
            "actual_quantity": _rate(null_counts["quantity_null"], total),
            "unit":            _rate(null_counts["unit_null"], total),
            "unit_price":      _rate(null_counts["unit_price_null"], total),
            "material_id":     _rate(null_counts["material_id_null"], total),
            "vendor_name":     _rate(null_counts["vendor_null"], total),
            "invoice_no":      _rate(null_counts["invoice_null"], total),
        },
        "amount_nonpositive": null_counts["amount_nonpositive"],
        "vendor_polluted_rows": vendor_polluted,
        "vendor_polluted_rate": _rate(vendor_polluted, total),
        "by_promotion_status": by_status,
        "by_source_system": by_source,
    }


def measure_alias_coverage(con: sqlite3.Connection) -> dict:
    """raw_description ↔ material_aliases 매칭 — 정확/토큰 두 단계."""
    rows = list(con.execute("""
        SELECT actual_cost_id, raw_description, material_id
        FROM actual_costs
        WHERE raw_description IS NOT NULL AND raw_description != ''
    """))
    total = len(rows)

    # alias 토큰 인덱스 빌드
    alias_idx = build_alias_token_index(con)
    aliases_total = con.execute("SELECT COUNT(*) FROM material_aliases").fetchone()[0]
    via_material_id = sum(1 for r in rows if r["material_id"] is not None)

    exact, token = 0, 0
    sample_token_hits: list[dict] = []
    unmapped: dict[str, int] = {}
    for r in rows:
        raw = (r["raw_description"] or "").strip()
        m = match_alias(raw, alias_idx)
        if m["method"] == "exact":
            exact += 1
        elif m["method"] == "token":
            token += 1
            if len(sample_token_hits) < 15:
                sample_token_hits.append({
                    "raw_description": raw,
                    "matched_alias":   m["alias_name"],
                    "material_id":     m["material_id"],
                    "score":           m["score"],
                    "method":          m["method"],
                })
        else:
            unmapped[raw] = unmapped.get(raw, 0) + 1

    unmapped_top = sorted(
        ({"raw_description": k, "n": v} for k, v in unmapped.items()),
        key=lambda x: -x["n"],
    )[:20]

    return {
        "actual_costs_with_description": total,
        "material_aliases_total":        aliases_total,
        "matched_by_material_id":        via_material_id,
        "matched_exact":                 exact,
        "matched_token":                 token,
        "alias_coverage_rate_exact":     _rate(exact, total),
        "alias_coverage_rate_token":     _rate(exact + token, total),
        "material_id_coverage_rate":     _rate(via_material_id, total),
        "sample_token_hits":             sample_token_hits,
        "top_unmapped_descriptions":     unmapped_top,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Alias 토큰 매칭 (B — material_aliases 250개 부분 매칭)
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_SPLIT = re.compile(r"[^\w가-힣]+", re.UNICODE)
_STOP_TOKENS = {"공사", "비", "비용", "운반", "운반비", "재료", "노무", "기타", "외", "포함"}


def _tokenize(s: str) -> list[str]:
    if not s:
        return []
    return [t for t in _TOKEN_SPLIT.split(s.lower().strip()) if len(t) >= 2]


def build_alias_token_index(con: sqlite3.Connection) -> dict:
    """material_aliases 를 토큰 인덱스로. 한 번 만들고 캐시 (파라미터로 전달).

    구조:
      {
        "by_exact": {alias_name_lower: {alias_name, material_id}},
        "by_token": {token: [{alias_name, material_id, tokens}]},
        "all":      [{alias_name, material_id, tokens}, ...],
      }
    """
    by_exact: dict[str, dict] = {}
    by_token: dict[str, list[dict]] = {}
    all_aliases: list[dict] = []
    for r in con.execute("SELECT alias_id, material_id, alias_name FROM material_aliases"):
        name = (r["alias_name"] or "").strip()
        if not name:
            continue
        toks = _tokenize(name)
        if not toks:
            continue
        rec = {
            "alias_name":  name,
            "material_id": r["material_id"],
            "tokens":      toks,
        }
        all_aliases.append(rec)
        by_exact[name.lower()] = rec
        for t in set(toks):
            by_token.setdefault(t, []).append(rec)
    return {"by_exact": by_exact, "by_token": by_token, "all": all_aliases}


def match_alias(raw: str, idx: dict) -> dict:
    """raw_description → 가장 잘 맞는 alias.

    1) 정확 일치 (lower, trim)
    2) 토큰 overlap 점수 (Jaccard 비슷). 의미 없는 stop 토큰 제외.
       반환 score = (공통 토큰 수) / (raw 토큰 수). 0.5 이상이면 채택.
    """
    raw = (raw or "").strip()
    low = raw.lower()
    if not low:
        return {"method": "none", "alias_name": None, "material_id": None, "score": 0.0}

    if low in idx["by_exact"]:
        rec = idx["by_exact"][low]
        return {"method": "exact", "alias_name": rec["alias_name"],
                "material_id": rec["material_id"], "score": 1.0}

    raw_tokens = [t for t in _tokenize(raw) if t not in _STOP_TOKENS]
    if not raw_tokens:
        return {"method": "none", "alias_name": None, "material_id": None, "score": 0.0}
    raw_set = set(raw_tokens)

    candidates: dict[str, dict] = {}
    for tok in raw_set:
        for rec in idx["by_token"].get(tok, []):
            key = rec["alias_name"]
            if key not in candidates:
                candidates[key] = rec

    best, best_score = None, 0.0
    for rec in candidates.values():
        alias_set = {t for t in rec["tokens"] if t not in _STOP_TOKENS}
        if not alias_set:
            continue
        common = raw_set & alias_set
        if not common:
            continue
        score = len(common) / max(len(raw_set), 1)
        # alias 안의 토큰도 많이 일치할수록 가산
        score = (score + len(common) / max(len(alias_set), 1)) / 2
        if score > best_score:
            best, best_score = rec, score

    if best and best_score >= 0.5:
        return {"method": "token", "alias_name": best["alias_name"],
                "material_id": best["material_id"], "score": round(best_score, 3)}
    return {"method": "none", "alias_name": None, "material_id": None, "score": round(best_score, 3)}


def clean_vendor_sample(con: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """vendor_name 정제 미리보기 (read-only)."""
    rows = con.execute(f"""
        SELECT actual_cost_id, vendor_name
        FROM actual_costs
        WHERE vendor_name IS NOT NULL AND vendor_name != ''
        LIMIT {int(limit)}
    """)
    out = []
    for r in rows:
        raw = r["vendor_name"]
        urls = NOTION_URL_RE.findall(raw or "")
        cleaned = NOTION_URL_RE.sub("", raw or "")
        # 잔여 괄호/구분자 정리
        cleaned = re.sub(r"\(\s*\)", "", cleaned).strip(" ,;()")
        # 다수 업체 분리
        vendors = [v.strip(" ,;()") for v in re.split(r"[,;]+", cleaned) if v.strip(" ,;()")]
        out.append({
            "actual_cost_id": r["actual_cost_id"],
            "raw": raw,
            "vendors": vendors,
            "url_count": len(urls),
        })
    return out


def _rate(num: int | None, denom: int | None) -> float:
    if not denom:
        return 0.0
    return round((num or 0) / denom, 4)
