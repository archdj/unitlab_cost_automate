"""Standalone FastAPI for v10.1-notion-sidecar-quote. Run with:

    python -m uvicorn src.server:app --port 8001 --reload

학습 풀 (default v2 production):
  - sidecar `autocost_enriched.db` (N=15, 학습 풀 풍부)
  - quote correction 적용 (자재 wMAPE proj-sum -3.15pp 안정 개선)
  - F scenario filter (noise wc 제외, all statuses, drop MIXED)

POOL_MODE=v1 환경변수로 레거시 v1 (운영 DB N=8) 사용 가능.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_access import connect_readonly, list_modules, list_projects_for_backtest
from notion_cost_model import (
    Pool,
    build_pool,
    build_pool_v2,
    predict_for_module,
    predict_request,
    MODEL_VERSION,
    MODEL_VERSION_V2,
)
from backtest import run as run_backtest

POOL_MODE = os.environ.get("POOL_MODE", "v2").lower()  # default v2 production

app = FastAPI(
    title="Unitlab Notion Cost Model",
    version="10.1" if POOL_MODE == "v2" else "10.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# In-process pool cache (rebuilds on demand)
_pool_cache: Pool | None = None
_pool_meta: dict | None = None


def get_pool(force: bool = False) -> Pool:
    global _pool_cache, _pool_meta
    if _pool_cache is None or force:
        if POOL_MODE == "v1":
            _pool_cache = build_pool()
            _pool_meta = {"model_version": MODEL_VERSION, "pool_mode": "v1"}
        else:
            _pool_cache, build_meta = build_pool_v2(apply_quote_corrections=True)
            _pool_meta = {**build_meta, "pool_mode": "v2"}
    return _pool_cache


def get_pool_meta() -> dict:
    if _pool_meta is None:
        get_pool()
    return _pool_meta or {}


_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if _WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")


@app.get("/")
def root_redirect() -> dict:
    return {"ok": True, "ui": "/web/", "api_prefix": "/api/notion"}


@app.get("/api/notion/health")
def health() -> dict:
    pool = get_pool()
    meta = get_pool_meta()
    return {
        "ok": True,
        "model_version": meta.get("model_version", MODEL_VERSION),
        "pool_mode": meta.get("pool_mode", "?"),
        "samples": len(pool.samples),
        "cells": len(pool.by_key),
        "total_projects": pool.total_projects,
        "quote_correction_applied": meta.get("quote_correction_applied", False),
        "build_meta": meta,
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
    meta = get_pool_meta()
    return {
        "ok": True,
        "model_version": meta.get("model_version"),
        "samples": len(pool.samples),
        "cells": len(pool.by_key),
        "total_projects": pool.total_projects,
    }


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
    meta = get_pool_meta()
    return {
        "model_version": meta.get("model_version", MODEL_VERSION),
        "pool_mode": meta.get("pool_mode", "?"),
        "total_projects": pool.total_projects,
        "rows": rows,
    }
