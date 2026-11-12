"""Dashboard API + static frontend.

    uv run biggame serve        # http://127.0.0.1:8050

Serves the JSON built by `biggame build` (data/dashboard/) and the files in frontend/.
Binds to localhost only: Research Data is TikTok Confidential Information.
"""

from __future__ import annotations

import json
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pipeline.config import DATA_DIR, ROOT  # importing config loads .env

DASH = DATA_DIR / "dashboard"
FRONTEND = ROOT / "frontend"

app = FastAPI(title="Big Game on TikTok", docs_url="/api/docs")


@app.middleware("http")
async def no_cache(request, call_next):
    """Make the browser revalidate every file, so front-end edits show on a normal reload."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _read(name: str) -> dict:
    p = DASH / f"{name}.json"
    if not p.exists():
        raise HTTPException(404, f"{p.name} not built yet; run `uv run biggame build`")
    return json.loads(p.read_text())


@app.get("/api/index")
def index() -> dict:
    return _read("index")


@app.get("/api/season/{year}")
def season(year: int) -> dict:
    return _read(str(year))


@app.get("/api/compare")
def compare() -> dict:
    """Every season's game-day timeline and summary, for the year-over-year view."""
    idx = _read("index")
    out = []
    for s in idx["seasons"]:
        d = _read(str(s["year"]))
        out.append({"year": s["year"], "winner": s["winner"], "summary": d.get("summary", {}),
                    "timeline_game": d.get("timeline_game", []), "timeline_daily": d.get("timeline_daily", []),
                    "emotions": d.get("emotions", {}), "topics": d.get("topics", [])})
    return {"seasons": out}


@app.get("/api/markets")
def markets() -> dict:
    """Live Polymarket odds (cached ~2 min): next Big Game, last year's market history, win totals."""
    from pipeline.markets import markets as fetch
    return fetch()


@app.post("/api/rebuild")
def rebuild() -> dict:
    """Re-run `biggame build` (after new collection or labeling)."""
    r = subprocess.run([sys.executable, "-m", "pipeline.cli", "build"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise HTTPException(500, r.stderr[-2000:])
    return {"ok": True, "built_at": _read("index")["built_at"]}


@app.get("/")
def home() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="frontend")
