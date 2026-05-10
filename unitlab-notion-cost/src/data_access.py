"""Read-only access to the operational DB. No IFC tables touched.

v1 함수 (`load_actual_samples`, `list_projects_for_backtest`): 운영 DB의 actual_costs만 사용.
  - cost_type=source_ref 매핑 버그 (운영 DB에 cost_type 컬럼 부재).
  - 학습 데이터 N=8 LOO.

v2 함수 (`load_actual_samples_v2`, `list_projects_for_backtest_v2`): sidecar autocost_enriched.db 사용.
  - cost_type은 노션 '선택' 컬럼 직접 매핑 (MAT/LAB/EXP/MIXED/ETC/RECUR/EXCL/OTHER).
  - 1420 cost rows / 16 학습 가능 프로젝트 (cost_total >= 49M).
  - module info는 운영 module_types에서 module_code_hint로 매칭.

v3 함수 (`load_actual_samples_v3`): 운영 DB 기반 + PR-1 cost_type 컬럼 + corrections optional.
  - PR-1 schema migration 후 운영 actual_costs.cost_type 백필됨 (931행 모두).
  - apply_corrections=True 시 sidecar `actual_cost_corrections` LEFT JOIN → corrected_wc로 work_code 교체.
  - corrections.actual_cost_id ↔ 운영 DB actual_cost_id 100% 매핑 (2026-05-10 검증).
  - 학습 가능 프로젝트는 v1과 동일 (운영 module_types 기반, N=8).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
# 운영 DB는 unitlab_autocost와 동일 레벨의 sister directory
DB_PATH = REPO_ROOT.parent.parent / "unitlab-cost-analysis" / "db" / "cost_analysis.db"

# Sidecar enriched DB (autocost-spec-2026-05-07/harness/data/autocost_enriched.db)
ENRICHED_DB_PATH = (
    REPO_ROOT.parent / "autocost-spec-2026-05-07" / "harness" / "data"
    / "autocost_enriched.db"
)


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def connect_readonly() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"운영 DB 없음: {DB_PATH}")
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def connect_enriched() -> sqlite3.Connection:
    """Sidecar enriched DB (autocost_enriched.db) 연결. Read mode (write는 build script만)."""
    if not ENRICHED_DB_PATH.exists():
        raise FileNotFoundError(
            f"sidecar 없음: {ENRICHED_DB_PATH}\n"
            "먼저 `python autocost-spec-2026-05-07/harness/scripts/build_enriched_db.py` 실행."
        )
    uri = f"file:{ENRICHED_DB_PATH.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def workcode_normalize_map(con: sqlite3.Connection) -> dict[int, dict]:
    """work_code_id → {normalized_code, normalized_name, level, category}.
    level 3 → level 2로, 그 외는 self."""
    rows = [dict(r) for r in con.execute(
        "SELECT work_code_id, work_code, parent_code_id, level, category, work_name_ko, unit FROM work_codes"
    )]
    by_id = {r["work_code_id"]: r for r in rows}
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
        wid: {
            "normalized_code": normalized(wid)["work_code"],
            "normalized_name": normalized(wid)["work_name_ko"],
            "category":        normalized(wid)["category"],
            "level":           by_id[wid]["level"],
            "definition_unit": normalized(wid)["unit"],
        }
        for wid in by_id
    }


def load_actual_samples(con: sqlite3.Connection) -> list[dict]:
    """One row per (project, normalized_work_code, cost_type).

    Returns rows ready for fitting:
        project_id / project_code / module_code / floor_area_m2 / pyeong / grade /
        normalized_work_code / work_name / category / cost_type / amount / rate_per_m2
    """
    norm = workcode_normalize_map(con)

    raw = list(con.execute("""
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
        JOIN projects p           ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
        GROUP BY ac.project_id, ac.work_code_id, COALESCE(ac.source_ref, 'unknown')
    """))

    grouped: dict[tuple, dict] = {}
    for r in raw:
        nwc = norm[r["work_code_id"]]
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            # 면적 없는 프로젝트는 학습에서 제외 (rate 산출 불가)
            continue
        key = (r["project_id"], nwc["normalized_code"], r["cost_type"])
        if key in grouped:
            grouped[key]["amount"] += int(r["amount"] or 0)
        else:
            grouped[key] = {
                "project_id":            r["project_id"],
                "project_code":          r["project_code"],
                "module_code":           r["module_code"],
                "normalized_work_code":  nwc["normalized_code"],
                "work_name":             nwc["normalized_name"],
                "category":              nwc["category"],
                "cost_type":             r["cost_type"],
                "amount":                int(r["amount"] or 0),
                "floor_area_m2":         area,
                "pyeong":                float(r["pyeong"] or 0),
                "grade":                 r["grade"],
                "structure_type":        r["structure_type"] or "STEEL",
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
    """)]


