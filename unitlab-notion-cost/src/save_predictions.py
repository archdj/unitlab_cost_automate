"""v10.0-notion 예측을 운영 DB의 cost_predictions에 저장.

LOO 방식으로 각 프로젝트 예측을 산출 → 저장. 그래야 화면에서 backtest와 동일한
오차로 비교 가능.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import (
    DB_PATH,
    connect_readonly,
    list_projects_for_backtest,
    load_actual_samples,
)
from notion_cost_model import Pool, predict_for_module, MODEL_VERSION


def save() -> dict:
    # readonly로 데이터 로드 → write 연결로 저장
    ro = connect_readonly()
    samples = load_actual_samples(ro)
    projects = list_projects_for_backtest(ro)
    ro.close()

    full_pool = Pool.from_samples(samples)

    # 운영 DB에 write 연결
    rw = sqlite3.connect(str(DB_PATH))
    cur = rw.cursor()

    # 기존 v10.0-notion prediction 삭제
    deleted = cur.execute(
        "DELETE FROM cost_predictions WHERE model_version = ?",
        (MODEL_VERSION,),
    ).rowcount

    inserted = 0
    for p in projects:
        pid = p["project_id"]
        train_pool = full_pool.exclude_project(pid)
        pred = predict_for_module(
            train_pool,
            grade=p["grade"],
            pyeong=float(p["pyeong"] or 0),
            area_m2=float(p["floor_area_m2"]),
        )
        actual = int(p["actual_total"] or 0)
        error_pct = (pred["total"] - actual) / actual * 100 if actual else None

        # module_type_id 조회
        mt_row = cur.execute(
            "SELECT module_type_id FROM module_types WHERE module_code = ?",
            (p["module_code"],),
        ).fetchone()
        mt_id = mt_row[0] if mt_row else None

        cur.execute("""
            INSERT INTO cost_predictions(
                project_id, module_type_id, predicted_total,
                confidence_lower, confidence_upper, breakdown,
                model_version, input_features, predicted_by,
                actual_amount, error_pct
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            pid,
            mt_id,
            pred["total"],
            pred["confidence_lower"],
            pred["confidence_upper"],
            json.dumps(pred["breakdown"], ensure_ascii=False),
            MODEL_VERSION,
            json.dumps({
                "grade": p["grade"],
                "pyeong": p["pyeong"],
                "area_m2": p["floor_area_m2"],
                "loo": True,
            }, ensure_ascii=False),
            "v10-loo-pipeline",
            actual,
            round(error_pct, 1) if error_pct is not None else None,
        ))
        inserted += 1

    rw.commit()
    rw.close()
    return {"deleted": deleted, "inserted": inserted, "model_version": MODEL_VERSION}


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    res = save()
    print(json.dumps(res, ensure_ascii=False, indent=2))
