"""Collect videos and comments for every season, inside the shared daily quota.

Order: videos for all seasons first (cheap, ~1 request per 30-100 videos), then comments on
on-topic videos across all seasons, most-commented first. Everything resumes after the 00:00 UTC reset.
"""

from __future__ import annotations

import logging

import pandas as pd

from . import env  # noqa: F401  (must load .env before ttresearch)
from ttresearch import Query, QuotaExceeded, Research, cond
from ttresearch import analysis
from ttresearch.storage import iter_jsonl
from ttresearch.study import Study

from .config import raw, seasons
from .relevance import classify, rivalry_pattern

log = logging.getLogger(__name__)
RESERVE = 25            # leave a few requests for colleagues / ad-hoc checks
COMMENTS_PER_VIDEO = 1000
CHUNK = 10              # re-check the quota ledger every N videos


_research: Research | None = None


def study(year: int) -> Study:
    """Study for a season, all sharing one client so the quota ledger stays consistent."""
    global _research
    _research = _research or Research()
    return Study(seasons()[year].study, research=_research)


def queries(year: int) -> dict[str, Query]:
    cfg = raw()
    tags = list(dict.fromkeys([*cfg["hashtags"], f"biggame{year}"]))
    q = {"hashtags": Query(or_=[cond("hashtag_name", "IN", tags)])}
    for label, (a, b) in cfg["keyword_pairs"].items():
        q[label] = Query(and_=[cond("keyword", "EQ", a), cond("keyword", "EQ", b)])
    return q


def remaining(study: Study) -> int:
    return study.research.client.ledger.remaining("default") - RESERVE


def load_videos(year: int, st: Study | None = None) -> pd.DataFrame:
    """Deduplicated videos for a season, with `found_by` and `relevance` columns."""
    from .espn import load_game

    s = seasons()[year]
    st = st or study(year)
    if not st.path("videos").exists():
        return pd.DataFrame()
    raw_rows = pd.DataFrame(list(iter_jsonl(st.path("videos"))))
    found_by = raw_rows.groupby("id")["_query"].agg(lambda x: ",".join(sorted(set(x))))
    df = st.load("videos").drop(columns="_query").merge(found_by.rename("found_by"), left_on="id", right_index=True)
    df = analysis.prepare(df)
    try:
        g = load_game(year)
        # The final score is a rivalry marker only once the game is over (a 0-0 placeholder would match noise).
        score = (g["teams"]["stanford"]["score"], g["teams"]["cal"]["score"]) if g.get("winner") else None
    except FileNotFoundError:
        score = None
    pat = rivalry_pattern(score)
    df["relevance"] = df.apply(lambda r: classify(r, pat), axis=1)
    df["season"] = year
    return df.sort_values("view_count", ascending=False).reset_index(drop=True)


def collect_videos_all() -> None:
    for year, s in seasons().items():
        st = study(year)
        for label, q in queries(year).items():
            if remaining(st) <= 5:
                raise QuotaExceeded(429, "local_budget", "local ledger budget reached")
            st.collect_videos(q, s.start, s.end, window_days=7, label=label)
        log.info("%d: videos done", year)


def comment_queue() -> list[tuple[int, str, int]]:
    """(year, video_id, comment_count) for on-topic videos still lacking comments, biggest first."""
    queue = []
    for year, s in seasons().items():
        st = study(year)
        v = load_videos(year, st)
        if v.empty:
            continue
        done = st.state.done("comment_videos")
        rel = v[(v.relevance == "big_game") & (v.comment_count > 0)]
        queue += [(year, str(i), int(c)) for i, c in zip(rel.id, rel.comment_count) if str(i) not in done]
    return sorted(queue, key=lambda t: -t[2])


def collect_comments_all() -> None:
    queue = comment_queue()
    log.info("Comment queue: %d videos, %d comments counted", len(queue), sum(c for *_, c in queue))
    studies = {y: study(y) for y in seasons()}
    for i in range(0, len(queue), CHUNK):
        chunk = queue[i:i + CHUNK]
        any_study = studies[chunk[0][0]]
        # Each video costs >= ceil(comments/100) requests.
        need = sum(max(1, -(-min(c, COMMENTS_PER_VIDEO) // 100)) for *_, c in chunk)
        if remaining(any_study) < need:
            raise QuotaExceeded(429, "local_budget", f"need ~{need}, ledger has {remaining(any_study)}")
        for year in sorted({y for y, *_ in chunk}):
            ids = [vid for y, vid, _ in chunk if y == year]
            studies[year].collect_comments(ids, per_video_limit=COMMENTS_PER_VIDEO)
        log.info("Comments: %d/%d videos, ledger remaining %d", min(i + CHUNK, len(queue)), len(queue),
                 remaining(any_study) + RESERVE)


def collect_all() -> int:
    """Returns 0 when finished, 2 when the daily quota stopped it (re-run after 00:00 UTC)."""
    try:
        collect_videos_all()
        collect_comments_all()
    except QuotaExceeded as exc:
        log.warning("Stopped for today's quota (%s). Progress saved; re-run after 00:00 UTC (4 pm PT).", exc)
        return 2
    log.info("Collection complete for all seasons.")
    return 0
