"""Combine raw data + multi-model labels into the dashboard dataset (data/dashboard/*.json).

Ensemble rules per item (comment or video):
- categorical fields (stance, target, emotion, relevant, sarcasm): majority vote; ties go to the
  strongest model present (opus > sonnet > haiku)
- sentiment: mean of the models' scores (-2..+2)
- topics: topics named by at least half of the models

Game-day momentum uses a trailing 60-minute window stepped every 15 minutes; the season headline
is the game window (kickoff to +48h), since most TikTok reaction comes after the final whistle.
Momentum (per time bin) = mean sentiment of Stanford-leaning items minus mean sentiment of
Cal-leaning items. Positive = Stanford fans feel better than Cal fans right now.
Commenter names are never written to the dashboard dataset.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
from collections import Counter

import numpy as np
import pandas as pd

from . import env  # noqa: F401
from ttresearch import analysis

from .collect import load_videos, study
from .config import DATA_DIR, PT, seasons
from .espn import load_game
from .label import EMOTIONS, MODELS, TOPICS, label_path

log = logging.getLogger(__name__)
OUT = DATA_DIR / "dashboard"
MODEL_ORDER = ["opus", "sonnet", "haiku"]  # tie-break priority
GAME_BIN_MIN = 15
GAME_WINDOW = (-180, 420)  # minutes around kickoff for the game-day view
MIN_N = 3                  # minimum items per side to show a momentum value
ROLL_MIN = 60              # game-day momentum uses a trailing 60-minute window, stepped every 15 min


def load_labels(year: int) -> dict[str, pd.DataFrame]:
    out = {}
    for mk in MODELS:
        p = label_path(year, mk)
        if p.exists() and p.stat().st_size:
            df = pd.read_json(p, lines=True).drop_duplicates("key", keep="last").set_index("key")
            out[mk] = df
    return out


def _vote(values: list, order: list[str]):
    vals = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if not vals:
        return None
    c = Counter(vals).most_common()
    top = [v for v, n in c if n == c[0][1]]
    if len(top) == 1:
        return top[0]
    for v in values:  # values are in MODEL_ORDER, so the first tie member wins
        if v in top:
            return v
    return top[0]


def ensemble(labels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if not labels:
        return pd.DataFrame()
    present = [m for m in MODEL_ORDER if m in labels]
    keys = sorted(set().union(*[set(df.index) for df in labels.values()]))
    rows = []
    for k in keys:
        per = {m: labels[m].loc[k] if k in labels[m].index else None for m in present}
        got = [m for m in present if per[m] is not None]
        r = {"key": k, "n_models": len(got)}
        for f in ["stance", "target", "emotion", "relevant", "sarcasm"]:
            r[f] = _vote([per[m][f] for m in got], got)
        sents = [float(per[m]["sentiment"]) for m in got]
        r["sentiment"] = float(np.mean(sents))
        r["sentiment_spread"] = float(np.ptp(sents)) if len(sents) > 1 else 0.0
        tc = Counter(t for m in got for t in (per[m]["topics"] or []))
        r["topics"] = [t for t, n in tc.items() if n >= max(1, len(got) / 2)]
        for m in got:
            r[f"stance_{m}"] = per[m]["stance"]
            r[f"sentiment_{m}"] = int(per[m]["sentiment"])
        rows.append(r)
    return pd.DataFrame(rows).set_index("key")


def agreement(labels: dict[str, pd.DataFrame]) -> dict:
    """Pairwise agreement between models on stance (exact) and sentiment (sign and |diff|<=1)."""
    pairs = []
    for a, b in itertools.combinations([m for m in MODEL_ORDER if m in labels], 2):
        j = labels[a][["stance", "sentiment"]].join(labels[b][["stance", "sentiment"]], lsuffix="_a", rsuffix="_b",
                                                    how="inner")
        if j.empty:
            continue
        po = float((j.stance_a == j.stance_b).mean())
        pa = j.stance_a.value_counts(normalize=True)
        pb = j.stance_b.value_counts(normalize=True)
        pe = float(sum(pa.get(c, 0) * pb.get(c, 0) for c in set(pa.index) | set(pb.index)))
        pairs.append({
            "a": a, "b": b, "n": len(j),
            "stance_agree": round(po, 3),
            # Side = stanford / cal / none (neutral and unclear both mean "no side"); what momentum uses.
            "side_agree": round(float((j.stance_a.replace("unclear", "neutral") == j.stance_b.replace("unclear", "neutral")).mean()), 3),
            "stance_kappa": round((po - pe) / (1 - pe), 3) if pe < 1 else None,
            "sentiment_sign_agree": round(float((np.sign(j.sentiment_a) == np.sign(j.sentiment_b)).mean()), 3),
            "sentiment_within1": round(float(((j.sentiment_a - j.sentiment_b).abs() <= 1).mean()), 3),
            "sentiment_corr": round(float(j.sentiment_a.corr(j.sentiment_b)), 3) if len(j) > 2 else None,
        })
    dist = {m: df["stance"].value_counts(normalize=True).round(3).to_dict() for m, df in labels.items()}
    mean_sent = {m: round(float(df["sentiment"].mean()), 3) for m, df in labels.items()}
    return {"pairs": pairs, "stance_distribution": dist, "mean_sentiment": mean_sent,
            "items": {m: len(df) for m, df in labels.items()}}


def _side_stats(g: pd.DataFrame) -> dict:
    st, ca = g[g.stance == "stanford"], g[g.stance == "cal"]
    out = {"n": int(len(g)), "n_stanford": int(len(st)), "n_cal": int(len(ca)),
           "n_neutral": int((g.stance == "neutral").sum()) if "stance" in g else 0}
    if "sentiment" in g and g["sentiment"].notna().any():
        out["sentiment"] = round(float(g.sentiment.mean()), 3)
        out["mood_stanford"] = round(float(st.sentiment.mean()), 3) if len(st) >= MIN_N else None
        out["mood_cal"] = round(float(ca.sentiment.mean()), 3) if len(ca) >= MIN_N else None
        out["momentum"] = (round(out["mood_stanford"] - out["mood_cal"], 3)
                           if out["mood_stanford"] is not None and out["mood_cal"] is not None else None)
    return out


def _rolling(items: pd.DataFrame, step: int, width: int, lo: int, hi: int) -> list[dict]:
    """Stats every `step` minutes over the trailing `width` minutes (smooths sparse in-game comments)."""
    rows = []
    for t in range(lo, hi, step):
        g = items[(items.t_min >= t - width + step) & (items.t_min < t + step)]
        rows.append({"t": t, **_side_stats(g)})
    return rows


def _timeline(items: pd.DataFrame, bin_min: int, lo: int, hi: int) -> list[dict]:
    d = items[(items.t_min >= lo) & (items.t_min < hi)].copy()
    d["bin"] = (d.t_min // bin_min * bin_min).astype(int)
    rows = []
    for b in range(lo // bin_min * bin_min, hi, bin_min):
        g = d[d.bin == b]
        rows.append({"t": b, **_side_stats(g)})
    return rows


# Last names that are ordinary words or very common names: match only the full name.
AMBIGUOUS = {"green", "ford", "brown", "young", "white", "black", "long", "king", "price", "rich", "may", "hill",
             "wood", "love", "bell", "rose", "hope", "day", "house", "west", "banks", "stone", "grant", "cash",
             "hunt", "bush", "case", "lane", "noble", "power", "sharp", "small", "strong", "wise", "rivers",
             "brooks", "fields", "woods", "reed", "rice", "star", "taylor", "jones", "smith", "johnson", "williams",
             "davis", "miller", "wilson", "moore", "jackson", "martin", "lee", "thomas", "harris", "clark", "lewis",
             "allen", "scott", "adams", "baker", "nelson", "hall", "turner", "parker", "collins", "edwards",
             "stewart", "morris", "murphy", "cook", "rogers", "bailey", "cooper", "ward", "gray", "james", "bryant",
             "russell", "hayes", "myers", "ross", "foster", "graham", "wallace", "cole", "west", "jordan", "reynolds",
             "fisher", "ellis", "daniels", "mason", "kelly", "washington", "dancy", "ott"}


def _dictionary() -> set[str]:
    """Lower-case English words (macOS/Linux word list); names that are words need the full name."""
    from pathlib import Path
    p = Path("/usr/share/dict/words")
    return {w.strip() for w in p.read_text().splitlines() if w.strip().islower()} if p.exists() else set()


_WORDS = _dictionary()


NICKNAMES = {"jaron-keawe sagapolutele": ["jks"], "fernando mendoza": ["nando"]}


def _aliases(person: dict) -> list[str]:
    name = (person.get("name") or "").lower().strip()
    last = (person.get("last") or name.split(" ")[-1]).lower().strip()
    out = ([name] if name else []) + NICKNAMES.get(name, [])
    if last and len(last) >= 4 and last not in AMBIGUOUS and last not in _WORDS and " " not in last:
        out.append(last)
    return out


def fan_buzz(items: pd.DataFrame, people: list[dict]) -> list[dict]:
    """How often each coach/player is named in the season's comments and video captions, and how it felt."""
    if items.empty:
        return []
    low = items.text.fillna("").str.lower()
    out = []
    for p in people:
        al = _aliases(p)
        if not al:
            continue
        pat = r"\b(?:" + "|".join(re.escape(a) for a in al) + r")\b"
        hit = items[low.str.contains(pat, regex=True)]
        if hit.empty:
            continue
        lab = hit[hit.sentiment.notna()] if "sentiment" in hit else hit.iloc[0:0]
        best = hit.nlargest(1, "likes").iloc[0]
        out.append({"name": p["name"], "team": p["team"], "role": p["role"], "position": p.get("position"),
                    "played": bool(p.get("played", p["role"] == "Head coach")),
                    "mentions": int(len(hit)), "likes": int(hit.likes.sum()),
                    "sentiment": round(float(lab.sentiment.mean()), 2) if len(lab) else None,
                    "from_stanford": int((lab.stance == "stanford").sum()) if len(lab) else 0,
                    "from_cal": int((lab.stance == "cal").sum()) if len(lab) else 0,
                    "top_text": str(best.text)[:240], "top_likes": int(best.likes)})
    return sorted(out, key=lambda x: (-x["mentions"], -x["likes"]))


