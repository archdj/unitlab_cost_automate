"""Standalone FastAPI for v10.0-notion. Run with:

    python -m uvicorn src.server:app --port 8001 --reload

The same model functions are also imported by the main backend
(unitlab-cost-analysis/web/backend/main.py) so this server is optional —
useful for isolated testing or running the notion model on its own machine.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import connect_readonly, list_modules, list_projects_for_backtest
from notion_cost_model import (
    Pool,
    build_pool,
    predict_for_module,
    predict_request,
    MODEL_VERSION,
)
from backtest import run as run_backtest

app = FastAPI(title="Unitlab Notion-only Cost Model", version="10.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# In-process pool cache (rebuilds on demand)
_pool_cache: Pool | None = None


def get_pool(force: bool = False) -> Pool:
    global _pool_cache
    if _pool_cache is None or force:
        _pool_cache = build_pool()
    return _pool_cache


@app.get("/api/notion/health")
def health() -> dict:
    pool = get_pool()
    return {
        "ok": True,
        "model_version": MODEL_VERSION,
        "samples": len(pool.samples),
        "cells": len(pool.by_key),
        "total_projects": pool.total_projects,
    }


@app.get("/api/notion/modules")
def modules() -> list[dict]:
    con = connect_readonly()
    try:
        return list_modules(con)
    finally:
        con.close()


@app.post("/api/notion/estimate")
def estimate(body: dict) -> dict:
    pool = get_pool()
    mods = body.get("modules") or []
    if not mods:
        raise HTTPException(400, "modules required")
    return predict_request(pool, mods)


@app.post("/api/notion/estimate/raw")
def estimate_raw(body: dict) -> dict:
    """입력이 module_code가 아닌 (grade, pyeong, area_m2)일 때 직접 예측."""
    pool = get_pool()
    grade = (body.get("grade") or "ESSENTIAL").upper()
    pyeong = float(body.get("pyeong") or 0)
    area = float(body.get("area_m2") or 0)
    if area <= 0:
        raise HTTPException(400, "area_m2 required")
    return predict_for_module(pool, grade=grade, pyeong=pyeong, area_m2=area)


@app.post("/api/notion/refresh")
def refresh() -> dict:
    pool = get_pool(force=True)
    return {"ok": True, "samples": len(pool.samples), "cells": len(pool.by_key)}


@app.get("/api/notion/backtest")
def backtest() -> dict:
    return run_backtest()


@app.get("/api/notion/pool")
def pool_summary() -> dict:
    """공종별·비용유형별 학습 풀 요약."""
    pool = get_pool()
    by_workcode: dict[str, dict] = {}
    for (wc, ct), rows in pool.by_key.items():
        d = by_workcode.setdefault(wc, {
            "work_code": wc,
            "samples": 0,
            "amount": 0,
            "cost_types": set(),
            "applicability": 0.0,
        })
        d["samples"] += len(rows)
        d["amount"]  += sum(r["amount"] for r in rows)
        d["cost_types"].add(ct)
    rows: list[dict] = []
    for d in by_workcode.values():
        d["cost_types"] = sorted(d["cost_types"])
        d["applicability"] = round(pool.applicability(d["work_code"], d["cost_types"][0]), 3)
        rows.append(d)
    rows.sort(key=lambda x: -x["amount"])
    return {
        "model_version": MODEL_VERSION,
        "total_projects": pool.total_projects,
        "rows": rows,
    }
