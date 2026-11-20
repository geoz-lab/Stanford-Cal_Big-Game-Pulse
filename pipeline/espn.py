"""Game facts from ESPN's public JSON API: kickoff time, final score, scoring plays.

This is public sports data (not TikTok data), used to overlay the score on sentiment timelines.
"""

from __future__ import annotations

import json
import logging

import requests

from .config import seasons

log = logging.getLogger(__name__)
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"


def fetch_game(year: int) -> dict:
    s = seasons()[year]
    d = requests.get(SUMMARY, params={"event": s.espn_id}, timeout=30).json()
    comp = d["header"]["competitions"][0]
    teams = {}
    for t in comp["competitors"]:
        key = "stanford" if t["team"]["abbreviation"] == "STAN" else "cal"
        teams[key] = {"id": t["team"]["id"], "name": t["team"]["displayName"], "score": int(t.get("score") or 0),
                      "winner": bool(t.get("winner")), "side": t["homeAway"]}
    id_to_team = {v["id"]: k for k, v in teams.items()}
    plays = []
    for p in d.get("scoringPlays", []):
        plays.append({
            "period": p["period"]["number"],
            "clock": p["clock"]["displayValue"],
            "team": id_to_team.get(p["team"]["id"]),
            "type": p.get("type", {}).get("text"),
            "text": p.get("text"),
            "stanford": p.get(f"{teams['stanford']['side']}Score"),
            "cal": p.get(f"{teams['cal']['side']}Score"),
            "wallclock": p.get("wallclock"),
        })
    # Play-by-play wallclock gives real UTC times when ESPN has them; fall back to scoring-play order.
    wall = {}
    for drive in (d.get("drives") or {}).get("previous", []):
        for play in drive.get("plays", []):
            if play.get("scoringPlay") and play.get("wallclock"):
                wall[(play["period"]["number"], play["clock"]["displayValue"])] = play["wallclock"]
    for p in plays:
        p["wallclock"] = p["wallclock"] or wall.get((p["period"], p["clock"]))
    status = comp.get("status", {}).get("type", {})
    final = bool(status.get("completed"))
    winner = ("stanford" if teams["stanford"]["winner"] else "cal") if final else None
    return {"year": year, "espn_id": s.espn_id, "kickoff_utc": comp["date"], "venue": s.venue, "home": s.home,
            "note": s.note, "teams": teams, "winner": winner, "final": final,
            "status": status.get("description") or status.get("name"), "scoring_plays": plays}


def refresh_games() -> None:
    for year, s in seasons().items():
        g = fetch_game(year)
        s.dir.mkdir(parents=True, exist_ok=True)
        (s.dir / "game.json").write_text(json.dumps(g, indent=2))
        n_wall = sum(1 for p in g["scoring_plays"] if p["wallclock"])
        log.info("%d: %s %d-%d, kickoff %s, %d scoring plays (%d timed)", year, g["winner"],
                 g["teams"]["stanford"]["score"], g["teams"]["cal"]["score"], g["kickoff_utc"],
                 len(g["scoring_plays"]), n_wall)


def load_game(year: int) -> dict:
    return json.loads((seasons()[year].dir / "game.json").read_text())
