"""FastAPI backend for the Safe Procure web app.

Endpoints
  GET  /                          the single-page app
  GET  /api/health                key + model status
  POST /api/dataset/sample        generate a synthetic dataset (user-controlled size/seed/categories)
  POST /api/dataset/upload        upload CSV/XLSX; columns auto-mapped
  POST /api/dataset/{id}/score    instant deterministic scorecard for any weights (what-if, no LLM)
  POST /api/runs                  launch the multi-agent flow in the background
  GET  /api/runs/{id}/events      Server-Sent Events stream of the live agent trace
  GET  /api/runs/{id}             final result JSON
  POST /api/runs/{id}/chat        ask the Procurement Copilot about this run
  GET  /api/runs/{id}/report      downloadable executive report (HTML)
  GET  /api/runs/{id}/csv         downloadable scorecard (CSV)
  GET  /api/runs/saved/latest     last completed run (offline backup)
"""
from __future__ import annotations

import asyncio
import io
import json
import threading
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics as A
from . import data as D
from .config import DEFAULT_WEIGHTS, ENDPOINTS, TIERS, keys_status
from .flow import prepare_context, run_analysis
from .llm import PACER
from .telemetry import RunTelemetry

ROOT = Path(__file__).parent
WEB = ROOT / "web"
RUNS_DIR = Path.cwd() / "runs"
RUNS_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Safe Procure", docs_url="/api/docs")
DATASETS: dict[str, dict[str, Any]] = {}
RUNS: dict[str, dict[str, Any]] = {}


def _clean_json(o: Any) -> Any:
    return json.loads(json.dumps(o, default=str))


def _dataset_payload(ds_id: str, df: pd.DataFrame, notes: list[str]) -> dict[str, Any]:
    d, q = A.clean(df)
    k = A.vendor_kpis(d)
    s = A.score(k)
    DATASETS[ds_id] = {"df": df, "notes": notes}
    preview = df.head(40).fillna("").to_dict("records")
    return _clean_json({
        "dataset_id": ds_id, "notes": notes, "quality": q, "columns": list(df.columns), "preview": preview,
        "row_count": len(df), "scorecard": _score_rows(s),
        "monthly_spend": A.spend_analysis(d, k)["monthly"],
    })


def _score_rows(s: pd.DataFrame) -> list[dict[str, Any]]:
    return [{"vendor": r.vendor_name, "category": r.category, "region": r.region, "composite": round(r.composite, 1),
             "tier": r.tier, "rank": int(r.rank), "internal_risk": round(r.internal_risk, 1), "spend": float(r.spend_total),
             "pillars": {p: round(getattr(r, p), 1) for p in A.PILLARS},
             "on_time_pct": round(r.on_time_pct, 1), "defect_rate_pct": round(r.defect_rate_pct, 2),
             "price_variance_pct": round(r.price_variance_pct, 2), "otd_trend": round(r.otd_trend, 2),
             "otd_series": r.otd_series} for r in s.itertuples()]


# ------------------------------------------------------------------ health
@app.get("/api/health")
def health():
    ks = keys_status()
    return {"keys": ks, "tiers": {k: [e.label for e in t.chain] for k, t in TIERS.items()},
            "endpoints": [{"label": e.label, "provider": e.provider, "model": e.model, "tpm": e.tpm, "rpm": e.rpm,
                           "available": ks.get(e.provider, False)} for e in ENDPOINTS],
            "pacer": PACER.snapshot(), "default_weights": DEFAULT_WEIGHTS, "categories": list(D.CATEGORIES),
            "saved_run": (RUNS_DIR / "latest.json").exists()}


# ---------------------------------------------------------------- datasets
class SampleReq(BaseModel):
    n_vendors: int = 20
    months: int = 18
    seed: int = 42
    categories: list[str] | None = None
    inject_quality_issues: bool = True


@app.post("/api/dataset/sample")
def sample(req: SampleReq):
    spec = D.GenSpec(n_vendors=max(5, min(25, req.n_vendors)), months=max(6, min(36, req.months)), seed=req.seed,
                     categories=tuple(req.categories or D.CATEGORIES), inject_quality_issues=req.inject_quality_issues)
    df = D.generate(spec)
    return _dataset_payload(uuid.uuid4().hex[:10], df, ["Synthetic dataset: all vendor names are fictional."])


