"""actual_cost row 단위 work_code 재분류 + sidecar 적재 + wMAPE 측정.

전략:
1. 자재 actual_cost row 의 raw_description 을 work_code_keywords 매핑으로 재분류
2. 견적서 line items 와 (vendor, project) cross-check 으로 보강
3. corrected_work_code 가 original 과 다르면 sidecar 에 기록
4. corrected 적용 후 LOO backtest 자재 wMAPE 측정
"""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harness" / "mapping"))

from src.config import OPERATIONAL_DB
from src.db import workcode_normalize_map
from src.model import Pool, predict_for_module
from work_code_keywords import classify_raw_description, classify_filename_v2

ENRICHED_DB = ROOT / "harness" / "data" / "autocost_enriched.db"

LOG: list[str] = []
def log(s=""): LOG.append(str(s))


NOTION_URL_RE = re.compile(r"\(https?://(www\.)?notion\.so/[^\s)]+\)")


def normalize_vendor(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = NOTION_URL_RE.sub("", raw).strip(" ,;()\t")
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 다수 vendor 분리 — 첫번째만 사용
    parts = re.split(r"[,;]+", cleaned)
    first = (parts[0] if parts else "").strip(" ,;()")
    # (주) 등 prefix 정규화
    first = re.sub(r"^[(\[]?주[)\]]?\s*", "", first)
    first = re.sub(r"^주식회사\s*", "", first)
    return first or None


def load_actual_material_rows(con) -> list[dict]:
    """자재(재료비) actual_cost rows + project_code + 정규화 vendor."""
    norm = workcode_normalize_map(con)
    rows = list(con.execute("""
        SELECT
          ac.actual_cost_id, ac.project_id, ac.work_code_id,
          ac.raw_description, ac.total_amount, ac.vendor_name,
          p.project_code,
          mt.floor_area_m2
        FROM actual_costs ac
        JOIN projects p              ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ('approved','promoted','validated')
          AND ac.source_ref = '재료비'
    """))
    out = []
    for r in rows:
        nwc = norm.get(r["work_code_id"])
        if not nwc:
            continue
        out.append({
            "actual_cost_id": r["actual_cost_id"],
            "project_id":     r["project_id"],
            "project_code":   r["project_code"],
            "current_wc":     nwc["normalized_code"],
            "raw_description": r["raw_description"] or "",
            "amount":         r["total_amount"],
            "vendor_norm":    normalize_vendor(r["vendor_name"]),
            "floor_area_m2":  float(r["floor_area_m2"] or 0),
        })
    return out


def build_quote_lookup(enriched_con) -> dict[tuple[str, str], dict]:
    """sidecar material_quote_lines → (vendor_norm, project_code) → {wc, amount}.

    같은 (vendor, project) 에 여러 work_code 견적서가 있을 수 있음 → list.
    """
    lookup: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in enriched_con.execute("""
        SELECT vendor, project_code, work_code, SUM(amount) amt, COUNT(*) n_lines
        FROM material_quote_lines
        WHERE vendor IS NOT NULL AND project_code IS NOT NULL AND work_code IS NOT NULL
        GROUP BY vendor, project_code, work_code
    """):
        v = normalize_vendor(r[0])
        if not v:
            continue
        lookup[(v, r[1])].append({
            "work_code": r[2],
            "amount":    r[3] or 0,
            "n_lines":   r[4],
        })
    return dict(lookup)


def determine_corrected_wc(row: dict, quote_lookup: dict) -> tuple[str, str, float]:
    """row의 corrected work_code 결정.

    Returns: (corrected_wc, evidence_source, confidence_score)

    Strategy:
    1. raw_description 분석 → primary_wc (high confidence 키워드 매칭)
    2. (vendor, project) 견적서 lookup → quote_wcs
    3. primary_wc 가 quote_wcs 에 있으면 → primary_wc (확정)
    4. primary_wc 만 있고 quote 없으면 → primary_wc (raw_description 우선)
    5. quote 만 있고 primary 없으면 → 가장 큰 amount quote_wc
    6. 둘 다 없으면 → original (변경 없음)
    """
    desc = row["raw_description"]
    cls = classify_raw_description(desc)
    primary_wc = cls["work_code"]
    primary_conf = cls["wc_confidence"]
    primary_kw = next((t.split(":", 1)[1] for t in cls["tags"] if t.startswith("cat:")), None)

    quote_wcs = quote_lookup.get((row["vendor_norm"], row["project_code"]), [])

    # case 3: primary_wc 가 quote 와 일치
    if primary_wc and any(q["work_code"] == primary_wc for q in quote_wcs):
        return primary_wc, f"raw_desc+quote:{primary_kw}", 1.0
    # case 4: primary 만
    if primary_wc:
        # high confidence 키워드면 raw_description 만으로도 corrected 적용
        if primary_conf == "high":
            return primary_wc, f"raw_desc:{primary_kw}", 0.85
        elif primary_conf == "medium":
            return primary_wc, f"raw_desc:{primary_kw}", 0.6
        else:
            return primary_wc, f"raw_desc_low:{primary_kw}", 0.4
    # case 5: quote 만
    if quote_wcs:
        # 가장 큰 amount
        best = max(quote_wcs, key=lambda q: q["amount"])
        return best["work_code"], f"quote_only:vendor+project", 0.7
    # case 6: 변경 없음
    return row["current_wc"], "no_evidence", 0.0


def setup_sidecar_table(con: sqlite3.Connection):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS actual_cost_corrections (
      correction_id    INTEGER PRIMARY KEY AUTOINCREMENT,
      actual_cost_id   INTEGER NOT NULL,
      original_wc      TEXT,
      corrected_wc     TEXT,
      evidence         TEXT,
      confidence       REAL,
      raw_description  TEXT,
      vendor_norm      TEXT,
      project_code     TEXT,
      amount           INTEGER,
      created_at       TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_acc_actual ON actual_cost_corrections(actual_cost_id);
    CREATE INDEX IF NOT EXISTS idx_acc_proj   ON actual_cost_corrections(project_code);
    CREATE INDEX IF NOT EXISTS idx_acc_corrected ON actual_cost_corrections(corrected_wc);
    """)
    con.execute("DELETE FROM actual_cost_corrections")  # idempotent
    con.commit()


def main():
    op_con = sqlite3.connect(f"file:{OPERATIONAL_DB.as_posix()}?mode=ro", uri=True)
    op_con.row_factory = sqlite3.Row
    en_con = sqlite3.connect(ENRICHED_DB)

    setup_sidecar_table(en_con)

    rows = load_actual_material_rows(op_con)
    log(f"=== 자재 actual_cost rows: {len(rows)} ===")
    log(f"  vendor 정규화 sample (5개):")
    for row in rows[:5]:
        log(f"    {row['vendor_norm'][:30] if row['vendor_norm'] else '(none)':30s}  desc='{row['raw_description'][:30]}'")
    log()

    quote_lookup = build_quote_lookup(en_con)
    log(f"=== 견적서 lookup ===")
    log(f"  unique (vendor, project) cells: {len(quote_lookup)}")
    log(f"  sample (5개):")
    for k, v in list(quote_lookup.items())[:5]:
        log(f"    ({k[0][:20]}, {k[1]}) → {len(v)} wcs: {[(q['work_code'], int(q['amount']/1000)) for q in v]}")
    log()

    # 각 row 에 대해 corrected_wc 결정
    correction_log = []
    n_changed = 0
    n_kept = 0
    n_no_evidence = 0
    by_evidence: dict[str, int] = defaultdict(int)
    by_change: dict[tuple[str, str], int] = defaultdict(int)
    amount_by_change: dict[tuple[str, str], int] = defaultdict(int)

    for row in rows:
        corrected_wc, evidence, conf = determine_corrected_wc(row, quote_lookup)
        original_wc = row["current_wc"]
        changed = (corrected_wc != original_wc)
        if changed:
            n_changed += 1
            by_change[(original_wc, corrected_wc)] += 1
            amount_by_change[(original_wc, corrected_wc)] += row["amount"]
        elif evidence == "no_evidence":
            n_no_evidence += 1
        else:
            n_kept += 1
        by_evidence[evidence.split(":")[0]] += 1

        # sidecar 적재 — 변경된 row 만 또는 모두?
        # 우선 모두 (original==corrected 도 confirmed 의미로 활용 가능)
        en_con.execute("""
            INSERT INTO actual_cost_corrections
              (actual_cost_id, original_wc, corrected_wc, evidence, confidence,
               raw_description, vendor_norm, project_code, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["actual_cost_id"], original_wc, corrected_wc, evidence, conf,
            row["raw_description"], row["vendor_norm"], row["project_code"], row["amount"],
        ))
        if changed:
            correction_log.append({
                "actual_cost_id": row["actual_cost_id"],
                "from_wc":        original_wc,
                "to_wc":          corrected_wc,
                "evidence":       evidence,
                "confidence":     conf,
                "raw_description": row["raw_description"],
                "amount":         row["amount"],
                "project_code":   row["project_code"],
            })
    en_con.commit()

    log(f"=== 재분류 결과 ===")
    log(f"  total rows: {len(rows)}")
    log(f"  changed (corrected != original): {n_changed}")
    log(f"  kept (original confirmed): {n_kept}")
    log(f"  no evidence (변경 없음): {n_no_evidence}")
    log()
    log(f"=== evidence source 분포 ===")
    for ev, n in sorted(by_evidence.items(), key=lambda x: -x[1]):
        log(f"  {ev:20s}: {n}")
    log()
    log(f"=== 재분류 from → to (top 15) ===")
    for (f, t), n in sorted(by_change.items(), key=lambda x: -amount_by_change[x[0]])[:15]:
        amt = amount_by_change[(f, t)]
        log(f"  {f:12s} → {t:12s}  n={n:>2d}  amt={amt/1e6:>5.1f}M")
    log()
    log(f"=== 재분류 sample (top 20 by amount) ===")
    correction_log.sort(key=lambda x: -x["amount"])
    for c in correction_log[:20]:
        log(f"  [{c['project_code'][:18]:18s}] {c['from_wc']:10s} → {c['to_wc']:10s} "
            f"amt={c['amount']/1e3:>6.0f}K  conf={c['confidence']:.2f}  "
            f"desc='{c['raw_description'][:40]}'")
    log()

    # === LOO wMAPE 측정 ===
    log("=== corrected actual 로 LOO backtest ===")
    # corrected wc 적용해서 samples 재구성
    correction_map = {row["actual_cost_id"]: determine_corrected_wc(row, quote_lookup)[0]
                      for row in rows}

    norm = workcode_normalize_map(op_con)
    raw_all = list(op_con.execute("""
        SELECT
          ac.actual_cost_id, ac.project_id, ac.work_code_id,
          COALESCE(ac.source_ref, 'unknown') AS cost_type,
          ac.total_amount AS amount,
          p.project_code,
          mt.module_code, mt.floor_area_m2, mt.pyeong,
          UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
          mt.structure_type
        FROM actual_costs ac
        JOIN projects p              ON ac.project_id = p.project_id
        LEFT JOIN project_modules pm ON p.project_id = pm.project_id
        LEFT JOIN module_types mt    ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0
          AND ac.promotion_status IN ('approved','promoted','validated')
    """))

    # baseline samples
    def build_samples(use_correction: bool):
        grouped: dict[tuple, dict] = {}
        for r in raw_all:
            nwc = norm.get(r["work_code_id"])
            if not nwc:
                continue
            area = float(r["floor_area_m2"] or 0)
            if area <= 0:
                continue
            ct = r["cost_type"]
            if use_correction and ct == "재료비" and r["actual_cost_id"] in correction_map:
                wc = correction_map[r["actual_cost_id"]]
            else:
                wc = nwc["normalized_code"]
            key = (r["project_id"], wc, ct)
            if key in grouped:
                grouped[key]["amount"] += int(r["amount"] or 0)
            else:
                grouped[key] = {
                    "project_id":           r["project_id"],
                    "project_code":         r["project_code"],
                    "module_code":          r["module_code"],
                    "normalized_work_code": wc,
                    "work_name":            wc,
                    "category":             nwc["category"],
                    "cost_type":            ct,
                    "amount":               int(r["amount"] or 0),
                    "floor_area_m2":        area,
                    "pyeong":               float(r["pyeong"] or 0),
                    "grade":                r["grade"],
                    "structure_type":       r["structure_type"] or "STEEL",
                }
        out = []
        for s in grouped.values():
            s["rate_per_m2"] = s["amount"] / s["floor_area_m2"]
            if s["rate_per_m2"] > 0:
                out.append(s)
        return out

    samples_baseline = build_samples(use_correction=False)
    samples_corrected = build_samples(use_correction=True)
    log(f"  baseline samples : {len(samples_baseline)}")
    log(f"  corrected samples: {len(samples_corrected)}")

    # projects
    projects = [dict(r) for r in op_con.execute("""
        SELECT p.project_id, p.project_code, p.project_name,
               mt.module_code, mt.floor_area_m2, mt.pyeong,
               UPPER(COALESCE(mt.finish_grade, 'UNKNOWN')) AS grade,
               SUM(ac.total_amount) AS actual_total
        FROM projects p
        JOIN actual_costs ac          ON p.project_id = ac.project_id
        LEFT JOIN project_modules pm  ON p.project_id = pm.project_id
        LEFT JOIN module_types mt     ON pm.module_type_id = mt.module_type_id
        WHERE ac.total_amount > 0 AND mt.floor_area_m2 IS NOT NULL AND mt.floor_area_m2 > 0
        GROUP BY p.project_id
        HAVING actual_total > 1000000
        ORDER BY actual_total DESC
    """)]

    def run_loo(samples):
        full_pool = Pool.from_samples(samples)
        records = []
        wc_errs: dict[str, dict] = defaultdict(lambda: {"abs": 0, "actual": 0})
        ct_errs: dict[str, dict] = defaultdict(lambda: {"abs": 0, "actual": 0})
        for proj in projects:
            pid = proj["project_id"]
            train = full_pool.exclude_project(pid)
            actual_kv: dict = defaultdict(int)
            for s in samples:
                if s["project_id"] == pid:
                    actual_kv[(s["normalized_work_code"], s["cost_type"])] += s["amount"]
            if not actual_kv:
                continue
            pred = predict_for_module(train, grade=proj["grade"],
                                      pyeong=float(proj["pyeong"] or 0),
                                      area_m2=float(proj["floor_area_m2"]))
            pred_kv = {(b["work_code"], b["cost_type"]): b["amount"] for b in pred["breakdown"]}
            for k in set(actual_kv) | set(pred_kv):
                a = actual_kv.get(k, 0)
                p = pred_kv.get(k, 0)
                wc, ct = k
                if a > 0:
                    wc_errs[wc]["abs"] += abs(p - a)
                    wc_errs[wc]["actual"] += a
                    ct_errs[ct]["abs"] += abs(p - a)
                    ct_errs[ct]["actual"] += a
            actual_mat = sum(v for k, v in actual_kv.items() if k[1] == "재료비")
            pred_mat   = sum(v for k, v in pred_kv.items()   if k[1] == "재료비")
            actual_tot = sum(actual_kv.values())
            records.append({
                "project_code": proj["project_code"],
                "actual_total": actual_tot,
                "pred_total":   pred["total"],
                "actual_mat":   actual_mat,
                "pred_mat":     pred_mat,
            })
        def wmape_proj(records, key_a, key_p):
            num = sum(abs(r[key_p] - r[key_a]) for r in records if r[key_a] > 0)
            den = sum(r[key_a] for r in records if r[key_a] > 0)
            return num / den * 100 if den else None
        return {
            "overall_wmape":    wmape_proj(records, "actual_total", "pred_total"),
            "material_wmape":   wmape_proj(records, "actual_mat",   "pred_mat"),
            "by_wc":            {wc: (v["abs"]/v["actual"]*100 if v["actual"] else None,
                                       v["abs"], v["actual"]) for wc, v in wc_errs.items()},
            "by_ct":            {ct: (v["abs"]/v["actual"]*100 if v["actual"] else None,
                                       v["abs"], v["actual"]) for ct, v in ct_errs.items()},
            "projects":         records,
        }

    base = run_loo(samples_baseline)
    corr = run_loo(samples_corrected)

    log()
    log(f"=== wMAPE 비교 ===")
    log(f"  {'metric':25s} {'baseline':>10s} {'corrected':>10s} {'delta':>8s}")
    for label, b, c in [
        ("전체 wMAPE",       base["overall_wmape"],     corr["overall_wmape"]),
        ("자재 wMAPE",       base["material_wmape"],    corr["material_wmape"]),
    ]:
        delta = (c - b) if (b is not None and c is not None) else None
        log(f"  {label:25s} {b:>9.1f}% {c:>9.1f}% {delta:>+7.1f}pp")
    log()

    log(f"=== cost_type 비교 (셀-단위 wMAPE) ===")
    log(f"  {'ct':15s} {'b_wMAPE':>8s} {'c_wMAPE':>8s} {'delta':>8s}")
    for ct in set(base["by_ct"]) | set(corr["by_ct"]):
        b = base["by_ct"].get(ct, (None, 0, 0))
        c = corr["by_ct"].get(ct, (None, 0, 0))
        b_str = f"{b[0]:.1f}%" if b[0] is not None else "-"
        c_str = f"{c[0]:.1f}%" if c[0] is not None else "-"
        delta = (c[0] - b[0]) if (b[0] is not None and c[0] is not None) else None
        d_str = f"{delta:+.1f}pp" if delta is not None else "-"
        log(f"  {ct:15s} {b_str:>8s} {c_str:>8s} {d_str:>8s}")
    log()

    log(f"=== 자재 work_code 비교 (top 12 by abs_diff) ===")
    log(f"  {'wc':12s} {'b_wMAPE':>8s} {'c_wMAPE':>8s} {'b_abs':>7s} {'c_abs':>7s}  notes")
    all_wcs = set(base["by_wc"]) | set(corr["by_wc"])
    rows_sorted = []
    for wc in all_wcs:
        b = base["by_wc"].get(wc, (None, 0, 0))
        c = corr["by_wc"].get(wc, (None, 0, 0))
        rows_sorted.append((wc, b, c))
    rows_sorted.sort(key=lambda x: -max(x[1][1], x[2][1]))
    for wc, b, c in rows_sorted[:12]:
        b_str = f"{b[0]:.1f}%" if b[0] is not None else "-"
        c_str = f"{c[0]:.1f}%" if c[0] is not None else "-"
        log(f"  {wc:12s} {b_str:>8s} {c_str:>8s} {b[1]/1e6:>6.1f}M {c[1]/1e6:>6.1f}M")

    out_path = ROOT / "harness" / "reports" / "_correction_wmape.txt"
    out_path.write_text("\n".join(LOG), encoding="utf-8")

    # 변경된 row 만 dump 도 저장
    correction_log.sort(key=lambda x: -x["amount"])
    (ROOT / "harness" / "reports" / "actual_corrections.json").write_text(
        json.dumps(correction_log, ensure_ascii=False, indent=2), encoding="utf-8")

    op_con.close()
    en_con.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"ERROR: {e}\n{traceback.format_exc()}")
        out_path = ROOT / "harness" / "reports" / "_correction_wmape.txt"
        out_path.write_text("\n".join(LOG), encoding="utf-8")
