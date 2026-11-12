"""Coaches, rosters and in-game player performance for each Big Game.

Sources: ESPN's public JSON APIs (box score from the game summary, season rosters from the core
API) plus the head coaches curated in seasons.yaml (ESPN's historical coach records are wrong).
Writes data/<year>_biggame/football.json. Athlete records are cached in data/.cache/espn/.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from .config import DATA_DIR, raw, seasons

log = logging.getLogger(__name__)
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
CACHE = DATA_DIR / ".cache" / "espn"
TEAM_IDS = {"stanford": "24", "cal": "25"}

# Fantasy-style impact score, for ranking performances within a game (documented in the dashboard).
IMPACT = {
    ("passing", "YDS"): 1 / 25, ("passing", "TD"): 4, ("passing", "INT"): -2,
    ("rushing", "YDS"): 1 / 10, ("rushing", "TD"): 6,
    ("receiving", "YDS"): 1 / 10, ("receiving", "TD"): 6, ("receiving", "REC"): 0.5,
    ("defensive", "TOT"): 1, ("defensive", "SACKS"): 3, ("defensive", "TFL"): 1, ("defensive", "PD"): 1,
    ("defensive", "TD"): 6, ("interceptions", "INT"): 5, ("interceptions", "TD"): 6,
    ("fumbles", "LOST"): -2, ("kickReturns", "TD"): 6, ("puntReturns", "TD"): 6,
    ("kicking", "PTS"): 1,
}


def _get(url: str, **params) -> dict:
    r = requests.get(url.replace("http://", "https://"), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _num(v: str):
    try:
        return float(v) if "." in v else int(v)
    except (TypeError, ValueError):
        return v


def athlete(year: int, ref: str) -> dict:
    aid = ref.split("/athletes/")[1].split("?")[0]
    p = CACHE / f"athlete_{year}_{aid}.json"
    if p.exists():
        return json.loads(p.read_text())
    a = _get(ref)
    out = {
        "id": aid, "name": a.get("displayName"), "first": a.get("firstName"), "last": a.get("lastName"),
        "jersey": a.get("jersey"),
        "position": (a.get("position") or {}).get("abbreviation"),
        "position_name": (a.get("position") or {}).get("displayName"),
        "class": (a.get("experience") or {}).get("displayValue"),
        "height": a.get("displayHeight"), "weight": a.get("displayWeight"),
        "hometown": ", ".join(x for x in [(a.get("birthPlace") or {}).get("city"), (a.get("birthPlace") or {}).get("state")] if x),
        "headshot": (a.get("headshot") or {}).get("href"),
    }
    p.write_text(json.dumps(out))
    return out


def roster(year: int, team: str) -> list[dict]:
    d = _get(f"{CORE}/seasons/{year}/teams/{TEAM_IDS[team]}/athletes", limit=500)
    refs = [i["$ref"] for i in d.get("items", [])]
    with ThreadPoolExecutor(max_workers=6) as ex:
        players = list(ex.map(lambda r: athlete(year, r), refs))
    return sorted(players, key=lambda x: (x["position"] or "ZZ", x["last"] or ""))


def box_score(espn_id: int) -> tuple[dict, dict, dict]:
    """(player stats by team, team stats by team, team records) from the game summary."""
    d = _get(SUMMARY, event=espn_id)
    abbr = lambda t: "stanford" if t["abbreviation"] == "STAN" else "cal"  # noqa: E731
    players: dict[str, dict] = {"stanford": {}, "cal": {}}
    for t in d["boxscore"]["players"]:
        side = abbr(t["team"])
        for cat in t["statistics"]:
            for a in cat["athletes"]:
                ath = a["athlete"]
                p = players[side].setdefault(ath["id"], {"id": ath["id"], "name": ath["displayName"],
                                                         "jersey": ath.get("jersey"), "stats": {}})
                p["stats"][cat["name"]] = {lab: _num(v) for lab, v in zip(cat["labels"], a["stats"])}
    team_stats = {abbr(t["team"]): {s["label"]: s["displayValue"] for s in t["statistics"]} for t in d["boxscore"]["teams"]}
    records = {}
    for c in d["header"]["competitions"][0]["competitors"]:
        recs = {r.get("type"): r.get("summary") for r in c.get("record", [])}
        records[abbr(c["team"])] = recs.get("total") or next(iter(recs.values()), None)
    return players, team_stats, records


def impact(stats: dict) -> float:
    score = 0.0
    for (cat, lab), w in IMPACT.items():
        v = stats.get(cat, {}).get(lab)
        if isinstance(v, (int, float)):
            score += v * w
    return round(score, 1)


def stat_line(stats: dict) -> str:
    parts = []
    if (p := stats.get("passing")):
        parts.append(f"{p.get('C/ATT')} {p.get('YDS')} yds pass, {p.get('TD')} TD, {p.get('INT')} INT")
    if (r := stats.get("rushing")) and r.get("CAR"):
        parts.append(f"{r.get('CAR')} car {r.get('YDS')} yds" + (f", {r['TD']} TD" if r.get("TD") else ""))
    if (r := stats.get("receiving")) and r.get("REC"):
        parts.append(f"{r.get('REC')} rec {r.get('YDS')} yds" + (f", {r['TD']} TD" if r.get("TD") else ""))
    if (d := stats.get("defensive")) and d.get("TOT"):
        bits = [f"{d['TOT']} tkl"] + ([f"{d['SACKS']} sk"] if d.get("SACKS") else []) + ([f"{d['TFL']} TFL"] if d.get("TFL") else [])
        parts.append(" ".join(bits))
    if (i := stats.get("interceptions")) and i.get("INT"):
        parts.append(f"{i['INT']} INT")
    if (k := stats.get("kicking")) and k.get("FG"):
        parts.append(f"FG {k['FG']}, XP {k.get('XP')}")
    if (pu := stats.get("punting")) and pu.get("NO"):
        parts.append(f"{pu['NO']} punts, {pu.get('AVG')} avg")
    return " · ".join(parts)


def build_football(year: int) -> dict:
    s = seasons()[year]
    cfg = raw()
    played, team_stats, records = box_score(s.espn_id)
    out = {"year": year, "coaches": {}, "teams": {}}
    for team in ("stanford", "cal"):
        ckey = cfg["seasons"][year].get("coaches", {}).get(team)
        out["coaches"][team] = {"key": ckey, **cfg["coaches"].get(ckey, {})} if ckey else None
        ros = roster(year, team)
        by_id = {p["id"]: p for p in ros}
        performers = []
        for pid, p in played[team].items():
            info = by_id.get(pid, {})
            performers.append({**info, "id": pid, "name": p["name"], "jersey": p.get("jersey") or info.get("jersey"),
                               "stats": p["stats"], "line": stat_line(p["stats"]), "impact": impact(p["stats"])})
        performers.sort(key=lambda x: -x["impact"])
        for p in ros:
            p["played"] = p["id"] in played[team]
        out["teams"][team] = {"record_after_game": records.get(team), "team_stats": team_stats.get(team, {}),
                              "performers": performers, "roster": ros}
        log.info("%d %s: coach %s, roster %d, %d players with stats (top: %s %.1f)", year, team,
                 (out["coaches"][team] or {}).get("name"), len(ros), len(performers),
                 performers[0]["name"] if performers else "-", performers[0]["impact"] if performers else 0)
    return out


def refresh_football() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for year, s in seasons().items():
        (s.dir / "football.json").write_text(json.dumps(build_football(year), ensure_ascii=False, indent=1))