@app.post("/api/dataset/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 15_000_000:
        raise HTTPException(413, "File too large (max 15 MB).")
    try:
        df, notes = D.normalise_upload(raw, file.filename or "upload.csv")
    except Exception as err:  # noqa: BLE001
        raise HTTPException(422, f"Could not read this file: {err}") from err
    return _dataset_payload(uuid.uuid4().hex[:10], df, notes)


@app.get("/api/dataset/{ds_id}/csv")
def dataset_csv(ds_id: str):
    ds = DATASETS.get(ds_id) or HTTPException(404)
    if isinstance(ds, HTTPException):
        raise ds
    buf = io.StringIO()
    ds["df"].to_csv(buf, index=False)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="safe_procure_vendors.csv"'})


class ScoreReq(BaseModel):
    weights: dict[str, float] = DEFAULT_WEIGHTS


@app.post("/api/dataset/{ds_id}/score")
def rescore(ds_id: str, req: ScoreReq):
    ds = DATASETS.get(ds_id)
    if not ds:
        raise HTTPException(404, "Dataset expired; reload sample or upload again.")
    d, _ = A.clean(ds["df"])
    return _clean_json({"scorecard": _score_rows(A.score(A.vendor_kpis(d), req.weights))})


# -------------------------------------------------------------------- runs
class RunReq(BaseModel):
    dataset_id: str
    question: str = ""
    weights: dict[str, float] = DEFAULT_WEIGHTS
    risk_threshold: float = 55
    otd_floor: float = 85
    defect_ceiling: float = 3.0
    focus_categories: list[str] = []


def _worker(run_id: str, ctx) -> None:
    try:
        result = run_analysis(ctx)
        result = _clean_json(result)
        RUNS[run_id]["result"] = result
        (RUNS_DIR / f"{run_id}.json").write_text(json.dumps(result), encoding="utf-8")
        if not result.get("degraded") or len(result["degraded"]) < 4:
            (RUNS_DIR / "latest.json").write_text(json.dumps(result), encoding="utf-8")
    except Exception as err:  # noqa: BLE001
        ctx.telemetry.emit("run_error", message=str(err)[:400])
        ctx.telemetry.close()
    finally:
        RUNS[run_id]["done"] = True


@app.post("/api/runs")
def start_run(req: RunReq):
    ds = DATASETS.get(req.dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset expired; reload sample or upload again.")
    if not any(keys_status().values()):
        raise HTTPException(400, "No API keys configured on the server.")
    run_id = uuid.uuid4().hex[:8]
    tel = RunTelemetry(run_id)
    ctx = prepare_context(ds["df"], weights=req.weights, risk_threshold=req.risk_threshold, question=req.question.strip()[:600],
                          focus_categories=req.focus_categories, otd_floor=req.otd_floor, defect_ceiling=req.defect_ceiling,
                          telemetry=tel)
    RUNS[run_id] = {"telemetry": tel, "ctx": ctx, "result": None, "done": False}
    threading.Thread(target=_worker, args=(run_id, ctx), daemon=True).start()
    return {"run_id": run_id, "vendors_in_scope": len(ctx.in_scope)}


@app.get("/api/runs/{run_id}/events")
async def events(run_id: str):
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    tel: RunTelemetry = run["telemetry"]

    async def gen():
        seq = 0
        while True:
            batch = await asyncio.to_thread(tel.since, seq, 10.0)
            for ev in batch:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            seq += len(batch)
            if tel.closed and seq >= len(tel.events):
                yield "event: done\ndata: {}\n\n"
                return
            if not batch:
                yield ": keep-alive\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/runs/{run_id}/poll")
def poll(run_id: str, since: int = 0):
    """Polling fallback for proxies that buffer Server-Sent Events."""
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    tel: RunTelemetry = run["telemetry"]
    evs = tel.events[since:]
    return {"events": _clean_json(evs), "done": bool(tel.closed)}


def _load_result(run_id: str) -> dict[str, Any]:
    if run_id == "latest":
        p = RUNS_DIR / "latest.json"
    else:
        run = RUNS.get(run_id)
        if run and run.get("result"):
            return run["result"]
        p = RUNS_DIR / f"{run_id}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    raise HTTPException(404, "Result not ready")


@app.get("/api/runs/saved/latest")
def latest():
    return _load_result("latest")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = RUNS.get(run_id)
    if run and not run["done"]:
        return JSONResponse({"status": "running", "events": len(run["telemetry"].events)}, status_code=202)
    if run and run["done"] and not run.get("result"):
        raise HTTPException(410, "Run failed before producing a result.")
    return _load_result(run_id)


class ChatReq(BaseModel):
    message: str
    history: list[dict[str, str]] = []


@app.post("/api/runs/{run_id}/chat")
def chat(run_id: str, req: ChatReq):
    from .copilot import answer
    result = _load_result(run_id)
    run = RUNS.get(run_id)
    return answer(result, req.message[:800], req.history[-8:], run["ctx"] if run else None)


@app.get("/api/runs/{run_id}/report")
def report(run_id: str):
    from .report import render_report
    html = render_report(_load_result(run_id))
    return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="safe_procure_report_{run_id}.html"'})


@app.get("/api/runs/{run_id}/csv")
def run_csv(run_id: str):
    r = _load_result(run_id)
    rows = [{"vendor": v["vendor"], "category": v["category"], "region": v["region"], "rank": v["rank"], "tier": v["tier"],
             "composite": v["composite"], **{f"pillar_{k}": x for k, x in v["pillars"].items()},
             "internal_risk": v["internal_risk"], "market_risk": v["market_risk"], "combined_risk": v["combined_risk"],
             "decision": (v.get("decision") or {}).get("decision", ""), "confidence": (v.get("decision") or {}).get("confidence", ""),
             "rationale": (v.get("decision") or {}).get("rationale", ""), "spend_inr": v["spend_total"]} for v in r["vendors"]]
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="safe_procure_scorecard_{run_id}.csv"'})


# --------------------------------------------------------------- frontend
@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=WEB), name="static")