def list_projects_for_backtest(con: sqlite3.Connection) -> list[dict]:
    """Projects with module info AND actual cost > some minimum."""
    return [dict(r) for r in con.execute("""
        SELECT p.project_id, p.project_code, p.project_name,
               mt.module_code, mt.floor_area_m2, mt.pyeong,
               UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac      ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        GROUP BY p.project_id
        HAVING actual_total > 1000000
        ORDER BY actual_total DESC
    """)]


# ─────────────────────────────────────────────────────────────────────────────
# v2: sidecar 기반 — Q10 A 부활 (cost_type=노션 '선택') + 1420 cost rows + 16 projects
# ─────────────────────────────────────────────────────────────────────────────

# 노션 module_code_hint → 운영 module_types.module_code 매핑.
# 정확히 동일한 모듈이 운영에 있을 때만 매핑. 없으면 None → estimate fallback.
# (이전엔 "가장 가까운 BESPOKE"로 잘못 매핑해 큰 면적 오차 발생, 2026-05-09 정정)
MODULE_HINT_TO_OP_CODE = {
    "T-12":   "T-12-2025",      # 39.7 m²
    "T-15":   "T-15-STD",       # 49.6 m²
    "T-15-3": "T-15-STD",       # T-15 variant (노션 property상 T-12지만 T-15 더 정확)
    "T-9":    "T-9-STD",        # 29.8 m²
    "T-10":   "T-10-SHW",       # 33.1 m²
    "S-18":   "S-18-2025",      # 59.5 m²
    "H-30":   "H-30-2025",      # 99.2 m²
    "U-6":    "U-6-1-2025",     # 19.8 m²
    "U-6-1":  "U-6-1-2025",
    "ST-STD": "ST-STD-2025",    # 49 m² standard
    # 운영 entry 없는 module — None으로 두고 estimate fallback 사용:
    # "S-15"  → 50 m² estimate
    # "S-30"  → 99 m² estimate
    # "U-9"   → 30 m² estimate
    # "U-10"  → 33 m² estimate
    # "10평:20EA" → 33 m² estimate (단지 분양은 단일 모듈 추정의 한계)
}

# 학습 입력 필터: 노션 '선택' 컬럼 → cost_type 정규화 후 학습 가능 여부.
LEARNABLE_COST_TYPES = ("MAT", "LAB", "EXP", "MIXED", "ETC")  # RECUR/EXCL/OTHER 제외
LEARNABLE_STATUS = ("입금완료",)                                # 결제 완료된 행만 (기본)
LEARNABLE_STATUS_RELAXED = ("입금완료", "진행 전")               # 진행 중 프로젝트 cost 회수 (Q12 2-A)
PROJECT_COST_THRESHOLD = 49_000_000                             # cost_total ≥ 49M (Top 16 컷)


