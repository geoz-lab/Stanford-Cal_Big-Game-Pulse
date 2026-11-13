"""Standalone dashboard export: one HTML file that opens with a double-click (no server).

    uv run biggame export            # full version: every chart, comment and video (approved team only)
    uv run biggame export --public   # public version: results only, no comment text, creators or links

Each run writes dist/BigGamePulse_<full|public>_<date>.html and a .zip next to it.
The HTML embeds the dashboard data, styles, ECharts and images. Player headshots and fonts
still load from the web when online; offline, the page falls back to system fonts.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import zipfile
from datetime import datetime, timezone

from .config import DATA_DIR, ROOT

log = logging.getLogger(__name__)
FRONTEND = ROOT / "frontend"
DASH = DATA_DIR / "dashboard"
DIST = ROOT / "dist"

# Fields that carry TikTok user content: comment text, captions, creators, video links.
USER_CONTENT_LISTS = ("feed", "top_comments", "disagreements", "top_videos")
USER_CONTENT_KEYS = {"text", "caption", "username", "url", "top_text"}


def _read(name: str) -> dict:
    return json.loads((DASH / f"{name}.json").read_text())


def _strip_user_content(season: dict) -> dict:
    s = dict(season)
    for k in USER_CONTENT_LISTS:
        s[k] = []
    fb = dict(s.get("football") or {})
    fb["buzz"] = [{k: v for k, v in b.items() if k != "top_text"} for b in fb.get("buzz") or []]
    s["football"] = fb
    return s


def _find_user_content(obj, path="") -> list[str]:
    """Paths of any user-content fields left in obj (ESPN text and links are allowed)."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            espn = "scoring_plays" in p or (".football" in p and k == "url")  # ESPN, not TikTok
            if k in USER_CONTENT_KEYS and v and not espn:
                hits.append(p)
            hits += _find_user_content(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _find_user_content(v, f"{path}[{i}]")
    return hits


def _data(public: bool) -> dict:
    index = _read("index")
    seasons = {str(s["year"]): _read(str(s["year"])) for s in index["seasons"]}
    if public:
        seasons = {y: _strip_user_content(d) for y, d in seasons.items()}
    compare = {"seasons": [{"year": int(y), "winner": d["game"].get("winner") if isinstance(d.get("game"), dict) else None,
                            "summary": d.get("summary", {}), "timeline_game": d.get("timeline_game", []),
                            "timeline_daily": d.get("timeline_daily", []), "emotions": d.get("emotions", {}),
                            "topics": d.get("topics", [])} for y, d in seasons.items()]}
    for row, s in zip(compare["seasons"], index["seasons"]):  # same winner field the backend serves
        row["winner"] = s["winner"]
    try:
        from .markets import markets
        mk = markets()
    except Exception as exc:  # offline export still works, just without odds
        log.warning("Polymarket snapshot failed: %s", exc)
        mk = None
    out = {"public": public, "exported_at": datetime.now(timezone.utc).isoformat(),
           "index": index, "seasons": seasons, "compare": compare, "markets": mk}
    if public:
        left = _find_user_content({"seasons": seasons})
        if left:
            raise RuntimeError(f"user content left in public export: {left[:5]}")
    return out


def _data_uri(path) -> str:
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[path.suffix.lower()]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _inline_script(js: str) -> str:
    return "<script>" + js.replace("</script", "<\\/script") + "</script>"


def export(public: bool = False) -> str:
    html = (FRONTEND / "index.html").read_text()
    css = (FRONTEND / "styles.css").read_text()
    html = re.sub(r'<link rel="stylesheet" href="styles\.css[^"]*">', lambda _: f"<style>\n{css}\n</style>", html)
    html = re.sub(r'<script src="vendor/echarts\.min\.js[^"]*"></script>',
                  lambda _: _inline_script((FRONTEND / "vendor/echarts.min.js").read_text()), html)
    data = json.dumps(_data(public), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = re.sub(r'<script src="app\.js[^"]*"></script>',
                  lambda _: f"<script>window.__BG__ = {data};</script>\n" + _inline_script((FRONTEND / "app.js").read_text()), html)
    for name in ("hero.jpg", "logo.png", "favicon.png"):
        html = html.replace(f"assets/{name}", _data_uri(FRONTEND / "assets" / name))
    if public:
        html = html.replace("<title>Big Game Pulse</title>", "<title>Big Game Pulse (public version)</title>")

    kind = "public" if public else "full"
    stem = f"BigGamePulse_{kind}_{datetime.now().strftime('%Y-%m-%d')}"
    DIST.mkdir(exist_ok=True)
    out = DIST / f"{stem}.html"
    out.write_text(html)
    note = ("Big Game Pulse: standalone dashboard\n\nDouble-click BigGamePulse.html to open it in a browser. "
            "No server or install is needed. Odds are a snapshot from the export date.\n\n")
    note += ("PUBLIC VERSION: aggregate results only. Comment text, creators and video links are left out, "
             "per the TikTok Research API terms. Send TikTok a copy at least 7 days before publishing.\n"
             if public else
             "FULL VERSION: contains TikTok Research Data (comment text, creators, video links). "
             "TikTok Confidential Information: share only within the approved research team. Do not post publicly.\n")
    with zipfile.ZipFile(DIST / f"{stem}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(out, "BigGamePulse.html")
        z.writestr("README.txt", note)
    log.info("wrote %s (%.1f MB) and %s.zip", out.name, out.stat().st_size / 1e6, stem)
    return str(out)
