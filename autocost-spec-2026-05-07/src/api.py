"""FastAPI 진입점. 명세서 §1.5 (김대리 시나리오) 의 MVP 흐름.

엔드포인트:
  GET  /                  — 단일 페이지 Admin UI
  GET  /api/health        — 운영 DB 연결 확인
  GET  /api/modules       — 모듈 목록 (F6 입력 폼 옵션)
  GET  /api/projects      — 프로젝트 메타 (F6 / F3.1.1)
  POST /api/predict       — 예측 + 근거 (F2 + F7)
  GET  /api/profile       — 데이터 품질 프로파일 (M0)
  GET  /api/coverage      — material_aliases 매칭 커버리지 (M0)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, loaders
from .config import MODEL_VERSION, OPERATIONAL_DB
from .explain import data_quality, similar_projects, top_features
from .model import build_pool, predict_request

app = FastAPI(title="AI 기반 원가 예측 프로그램", version=MODEL_VERSION)

WEB_DIR = Path(__file__).resolve().parent / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# ─── Schemas ──────────────────────────────────────────────────────────────

class ModuleRequest(BaseModel):
    module_code: str
    quantity: int = Field(default=1, ge=1)


class PredictRequest(BaseModel):
    modules: list[ModuleRequest] = Field(min_length=1)
    loss_rate_default: float | None = None
    loss_rate_lower:   float | None = None
    loss_rate_upper:   float | None = None


# ─── In-memory pool cache (학습 1회 후 재사용) ─────────────────────────────

_POOL = None


def get_pool():
    global _POOL
    if _POOL is None:
        _POOL = build_pool()
    return _POOL


# ─── Routes ────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    try:
        con = db.connect_readonly()
        n = con.execute("SELECT COUNT(*) FROM actual_costs").fetchone()[0]
        con.close()
        return {"ok": True, "db": str(OPERATIONAL_DB), "actual_costs": n,
                "model_version": MODEL_VERSION}
    except Exception as e:
        raise HTTPException(500, detail=f"DB 연결 실패: {e}")


@app.get("/api/modules")
def modules():
    con = db.connect_readonly()
    try:
        return {"modules": db.list_modules(con)}
    finally:
        con.close()


@app.get("/api/projects")
def projects():
    con = db.connect_readonly()
    try:
        return {"projects": db.list_projects(con)}
    finally:
        con.close()


@app.post("/api/predict")
def predict(req: PredictRequest):
    pool = get_pool()
    payload = [m.model_dump() for m in req.modules]
    result = predict_request(pool, payload)

    # 로스율 가정 적용 (F6.1.2): 입력 받은 상한/하한으로 ci 보정
    if req.loss_rate_default is not None:
        factor = 1.0 + req.loss_rate_default
        result["loss_rate_applied"] = req.loss_rate_default
        result["total_with_loss"] = int(round(result["total"] * factor))
    if req.loss_rate_lower is not None:
        result["confidence_lower_with_loss"] = int(
            round(result["confidence_lower"] * (1.0 + req.loss_rate_lower))
        )
    if req.loss_rate_upper is not None:
        result["confidence_upper_with_loss"] = int(
            round(result["confidence_upper"] * (1.0 + req.loss_rate_upper))
        )

    # F7 근거 패널
    first_module = result["modules"][0] if result["modules"] else None
    if first_module:
        pred = first_module["predicted"]
        result["evidence"] = {
            "top_features": top_features(pred, n=5),
            "similar_projects": similar_projects(
                pool,
                grade=pred["input"]["grade"],
                area_m2=pred["input"]["area_m2"],
                n=3,
            ),
            "data_quality": data_quality(pool),
        }
    return result


@app.get("/api/profile")
def profile():
    con = db.connect_readonly()
    try:
        return db.profile_actual_costs(con)
    finally:
        con.close()


@app.get("/api/coverage")
def coverage():
    con = db.connect_readonly()
    try:
        return db.measure_alias_coverage(con)
    finally:
        con.close()


# ─── F4 업로드 — 파싱 + alias 매칭 + (선택) 저장 ──────────────────────────

import io as _io
import json as _json
from datetime import datetime as _dt

from .config import HARNESS_REPORTS

_ALIAS_IDX = None


def get_alias_index():
    global _ALIAS_IDX
    if _ALIAS_IDX is None:
        con = db.connect_readonly()
        try:
            _ALIAS_IDX = db.build_alias_token_index(con)
        finally:
            con.close()
    return _ALIAS_IDX


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    sheet: str | None = Form(default=None),
    preview_rows: int = Form(default=10),
    save: bool = Form(default=False),
):
    contents = await file.read()
    try:
        report = loaders.load_any(
            stream=_io.BytesIO(contents),
            filename=file.filename or "upload",
            sheet=sheet,
            preview_rows=preview_rows,
        )
    except Exception as e:
        raise HTTPException(500, detail=f"파싱 실패: {e}")

    # B) alias 토큰 매칭
    loaders.enrich_with_alias_match(report, get_alias_index())

    # A 일부) save=true 면 응답을 디스크에 보관
    if save:
        uploads_dir = HARNESS_REPORTS / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe = (file.filename or "upload").replace("/", "_").replace("\\", "_")
        out = uploads_dir / f"{ts}_{safe}.json"
        out.write_text(
            _json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        report.saved_to = str(out)

    return report.to_dict()