def _project_int_id(notion_page_id: str) -> int:
    """notion_page_id (UUID) → 안정된 정수 project_id (Pool key 호환).
    SHA1 첫 8 hex → 32-bit int."""
    h = hashlib.sha1(notion_page_id.encode("utf-8")).hexdigest()[:8]
    return int(h, 16)


def _estimate_module_meta(module_size_text: str | None) -> dict | None:
    """노션 module_size 텍스트(예: 'S-30', 'U-9', 'T-15-3')에서 평형/면적/등급 추정.
    운영 module_types에 매칭 entry가 없을 때 fallback.

    Convention: 모듈 코드 숫자 = 평형. 1평 ≈ 3.3 m².
    Grade는 표준 모델(T-12-2025 등)이 ESSENTIAL, 그 외는 BESPOKE.
    """
    if not module_size_text:
        return None
    s = module_size_text.strip().upper()
    # T-숫자, S-숫자, U-숫자, H-숫자 패턴
    m = re.match(r"^([THSUH])-?(\d+)", s)
    if m:
        type_code, size = m.group(1), int(m.group(2))
        pyeong = float(size)
        area_m2 = round(pyeong * 3.3, 1)
        return {
            "floor_area_m2":   area_m2,
            "pyeong":          pyeong,
            "structure_type":  "STEEL",
            "grade":           "BESPOKE",  # 운영 entry가 없으면 custom
        }
    # 10평:20EA 같은 패턴
    m = re.match(r"^(\d+)평", s)
    if m:
        pyeong = float(m.group(1))
        return {
            "floor_area_m2":  round(pyeong * 3.3, 1),
            "pyeong":         pyeong,
            "structure_type": "STEEL",
            "grade":          "BESPOKE",
        }
    return None


def _classify_work_code_category(work_code_text: str | None) -> str:
    """노션 '공종' 텍스트 → 운영 work_codes.category 4종 정규화.
    예: '01. 골조' → STRUCTURE, '02. 판넬' → FINISH, '05. 전기' → MEP, ..."""
    if not work_code_text:
        return "UNKNOWN"
    s = work_code_text.lower()
    if any(k in s for k in ["골조", "철골", "기초", "alc", "잡철", "01.", "structure"]):
        return "STRUCTURE"
    if any(k in s for k in ["전기", "설비", "공조", "환기", "배관", "보일러", "에어컨", "05.", "06.", "07.", "11.", "24.", "32.", "mep"]):
        return "MEP"
    if any(k in s for k in ["외장", "징크", "현관문", "창호", "폴딩", "지붕", "데크", "08.", "09.", "10.", "29.데크", "exterior"]):
        return "EXTERIOR"
    if any(k in s for k in ["도기", "수장", "경량", "타일", "마루", "도배", "마감", "도어", "스크린", "03.", "12.", "13.", "14.", "15.", "16.", "17.", "21.", "22.", "finish"]):
        return "FINISH"
    if any(k in s for k in ["크레인", "운반", "현장설치", "청소", "폐기물", "25.", "26.", "28.", "29. ", "30.", "31.", "site"]):
        return "SITE"
    if any(k in s for k in ["가구", "패키지", "데크", "어닝", "커튼", "iot", "프라이버시", "방충망", "베리어프리", "cs", "as", "처마", "목공", "토목", "차음재", "재설치", "33.", "34.", "furniture"]):
        return "FURNITURE"
    return "OTHER"