def football_section(year: int, items: pd.DataFrame) -> dict | None:
    p = seasons()[year].dir / "football.json"
    if not p.exists():
        return None
    f = json.loads(p.read_text())
    people = []
    teams = {}
    for team, t in f["teams"].items():
        coach = f["coaches"].get(team)
        if coach:
            people.append({**coach, "team": team, "role": "Head coach", "position": "HC"})
        people += [{**pl, "team": team, "role": "Player"} for pl in t["roster"]]
        keep = ["id", "name", "jersey", "position", "position_name", "class", "height", "weight", "hometown", "headshot"]
        teams[team] = {
            "record_after_game": t["record_after_game"], "team_stats": t["team_stats"],
            "performers": [{**{k: pl.get(k) for k in keep}, "line": pl["line"], "impact": pl["impact"], "stats": pl["stats"]}
                           for pl in t["performers"]],
            "roster": [{**{k: pl.get(k) for k in keep if k != "headshot"}, "played": pl["played"]} for pl in t["roster"]],
        }
    return {"coaches": f["coaches"], "teams": teams, "buzz": fan_buzz(items, people)[:30]}


def build_season(year: int) -> dict:
    s = seasons()[year]
    st = study(year)
    game = load_game(year)
    kickoff = pd.Timestamp(game["kickoff_utc"])
    videos = load_videos(year, st)
    if videos.empty:
        return {"year": year, "game": game, "empty": True}
    rel = videos[videos.relevance == "big_game"].copy()
    comments = st.load("comments") if st.path("comments").exists() else pd.DataFrame()
    if not comments.empty:
        comments = comments[comments.video_id.astype(str).isin(rel.id.astype(str))].copy()

    labels = load_labels(year)
    ens = ensemble(labels)

    # One table of everything that can carry sentiment: comments + the videos themselves.
    items = []
    for _, c in comments.iterrows():
        items.append({"key": f"comment:{c['id']}", "kind": "comment", "video_id": str(c["video_id"]),
                      "ts": int(c["create_time"]), "likes": int(c.get("like_count") or 0), "text": c.get("text")})
    for _, v in rel.iterrows():
        items.append({"key": f"video:{v['id']}", "kind": "video", "video_id": str(v["id"]),
                      "ts": int(v["create_time"]), "likes": int(v["like_count"]), "text": v.get("video_description")})
    items = pd.DataFrame(items)
    items["t_min"] = (items.ts - kickoff.timestamp()) / 60
    if not ens.empty:
        items = items.join(ens, on="key")
        labeled = items[items.n_models.notna()]
        labeled = labeled[labeled.relevant.fillna(True).astype(bool)]
    else:
        for col in ["n_models", "stance", "target", "emotion", "relevant", "sarcasm", "sentiment", "sentiment_spread", "topics"]:
            items[col] = None
        items["sentiment"] = np.nan
        labeled = items.iloc[0:0]

    vol = items.assign(stance=items.get("stance"))
    game_tl = _rolling(labeled, GAME_BIN_MIN, ROLL_MIN, *GAME_WINDOW)
    vol_game = _timeline(vol.assign(sentiment=np.nan), GAME_BIN_MIN, *GAME_WINDOW)
    for row, v in zip(game_tl, vol_game):
        row["volume"] = v["n"]
    days_lo, days_hi = -(kickoff - pd.Timestamp(s.start, tz=PT)).days * 1440, 16 * 1440
    daily = _timeline(labeled, 1440, days_lo, days_hi)
    vol_daily = _timeline(vol.assign(sentiment=np.nan), 1440, days_lo, days_hi)
    for row, v in zip(daily, vol_daily):
        row["volume"] = v["n"]

    for p in game["scoring_plays"]:
        p["t_min"] = round((pd.Timestamp(p["wallclock"]) - kickoff).total_seconds() / 60, 1) if p["wallclock"] else None

    def counts(col_vals, universe):
        c = Counter(col_vals)
        return [{"name": k, "n": c.get(k, 0)} for k in universe]

    emo_by_side = {side: counts(labeled[labeled.stance == side].emotion, EMOTIONS) for side in ["stanford", "cal"]}
    topic_counts = counts([t for ts in labeled.get("topics", []) if isinstance(ts, list) for t in ts], TOPICS)

    top_cols = ["key", "kind", "text", "likes", "t_min", "stance", "sentiment", "emotion", "sarcasm", "sentiment_spread"]
    top = labeled[labeled.kind == "comment"].nlargest(60, "likes")[top_cols] if len(labeled) else pd.DataFrame()
    disagreements = (labeled[(labeled.n_models > 1) & (labeled.sentiment_spread >= 2)].nlargest(30, "likes")[top_cols]
                     if len(labeled) else pd.DataFrame())

    # Replay feed: labeled comments during the game window, most-liked first (no commenter names).
    gw = labeled[(labeled.kind == "comment") & (labeled.t_min >= GAME_WINDOW[0]) & (labeled.t_min < GAME_WINDOW[1])]
    feed = gw.nlargest(500, "likes")[top_cols] if len(gw) else pd.DataFrame()

    o = analysis.overview(rel)
    vids = rel.nlargest(25, "view_count")
    video_rows = [{"id": str(v.id), "url": v.url, "username": v.username, "created_pt": v.created.tz_convert(PT).strftime("%b %d %H:%M"),
                   "t_min": round((v.created - kickoff).total_seconds() / 60), "views": int(v.view_count),
                   "likes": int(v.like_count), "comments": int(v.comment_count), "shares": int(v.share_count),
                   "caption": str(v.video_description or "")[:220],
                   **({k: ens.loc[f"video:{v.id}", k] for k in ["stance", "sentiment", "emotion"]}
                      if not ens.empty and f"video:{v.id}" in ens.index else {})}
                  for v in vids.itertuples()]

    return {
        "year": year,
        "game": game,
        "summary": {
            "videos_matched": len(videos), "videos_on_topic": int(len(rel)), "creators": int(o["creators"]),
            "views": int(o["total_view_count"]), "likes": int(o["total_like_count"]),
            "shares": int(o["total_share_count"]), "comments_counted": int(o["total_comment_count"]),
            "comments_collected": int(len(comments)), "items_labeled": int(len(labeled)),
            "relevance_tiers": videos.relevance.value_counts().to_dict(),
            **{f"overall_{k}": v for k, v in _side_stats(labeled).items()},
            "in_game": _side_stats(labeled[(labeled.t_min >= 0) & (labeled.t_min < 240)]),
            "post_game": _side_stats(labeled[(labeled.t_min >= 240) & (labeled.t_min < 2880)]),
            "game_window": _side_stats(labeled[(labeled.t_min >= 0) & (labeled.t_min < 2880)]),
        },
        "timeline_game": game_tl,
        "timeline_daily": daily,
        "emotions": emo_by_side,
        "topics": topic_counts,
        "feed": json.loads(feed.to_json(orient="records")) if len(feed) else [],
        "top_comments": json.loads(top.to_json(orient="records")) if len(top) else [],
        "disagreements": json.loads(disagreements.to_json(orient="records")) if len(disagreements) else [],
        "top_videos": json.loads(json.dumps(video_rows, default=lambda x: None if pd.isna(x) else x)),
        "hashtags": analysis.top_hashtags(rel, 20).to_dict(orient="records"),
        "models": agreement(labels),
        "football": football_section(year, items),
    }


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for year in seasons():
        d = build_season(year)
        (OUT / f"{year}.json").write_text(json.dumps(d, ensure_ascii=False, default=str))
        g = d["game"]
        index.append({"year": year, "winner": g["winner"], "stanford": g["teams"]["stanford"]["score"],
                      "cal": g["teams"]["cal"]["score"], "venue": g["venue"], "kickoff_utc": g["kickoff_utc"],
                      "note": g.get("note", ""),
                      "momentum_48h": (d.get("summary", {}).get("game_window") or {}).get("momentum"),
                      **({k: d["summary"][k] for k in d.get("summary", {})
                                                     if not isinstance(d["summary"][k], dict)})})
        log.info("%d: %s", year, {k: index[-1].get(k) for k in ["videos_on_topic", "comments_collected", "items_labeled"]})
    (OUT / "index.json").write_text(json.dumps({"seasons": index, "models": MODELS,
                                                "built_at": pd.Timestamp.now(tz="UTC").isoformat()}, default=str))
    log.info("Wrote %s", OUT)
