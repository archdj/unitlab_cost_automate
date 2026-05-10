"""LOO backtest v5 — sidecar v2 (N=15) + 견적서 amount 보정.

v4 (운영 DB N=8) 의 sidecar 버전. 더 큰 학습 풀에서 quote correction 효과 측정.

매핑 bridge:
  quote_lines.project_code (예 N-01-T-15)
    → 운영 DB projects.notion_page_id (PR-1 적용)
    → sidecar projects_master.project_notion_id
    → v2 sample.project_id (notion_id hash)

자재 wMAPE 측정 단위:
  - cell-단위 wMAPE (work_code × cost_type 셀별)
  - project-sum wMAPE (프로젝트별 자재 합계)

비교: v2 baseline vs v2 + quote correction.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    connect_readonly,
    connect_enriched,
    load_actual_samples_v2,
    list_projects_for_backtest_v2,
)
from notion_cost_model import Pool, predict_for_module
from backtest_v2 import DEFAULT_FILTERS


REPORT_PATH = Path(__file__).resolve().parents[1] / "reports" / "backtest_v5_quote_sidecar.json"
MAT_LABEL = "MAT"

# quote_lines work_code (영어 정규화) → sidecar work_code_text (한글/번호 형식) 매핑.
# sidecar의 work_code_text는 노션 raw 한글 카테고리.
# 무매핑 시 영어 신규 셀 추가만 됨 = 자재 actual dilution (검증: baseline 515M vs corrected 603M, +17%).
QUOTE_WC_TO_SIDECAR = {
    "STR-ST":   "01. 골조",       # 철골 = 골조
    "FIN-PANEL": "02. 판넬",      # 샌드위치 판넬
    "FIN-CARP":  "13. 경량",      # 목공/경량 목조
    "FIN-FLOOR": "12. 마루",      # 바닥마감
    "EXT-WIN":   "03. 창호",
    "MEP-ELEC":  "05. 전기",
    "MEP-HVAC":  "07. 환기/공조",
    "FUR":       "14. 수장/도어",  # 가구인테리어 = 수장/도어 (sidecar에 'FUR' 코드도 일부 있지만 14. 수장/도어가 다수)
    "FUR-DOOR":  "08. 현관문",
    "EXT-DECK":  "29.데크",
    "SITE-DEMO": "토목",
}


def build_pcode_to_sidecar_pid_bridge(
    en_con: sqlite3.Connection,
    op_con: sqlite3.Connection,
) -> dict[str, int]:
    """quote_lines.project_code (N-XX) → v2 sample.project_id (sidecar hash).

    Bridge: op.projects(project_code, notion_page_id) → sidecar projects_master(project_notion_id).
    project_id는 v2의 _project_int_id(notion_page_id) hash.
    """
    from data_access import _project_int_id  # private but stable

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
    bridge = {}
    for pcode, nid in op_pcode_to_nid.items():
        if nid in sidecar_nids:
            bridge[pcode] = _project_int_id(nid)
    return bridge


def load_quote_sums_keyed_by_sidecar_pid(
    en_con: sqlite3.Connection,
    bridge: dict[str, int],
) -> tuple[dict[tuple[int, str], float], dict]:
    """quote_lines → (sidecar_pid, work_code) → amount sum.

    Returns (key_to_amount, stats: {n_quote_cells, n_mapped, n_skipped, total_amount}).
    """
    raw = list(en_con.execute("""
        SELECT project_code, work_code, SUM(amount) AS s
        FROM material_quote_lines
        WHERE project_code IS NOT NULL AND work_code IS NOT NULL AND amount IS NOT NULL
        GROUP BY project_code, work_code
    """))
    # quote work_code (영어) → sidecar work_code_text (한글) 매핑 + 같은 (pid, sidecar_wc) 중복은 합산
    out: dict[tuple, float] = defaultdict(float)
    n_mapped = 0
    n_skipped_proj = 0
    n_skipped_wc = 0
    total_amount_mapped = 0.0
    for r in raw:
        pcode = r["project_code"]
        sidecar_pid = bridge.get(pcode)
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


def apply_quote_corrections_v5(
    samples: list[dict],
    quote_keyed: dict[tuple[int, str], float],
) -> tuple[list[dict], dict]:
    """v2 sample list에 quote correction 적용. cell key = (project_id, work_code, MAT)."""
    pid_to_meta: dict[int, dict] = {}
    for s in samples:
        if s["project_id"] not in pid_to_meta:
            pid_to_meta[s["project_id"]] = s

    keyed = {(s["project_id"], s["normalized_work_code"], s["cost_type"]): s for s in samples}

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
        if key in keyed:
            old = keyed[key]["amount"]
            keyed[key]["amount"] = int(qsum)
            keyed[key]["rate_per_m2"] = qsum / keyed[key]["floor_area_m2"] if keyed[key]["floor_area_m2"] else 0
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
                "floor_area_m2":         meta["floor_area_m2"],
                "pyeong":                meta["pyeong"],
                "grade":                 meta["grade"],
                "structure_type":        meta["structure_type"],
                "rate_per_m2":           qsum / meta["floor_area_m2"] if meta["floor_area_m2"] else 0,
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


def run_loo(samples: list[dict], projects: list[dict]) -> dict:
    learnable = {p["project_id"] for p in projects if p["module_code"]}
    samples = [s for s in samples if s["project_id"] in learnable]
    full_pool = Pool.from_samples(samples)

    actuals_by_project: dict[int, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for s in samples:
        actuals_by_project[s["project_id"]][(s["normalized_work_code"], s["cost_type"])] += s["amount"]

    project_records = []
    cost_type_errors: dict[str, dict] = defaultdict(lambda: {"errors": [], "abs_diff": 0, "actual": 0})

    for proj in projects:
        pid = proj["project_id"]
        if pid not in learnable:
            continue
        train = full_pool.exclude_project(pid)
        actual_kv = actuals_by_project.get(pid, {})
        actual_total = sum(actual_kv.values())
        if actual_total <= 0:
            continue

        prediction = predict_for_module(
            train,
            grade=proj["grade"],
            pyeong=proj["pyeong"],
            area_m2=proj["floor_area_m2"],
        )
        pred_kv = {(b["work_code"], b["cost_type"]): b["amount"] for b in prediction["breakdown"]}

        for k in set(actual_kv) | set(pred_kv):
            wc, ct = k
            a = actual_kv.get(k, 0)
            p = pred_kv.get(k, 0)
            if a > 0:
                err = abs(p - a) / a
                cost_type_errors[ct]["errors"].append(err)
                cost_type_errors[ct]["abs_diff"] += abs(p - a)
                cost_type_errors[ct]["actual"] += a

        actual_mat = sum(v for k, v in actual_kv.items() if k[1] == MAT_LABEL)
        pred_mat = sum(v for k, v in pred_kv.items() if k[1] == MAT_LABEL)
        project_records.append({
            "project_code": proj["project_code"],
            "module_code":  proj["module_code"],
            "actual":       actual_total,
            "predicted":    prediction["total"],
            "actual_mat":   actual_mat,
            "pred_mat":     pred_mat,
            "abs_total_pct": round(abs(prediction["total"] - actual_total) / actual_total * 100, 1),
        })

    def proj_sum_wmape(records, key_a, key_p):
        diff = sum(abs(r[key_p] - r[key_a]) for r in records if r[key_a] > 0)
        actual = sum(r[key_a] for r in records if r[key_a] > 0)
        return round(diff / actual * 100, 1) if actual else None

    total_errs = [r["abs_total_pct"] / 100 for r in project_records]
    overall = {
        "n": len(project_records),
        "total_wmape_proj_sum": proj_sum_wmape(project_records, "actual", "predicted"),
        "total_mae_pct": round(sum(total_errs) / len(total_errs) * 100, 1) if total_errs else 0,
        "total_median_pct": round(statistics.median(total_errs) * 100, 1) if total_errs else 0,
        "total_within_20": f"{sum(1 for e in total_errs if e <= 0.20)}/{len(total_errs)}",
        "material_wmape_proj_sum": proj_sum_wmape(project_records, "actual_mat", "pred_mat"),
        "material_wmape_cell": round(
            cost_type_errors[MAT_LABEL]["abs_diff"] / cost_type_errors[MAT_LABEL]["actual"] * 100, 1
        ) if cost_type_errors[MAT_LABEL]["actual"] else None,
    }

    return {
        "overall": overall,
        "by_cost_type": [
            {
                "ct": ct,
                "n": len(d["errors"]),
                "wmape_cell": round(d["abs_diff"] / d["actual"] * 100, 1) if d["actual"] else None,
                "actual": d["actual"],
            }
            for ct, d in cost_type_errors.items()
        ],
        "projects": project_records,
    }


def main():
    op = connect_readonly()
    en = connect_enriched()

    bridge = build_pcode_to_sidecar_pid_bridge(en, op)
    print(f"=== bridge: quote project_code → sidecar project_id ===")
    print(f"  matched: {len(bridge)}")

    quote_keyed, qstats = load_quote_sums_keyed_by_sidecar_pid(en, bridge)
    print(f"\n=== quote_lines aggregation ===")
    print(f"  total cells (project_code × work_code): {qstats['n_quote_cells']}")
    print(f"  mapped (project + workcode 둘 다 매핑됨): {qstats['n_mapped']}")
    print(f"  skipped — project not in bridge: {qstats['n_skipped_project']}")
    print(f"  skipped — work_code 매핑 없음:   {qstats['n_skipped_workcode']}")
    print(f"  total quote amount mapped: ₩{qstats['total_amount_mapped']:,}")

    s_base = load_actual_samples_v2(en, op, **DEFAULT_FILTERS)
    projects = list_projects_for_backtest_v2(en, op)
    print(f"\n=== v2 baseline ===")
    print(f"  samples: {len(s_base)}")
    print(f"  projects (with module match): {len([p for p in projects if p['module_code']])}")

    r_base = run_loo(s_base, projects)

    s_c = [dict(s) for s in load_actual_samples_v2(en, op, **DEFAULT_FILTERS)]
    s_c, stats = apply_quote_corrections_v5(s_c, quote_keyed)
    r_corr = run_loo(s_c, projects)

    op.close(); en.close()

    print(f"\n=== quote correction stats ===")
    print(f"  cells replaced: {stats['n_replaced']}")
    print(f"  cells added:    {stats['n_added']}")
    print(f"  total |delta|:  ₩{stats['delta_amount']:,}")
    print(f"  skipped (pid not in learning pool): {stats['skipped_no_pool']}")

    print(f"\n=== Comparison (LOO N={r_base['overall']['n']}) ===")
    print(f"{'metric':38s}  {'BASELINE':>10s}  {'CORRECTED':>10s}  {'delta':>10s}")
    for k in ("total_wmape_proj_sum", "total_mae_pct", "total_median_pct", "material_wmape_proj_sum", "material_wmape_cell"):
        a = r_base["overall"].get(k)
        b = r_corr["overall"].get(k)
        if a is None or b is None:
            print(f"  {k:36s}  {'-':>10}  {'-':>10}")
            continue
        d = b - a
        print(f"  {k:36s}  {a:>9.1f}%  {b:>9.1f}%  {d:>+9.1f}pp")
    print(f"  {'total_within_20':36s}  {r_base['overall']['total_within_20']:>10}  {r_corr['overall']['total_within_20']:>10}")

    out = {
        "model_version": "v10.0-notion-v5-quote-sidecar",
        "data_source": "sidecar autocost_enriched.db (N=15) + material_quote_lines via notion_page_id bridge",
        "bridge_size": len(bridge),
        "quote_stats": qstats,
        "correction_stats": stats,
        "baseline": r_base,
        "corrected": r_corr,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