def list_projects_for_backtest_v2(
    enriched_con: sqlite3.Connection,
    op_con: sqlite3.Connection | None = None,
) -> list[dict]:
    """sidecar projects_master에서 학습 가능 프로젝트 (cost_total >= 49M).
    op_con 제공 시 module_types에서 area/pyeong/grade를 join, 없으면 module_code_hint에서 추정.
    Returns one dict per project with keys compatible with `list_projects_for_backtest()`.
    """
    # Prepare op module_types lookup if op_con available
    mt_by_code: dict[str, dict] = {}
    if op_con is not None:
        for r in op_con.execute("""
            SELECT module_code, floor_area_m2, pyeong, structure_type,
                   UPPER(COALESCE(finish_grade, 'UNKNOWN')) AS grade
            FROM module_types
            WHERE floor_area_m2 IS NOT NULL AND floor_area_m2 > 0
        """):
            mt_by_code[r["module_code"]] = dict(r)

    rows = []
    for r in enriched_con.execute("""
        SELECT project_notion_id, name, module_code_hint, cost_row_count, cost_total
        FROM projects_master
        WHERE cost_total >= ?
        ORDER BY cost_total DESC
    """, (PROJECT_COST_THRESHOLD,)):
        op_code = MODULE_HINT_TO_OP_CODE.get(r["module_code_hint"])
        # Resolve module meta — op_db first, then estimate, else None (project drops from learning)
        mt = mt_by_code.get(op_code) if op_code else None
        if mt:
            area = float(mt["floor_area_m2"])
            pyeong = float(mt["pyeong"] or 0)
            grade = mt["grade"]
            structure = mt["structure_type"] or "STEEL"
            module_code_eff = op_code
        else:
            est = _estimate_module_meta(r["module_code_hint"])
            if est:
                area = est["floor_area_m2"]
                pyeong = est["pyeong"]
                grade = est["grade"]
                structure = est["structure_type"]
                module_code_eff = r["module_code_hint"] or "ESTIMATED"
            else:
                area = pyeong = 0.0
                grade = "UNKNOWN"
                structure = "STEEL"
                module_code_eff = None
        rows.append({
            "project_id":        _project_int_id(r["project_notion_id"]),
            "project_code":      (r["name"] or "")[:20],
            "project_name":      r["name"],
            "module_code":       module_code_eff,
            "module_code_hint":  r["module_code_hint"],
            "floor_area_m2":     area,
            "pyeong":            pyeong,
            "grade":             grade,
            "structure_type":    structure,
            "actual_total":      r["cost_total"],
            "row_count":         r["cost_row_count"],
            "project_notion_id": r["project_notion_id"],
        })
    return rows


NOISE_WORK_CODES = ("미해당", "32. 기타", "32.기타")


