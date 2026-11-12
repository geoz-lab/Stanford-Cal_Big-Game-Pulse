"""Polymarket odds for the Big Game and both teams' win totals.

Uses Polymarket's public APIs (no key): Gamma for events/markets/prices, CLOB for price history.
Live markets are cached for CACHE_TTL seconds; closed markets are cached on disk for good.
Prices are implied probabilities (0-1) shown for context, not betting advice.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import requests

from .config import DATA_DIR, raw

log = logging.getLogger(__name__)
GAMMA = "https://gamma-api.polymarket.com/events"
CLOB_HISTORY = "https://clob.polymarket.com/prices-history"
CACHE_DIR = DATA_DIR / ".cache" / "polymarket"
CACHE_TTL = 120
_mem: dict[str, tuple[float, dict]] = {}


def _ts(s: str | None) -> int | None:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()) if s else None


def _event(slug: str) -> dict | None:
    r = requests.get(GAMMA, params={"slug": slug}, timeout=20)
    r.raise_for_status()
    d = r.json()
    if not d:
        return None
    e = d[0]
    markets = []
    for m in e.get("markets", []):
        outcomes = json.loads(m.get("outcomes") or "[]")
        prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
        markets.append({
            "question": m.get("question"), "slug": m.get("slug"), "type": m.get("sportsMarketType"),
            "outcomes": outcomes, "prices": prices, "volume": round(float(m.get("volume") or 0)),
            "closed": bool(m.get("closed")), "line": m.get("line"),
            "tokens": json.loads(m.get("clobTokenIds") or "[]"),
        })
    return {"slug": slug, "title": e.get("title"), "url": f"https://polymarket.com/event/{slug}",
            "volume": round(float(e.get("volume") or 0)), "closed": bool(e.get("closed")),
            "start": e.get("startDate"), "end": e.get("endDate"), "markets": markets}


def _history(token: str, start: int, end: int) -> list[list[float]]:
    r = requests.get(CLOB_HISTORY, params={"market": token, "startTs": start, "endTs": end, "fidelity": 30}, timeout=20)
    r.raise_for_status()
    return [[p["t"], p["p"]] for p in r.json().get("history", [])]


def big_game(year: int, slug: str) -> dict | None:
    cache = CACHE_DIR / f"big_game_{year}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    e = _event(slug)
    if not e:
        return None
    ml = next((m for m in e["markets"] if m["type"] == "moneyline"), None)
    out = {"year": year, "url": e["url"], "title": e["title"], "volume": e["volume"], "closed": e["closed"], "end": e["end"]}
    if ml:
        i = ml["outcomes"].index("Stanford")
        out["stanford_prob"] = ml["prices"][i]
        out["cal_prob"] = ml["prices"][1 - i]
        out["moneyline_volume"] = ml["volume"]
        start, end = _ts(e["start"]), min(_ts(e["end"]) or time.time(), int(time.time()))
        hist = _history(ml["tokens"][i], start, end + 3600) if start and ml["tokens"] else []
        out["history_stanford"] = hist
        kickoff = _ts(e["end"])  # Polymarket's event end = scheduled kickoff for game markets
        pre = [p for t, p in hist if kickoff and t <= kickoff]
        out["pregame_stanford"] = pre[-1] if pre and e["closed"] else None
        out["opening_stanford"] = hist[0][1] if hist else None
    spreads = [m for m in e["markets"] if m["type"] == "spreads" and not m["closed"] and m["volume"] > 0]
    if spreads:  # the most balanced spread is the market's line
        best = min(spreads, key=lambda m: abs(m["prices"][0] - 0.5))
        out["spread"] = best["question"]
    if e["closed"]:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out))
    return out


def win_total(team: str, slug: str) -> dict | None:
    e = _event(slug)
    if not e:
        return None
    ladder = []
    for m in e["markets"]:
        q = m["question"] or ""
        try:
            line = float(q.split("more than ")[1].split(" wins")[0])
        except (IndexError, ValueError):
            continue
        yes = m["prices"][m["outcomes"].index("Yes")] if "Yes" in m["outcomes"] else None
        ladder.append({"line": line, "yes": yes, "closed": m["closed"], "volume": m["volume"], "question": q})
    return {"team": team, "url": e["url"], "title": e["title"], "volume": e["volume"],
            "ladder": sorted(ladder, key=lambda x: x["line"])}


def markets() -> dict:
    hit = _mem.get("all")
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    cfg = raw().get("polymarket", {})
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(), "big_game": {}, "win_totals": {},
           "next_game": cfg.get("next_game"), "errors": []}
    for year, slug in (cfg.get("big_game") or {}).items():
        try:
            out["big_game"][str(year)] = big_game(int(year), slug)
        except requests.RequestException as exc:
            out["errors"].append(f"{slug}: {exc}")
    for team, slug in (cfg.get("win_totals") or {}).items():
        try:
            out["win_totals"][team] = win_total(team, slug)
        except requests.RequestException as exc:
            out["errors"].append(f"{slug}: {exc}")
    if out["next_game"] and out["next_game"].get("date"):
        out["next_game"]["date"] = str(out["next_game"]["date"])
    _mem["all"] = (time.time(), out)
    return out