def load_actual_samples_v2(
    enriched_con: sqlite3.Connection,
    op_con: sqlite3.Connection,
    *,
    cost_types: tuple[str, ...] = LEARNABLE_COST_TYPES,
    statuses:   tuple[str, ...] = LEARNABLE_STATUS,
    drop_mixed: bool = False,
    exclude_noise_work_codes: bool = False,
    use_all_statuses: bool = False,
    outlier_pct: float | None = None,
) -> list[dict]:
    """sidecar 기반 학습 샘플. cost_type은 노션 '선택' 직접 매핑.

    Args:
        cost_types: 학습 input에 포함할 cost_type 라벨. 기본 (MAT,LAB,EXP,MIXED,ETC).
        statuses:   포함할 status_code. 기본 ('입금완료',). 완화 시 LEARNABLE_STATUS_RELAXED.
        drop_mixed: True면 MIXED 라벨 행 제외 (Q12 2차 escalation).

    Returns rows with keys (model 호환):
      project_id, project_code, module_code, normalized_work_code, work_name,
      category, cost_type, cost_type_raw, amount,
      floor_area_m2, pyeong, grade, structure_type, rate_per_m2
    """
    if drop_mixed:
        cost_types = tuple(t for t in cost_types if t != "MIXED")

    # 학습 가능 프로젝트 list (sidecar) — module meta 포함 (op_con 전달 시 op_db 매핑)
    projects = list_projects_for_backtest_v2(enriched_con, op_con)
    proj_by_notion = {p["project_notion_id"]: p for p in projects}

    # 3. cost rows (sidecar) join + 그룹화
    placeholders = ",".join("?" for _ in cost_types)
    if use_all_statuses:
        status_clause = ""
        status_args = []
    else:
        statuses_ph  = ",".join("?" for _ in statuses)
        status_clause = f"AND status_code IN ({statuses_ph})"
        status_args = list(statuses)

    noise_clause = ""
    noise_args = []
    if exclude_noise_work_codes:
        noise_ph = ",".join("?" for _ in NOISE_WORK_CODES)
        noise_clause = f"AND COALESCE(work_code_text,'') NOT IN ({noise_ph})"
        noise_args = list(NOISE_WORK_CODES)

    cost_rows = list(enriched_con.execute(f"""
        SELECT project_notion_id, work_code_text, cost_type, cost_type_raw,
               SUM(total_amount) AS amount, COUNT(*) AS row_count
        FROM actual_costs_enriched
        WHERE cost_type IN ({placeholders})
          {status_clause}
          {noise_clause}
          AND project_notion_id IN ({",".join("?" for _ in proj_by_notion)})
          AND total_amount > 0
        GROUP BY project_notion_id, work_code_text, cost_type
    """, [*cost_types, *status_args, *noise_args, *proj_by_notion.keys()]))

    # 프로젝트는 list_projects_for_backtest_v2가 이미 floor_area_m2/grade/pyeong 해결한 상태로 반환.
    # module_code_eff = None인 프로젝트는 학습 제외.
    samples = []
    for r in cost_rows:
        proj = proj_by_notion.get(r["project_notion_id"])
        if not proj or not proj["module_code"]:
            continue
        area = proj["floor_area_m2"]
        amount = int(r["amount"] or 0)
        if area <= 0 or amount <= 0:
            continue
        wc = (r["work_code_text"] or "UNKNOWN").strip() or "UNKNOWN"
        samples.append({
            "project_id":           proj["project_id"],
            "project_code":         proj["project_code"],
            "module_code":          proj["module_code"],
            "normalized_work_code": wc,
            "work_name":            wc,
            "category":             _classify_work_code_category(wc),
            "cost_type":            r["cost_type"],
            "cost_type_raw":        r["cost_type_raw"],
            "amount":               amount,
            "floor_area_m2":        area,
            "pyeong":               proj["pyeong"],
            "grade":                proj["grade"],
            "structure_type":       proj["structure_type"],
            "rate_per_m2":          amount / area,
        })

    # Optional: outlier removal — (cost_type, normalized_work_code)별 rate_per_m2 P95 초과 제거
    if outlier_pct is not None and 0 < outlier_pct < 1:
        rates_by_key: dict[tuple, list[float]] = defaultdict(list)
        for s in samples:
            rates_by_key[(s["cost_type"], s["normalized_work_code"])].append(s["rate_per_m2"])
        # Sort each group's rates and find threshold
        thresholds: dict[tuple, float] = {}
        for k, rs in rates_by_key.items():
            if len(rs) < 4:  # 너무 작은 그룹은 outlier filter skip
                continue
            rs_sorted = sorted(rs)
            idx = int(len(rs_sorted) * outlier_pct)
            thresholds[k] = rs_sorted[min(idx, len(rs_sorted) - 1)]
        samples = [
            s for s in samples
            if s["rate_per_m2"] <= thresholds.get(
                (s["cost_type"], s["normalized_work_code"]), float("inf")
            )
        ]
    return samples


# ─────────────────────────────────────────────────────────────────────────────
# Quote correction helpers (2026-05-10) — backtest_v5 검증된 -3~-5pp 자재 MAPE 개선
#
# sidecar `material_quote_lines` (견적서 line item) 의 amount 로 자재(MAT) 셀
# actual 을 보정. project_code (N-XX) ↔ sidecar pid (notion hash) bridge,
# work_code 영어 → 한글 매핑 필요.
#
# 검증 결과: 자재 wMAPE proj-sum
#   v4 (운영 DB N=8):  26.3% → 21.7% (-4.6pp), bootstrap median -4.45pp
#   v5 (sidecar N=15): 22.3% → 19.1% (-3.2pp), bootstrap median -3.15pp
# ─────────────────────────────────────────────────────────────────────────────

# Quote work_code (영어 정규화) → sidecar work_code_text (한글) 매핑.
# 2026-05-10 도메인 검증 후 (docs/quote_workcode_mapping_audit_2026-05-10.md).
QUOTE_WC_TO_SIDECAR = {
    "STR-ST":   "01. 골조",       # H형강 / 삼남강재
    "FIN-PANEL": "02. 판넬",      # 우레탄판넬 / 진호판넬
    "FIN-CARP":  "13. 경량",      # LGS 경량철골 (quote의 L/ㄴ 코드)
    "FIN-FLOOR": "11. 바닥난방",  # 온수난방패널 / 태경에스앤씨
    "EXT-WIN":   "03. 창호",
    "MEP-ELEC":  "05. 전기",
    "MEP-HVAC":  "07. 환기/공조",
    "FUR":       "14. 수장/도어",
    "FUR-DOOR":  "08. 현관문",
    "EXT-DECK":  "29.데크",
    "SITE-DEMO": "토목",          # sidecar MAT 0건이지만 LAB/EXP에 존재 — 매핑 유지
}

MAT_LABEL = "MAT"


def build_pcode_to_sidecar_pid_bridge(
    en_con: sqlite3.Connection,
    op_con: sqlite3.Connection,
) -> dict[str, int]:
    """quote_lines.project_code (N-XX) → v2 sample.project_id (sidecar hash).

    Bridge: op.projects(project_code, notion_page_id) ↔ sidecar projects_master.project_notion_id.
    sidecar pid 는 _project_int_id(notion_page_id) hash.
    """
    op_pcode_to_nid = {
        r["project_code"]: r["notion_page_id"]
        for r in op_con.execute(
            "SELECT project_code, notion_page_id FROM projects WHERE notion_page_id IS NOT NULL"
        )
    }
    sidecar_nids = {
        r["project_notion_id"]
        for r in en_con.execute(
            "SELECT project_notion_id FROM projects_master WHERE project_notion_id IS NOT NULL"
        )
    }
    return {
        pcode: _project_int_id(nid)
        for pcode, nid in op_pcode_to_nid.items()
        if nid in sidecar_nids
    }


def load_quote_sums_keyed_by_sidecar_pid(
    en_con: sqlite3.Connection,
    bridge: dict[str, int],
) -> tuple[dict[tuple[int, str], float], dict]:
    """quote_lines → (sidecar_pid, sidecar_work_code) → amount sum.

    영어 work_code → 한글 work_code_text 매핑 (QUOTE_WC_TO_SIDECAR) 적용.
    Returns (key_to_amount, stats).
    """
    raw = list(en_con.execute("""
        SELECT project_code, work_code, SUM(amount) AS s
        FROM material_quote_lines
        WHERE project_code IS NOT NULL AND work_code IS NOT NULL AND amount IS NOT NULL
        GROUP BY project_code, work_code
    """))
    out: dict[tuple, float] = defaultdict(float)
    n_mapped = 0
    n_skipped_proj = 0
    n_skipped_wc = 0
    total_amount_mapped = 0.0
    for r in raw:
        sidecar_pid = bridge.get(r["project_code"])
        if sidecar_pid is None:
            n_skipped_proj += 1
            continue
        sidecar_wc = QUOTE_WC_TO_SIDECAR.get(r["work_code"])
        if sidecar_wc is None:
            n_skipped_wc += 1
            continue
        out[(sidecar_pid, sidecar_wc)] += float(r["s"] or 0)
        n_mapped += 1
        total_amount_mapped += float(r["s"] or 0)
    return dict(out), {
        "n_quote_cells": len(raw),
        "n_mapped": n_mapped,
        "n_skipped_project": n_skipped_proj,
        "n_skipped_workcode": n_skipped_wc,
        "total_amount_mapped": int(total_amount_mapped),
    }


def apply_quote_corrections_to_samples(
    samples: list[dict],
    quote_keyed: dict[tuple[int, str], float],
) -> tuple[list[dict], dict]:
    """v2 sample list 에 quote correction in-place 적용.

    - 같은 (project_id, work_code, MAT) 셀 존재 → amount 를 quote_sum 으로 대체
    - 셀이 없으면 신규 추가 (학습 풀에 영어 work_code MAT 셀 추가)

    rate_per_m2 = 0 이 되는 셀은 filter out.
    Returns (corrected_samples, stats).
    """
    pid_to_meta: dict[int, dict] = {}
    for s in samples:
        if s["project_id"] not in pid_to_meta:
            pid_to_meta[s["project_id"]] = s

    keyed = {
        (s["project_id"], s["normalized_work_code"], s["cost_type"]): s
        for s in samples
    }

    n_replaced = 0
    n_added = 0
    delta_amount = 0
    skipped_no_pool = 0

    for (pid, wc), qsum in quote_keyed.items():
        meta = pid_to_meta.get(pid)
        if meta is None:
            skipped_no_pool += 1
            continue
        key = (pid, wc, MAT_LABEL)
        area = meta["floor_area_m2"]
        if key in keyed:
            old = keyed[key]["amount"]
            keyed[key]["amount"] = int(qsum)
            keyed[key]["rate_per_m2"] = qsum / area if area else 0
            n_replaced += 1
            delta_amount += abs(qsum - old)
        else:
            new_sample = {
                "project_id":            pid,
                "project_code":          meta["project_code"],
                "module_code":           meta["module_code"],
                "normalized_work_code":  wc,
                "work_name":             wc,
                "category":              "?",
                "cost_type":             MAT_LABEL,
                "cost_type_raw":         "재료비",
                "amount":                int(qsum),
                "floor_area_m2":         area,
                "pyeong":                meta["pyeong"],
                "grade":                 meta["grade"],
                "structure_type":        meta["structure_type"],
                "rate_per_m2":           qsum / area if area else 0,
            }
            if new_sample["rate_per_m2"] > 0:
                samples.append(new_sample)
                keyed[key] = new_sample
                n_added += 1
                delta_amount += qsum

    samples = [s for s in samples if s.get("rate_per_m2", 0) > 0]
    return samples, {
        "n_replaced": n_replaced,
        "n_added": n_added,
        "delta_amount": int(delta_amount),
        "skipped_no_pool": skipped_no_pool,
    }


# ─────────────────────────────────────────────────────────────────────────────
# v3: 운영 DB 기반 + PR-1 cost_type 컬럼 + sidecar corrections optional
# ─────────────────────────────────────────────────────────────────────────────


def load_actual_samples_v3(
    con: sqlite3.Connection,
    *,
    apply_corrections: bool = False,
    corrections_con: sqlite3.Connection | None = None,
    cost_types: tuple[str, ...] = LEARNABLE_COST_TYPES,
    drop_mixed: bool = True,
) -> list[dict]:
    """운영 DB 기반 학습 샘플. PR-1 cost_type 컬럼 사용.

    apply_corrections=True 시 sidecar `actual_cost_corrections.corrected_wc`로
    work_code를 row 단위 override한 뒤 normalized_work_code 재계산.

    Returns 동일한 dict shape (load_actual_samples 호환).
    """
    if apply_corrections and corrections_con is None:
        corrections_con = connect_enriched()
        _close_corrections = True
    else:
        _close_corrections = False

    norm = workcode_normalize_map(con)
    code_to_id = {
        r["work_code"]: r["work_code_id"]
        for r in con.execute("SELECT work_code_id, work_code FROM work_codes")
    }

    # corrections 적용: actual_cost_id → corrected work_code_id
    correction_map: dict[int, int] = {}
    if apply_corrections:
        for r in corrections_con.execute("""
            SELECT actual_cost_id, corrected_wc
            FROM actual_cost_corrections
            WHERE corrected_wc IS NOT NULL
        """):
            wcid = code_to_id.get(r["corrected_wc"])
            if wcid is not None:
                correction_map[r["actual_cost_id"]] = wcid
        if _close_corrections:
            corrections_con.close()

    # 학습 cost_type 필터 (PR-1 컬럼)
    cost_type_ph = ",".join("?" * len(cost_types))
    raw = list(con.execute(f"""
        SELECT
          ac.actual_cost_id,
          ac.project_id,
          ac.work_code_id,
          ac.cost_type,
          ac.total_amount AS amount,
          p.project_code,
          mt.module_code,
          mt.floor_area_m2,
          mt.pyeong,
          UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
          mt.structure_type
        FROM actual_costs ac
        JOIN projects p           ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND ac.cost_type IN ({cost_type_ph})
    """, cost_types))

    grouped: dict[tuple, dict] = {}
    for r in raw:
        # corrected work_code_id 적용 (있으면)
        wcid = correction_map.get(r["actual_cost_id"], r["work_code_id"])
        if wcid not in norm:
            continue
        nwc = norm[wcid]
        area = float(r["floor_area_m2"] or 0)
        if area <= 0:
            continue
        cost_type = r["cost_type"]
        # 학습 입력 옵션 — MIXED는 학습 풀에 포함, 자재 MAPE 측정에서만 분리.
        # drop_mixed=True 시 학습에서도 제외.
        if drop_mixed and cost_type == "MIXED":
            continue
        key = (r["project_id"], nwc["normalized_code"], cost_type)
        if key in grouped:
            grouped[key]["amount"] += int(r["amount"] or 0)
        else:
            grouped[key] = {
                "project_id":            r["project_id"],
                "project_code":          r["project_code"],
                "module_code":           r["module_code"],
                "normalized_work_code":  nwc["normalized_code"],
                "work_name":             nwc["normalized_name"],
                "category":              nwc["category"],
                "cost_type":             cost_type,
                "amount":                int(r["amount"] or 0),
                "floor_area_m2":         area,
                "pyeong":                float(r["pyeong"] or 0),
                "grade":                 r["grade"],
                "structure_type":        r["structure_type"] or "STEEL",
            }

    samples = []
    for s in grouped.values():
        s["rate_per_m2"] = s["amount"] / s["floor_area_m2"] if s["floor_area_m2"] else 0
        if s["rate_per_m2"] <= 0:
            continue
        samples.append(s)
    return samples


if __name__ == "__main__":
    if "--v2" in sys.argv:
        op_con = connect_readonly()
        en_con = connect_enriched()
        samples = load_actual_samples_v2(en_con, op_con)
        projects = list_projects_for_backtest_v2(en_con, op_con)
        print(f"=== v2 (sidecar) ===")
        print(f"learning samples: {len(samples)}")
        print(f"learning projects: {len(projects)}")
        print(f"  with module match: {len([p for p in projects if p['module_code']])}")
        print(f"work_codes: {len({s['normalized_work_code'] for s in samples})}")
        print(f"cost_types: {sorted({s['cost_type'] for s in samples})}")
        print(f"categories: {sorted({s['category'] for s in samples})}")
        en_con.close(); op_con.close()
    else:
        con = connect_readonly()
        samples = load_actual_samples(con)
        print(f"=== v1 (operational) ===")
        print(f"actual samples: {len(samples)}")
        print(f"projects: {len({s['project_id'] for s in samples})}")
        print(f"work_codes: {len({s['normalized_work_code'] for s in samples})}")
        print(f"cost_types: {sorted({s['cost_type'] for s in samples})}")
