"""Multi-model LLM labeling of Big Game comments and video text.

Each request carries one video's context (caption, on-screen text, transcript, season result)
plus up to BATCH_ITEMS of its comments, and asks for one label object per item. Three Claude
models label everything independently; `build` later combines them (majority vote / mean) and
reports their agreement.

Runs through the Message Batches API by default (50% cheaper, usually done within an hour).
Resumable: labels go to data/<year>_biggame/labels/<model>.jsonl and finished items are skipped.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import anthropic
import pandas as pd
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from . import env  # noqa: F401

from .collect import load_videos, study
from .config import DATA_DIR, PT, seasons


def label_path(year: int, model_key: str) -> Path:
    d = seasons()[year].dir / "labels"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{model_key}.jsonl"
from .espn import load_game
from .relevance import video_text

log = logging.getLogger(__name__)
BATCH_DIR = DATA_DIR / ".label_batches"  # in-flight batch ids, for resuming
BATCH_ITEMS = 40
PROMPT_VERSION = "v1"

MODELS = {
    "haiku": "claude-haiku-5-5",
    "sonnet": "claude-sonnet-5-5",
    "opus": "claude-opus-5-5",
}

STANCES = ["stanford", "cal", "neutral", "unclear"]
TARGETS = ["stanford", "cal", "both", "game", "other", "none"]
EMOTIONS = ["joy", "pride", "banter", "mockery", "anger", "frustration", "sadness", "surprise",
            "nostalgia", "support", "neutral"]
TOPICS = ["score_result", "specific_play", "players", "coach", "axe", "band", "fans_tailgate", "stadium_atmosphere",
          "campus_school", "academics_rivalry", "nil_transfer_conference", "media_creator", "other"]

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "relevant": {"type": "boolean"},
        "stance": {"type": "string", "enum": STANCES},
        "sentiment": {"type": "integer", "enum": [-2, -1, 0, 1, 2]},
        "target": {"type": "string", "enum": TARGETS},
        "emotion": {"type": "string", "enum": EMOTIONS},
        "topics": {"type": "array", "items": {"type": "string", "enum": TOPICS}},
        "sarcasm": {"type": "boolean"},
        "confidence": {"type": "integer", "enum": [1, 2, 3]},
    },
    "required": ["id", "relevant", "stance", "sentiment", "target", "emotion", "topics", "sarcasm", "confidence"],
    "additionalProperties": False,
}
OUTPUT_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}},
        "required": ["items"],
        "additionalProperties": False,
    },
}

SYSTEM = """You annotate TikTok content about the Big Game, the annual college football rivalry between \
Stanford (the Cardinal; mascot the Stanford Tree; band LSJUMB) and Cal / UC Berkeley (the Golden Bears; \
Oski; Cal Band). The winner takes home the Stanford Axe. Fans trade banter about the game, the schools, \
academics, the Axe, the bands and "The Play" (1982).

For every item (the video itself, id "v", and each comment, ids "c1", "c2", ...) return one label:

- relevant: is it about the game, the rivalry, the teams, fans, bands or the schools in this context? \
Spam, unrelated chatter and generic replies like "first" are not relevant.
- stance: which side the author is on: "stanford", "cal", "neutral" (a non-fan, media or balanced voice) or \
"unclear". Infer from wording, "we/us/our", mockery of one side, emojis and the video's context. A comment \
mocking Cal is usually a Stanford fan, and vice versa.
- sentiment: the author's own emotional valence, -2 (very negative) to +2 (very positive). Gloating, joy and \
playful trash talk are positive for the author; despair, anger and complaints are negative.
- target: who the sentiment is aimed at: "stanford", "cal", "both", "game" (the game/event in general), \
"other" or "none".
- emotion: the single dominant emotion.
- topics: zero or more topics the item touches.
- sarcasm: true if the literal words mean the opposite of what's meant.
- confidence: 1 (guess) to 3 (clear).

Read emojis as signals: 🌲 Stanford Tree, ❤️🤍 Stanford red/white, 🐻 💙💛 Cal, 🪓 the Axe, 😭💀 usually \
laughter (not sadness), 🤡 🗑️ 🥱 mockery, 🔥 hype, 🙏 support. Typos, slang and other languages are normal; \
label them as you would standard English. Return labels for every id given, in order, and nothing else."""


def _fmt_offset(ts: pd.Timestamp, kickoff: pd.Timestamp) -> str:
    mins = int((ts - kickoff).total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"T{sign}{mins // 1440}d{(mins % 1440) // 60:02d}h{mins % 60:02d}m"


def build_tasks(limit: int | None = None) -> list[dict]:
    """One task per (video, comment chunk). Each task lists item keys and the prompt."""
    tasks = []
    for year, s in seasons().items():
        st = study(year)
        videos = load_videos(year, st)
        if videos.empty:
            continue
        rel = videos[videos.relevance == "big_game"]
        comments = st.load("comments") if st.path("comments").exists() else pd.DataFrame()
        g = load_game(year)
        kickoff = pd.Timestamp(g["kickoff_utc"])
        st, ca = g["teams"]["stanford"]["score"], g["teams"]["cal"]["score"]
        result = f"{'Stanford' if g['winner'] == 'stanford' else 'Cal'} won {max(st, ca)}-{min(st, ca)}"
        header = (f"Season {year} Big Game at {s.venue}, kickoff {kickoff.tz_convert(PT):%a %b %d %Y %-I:%M %p} PT. "
                  f"Final: {result} (Stanford {st}, Cal {ca}).")
        by_video = {k: g_ for k, g_ in comments.groupby("video_id")} if not comments.empty else {}
        for _, v in rel.iterrows():
            vid = str(v["id"])
            vtext = video_text(v)[:1500]
            vctx = (f"{header}\nVideo by @{v['username']}, posted {_fmt_offset(v['created'], kickoff)} relative to "
                    f"kickoff, {int(v['view_count']):,} views.\nVideo text (caption, hashtags, transcript, "
                    f"on-screen text): {vtext}")
            cs = by_video.get(int(vid), by_video.get(vid, pd.DataFrame()))
            if not cs.empty:
                cs = cs.sort_values("create_time")
            rows = [("v", f"video:{vid}", None)] + [
                (None, f"comment:{c['id']}", c) for _, c in cs.iterrows() if str(c.get("text") or "").strip()
            ]
            for i in range(0, len(rows), BATCH_ITEMS):
                chunk = rows[i:i + BATCH_ITEMS]
                lines, keys = [], {}
                n = 0
                for short, key, c in chunk:
                    if short == "v":
                        keys["v"] = key
                        continue
                    n += 1
                    sid = f"c{n}"
                    keys[sid] = key
                    t = pd.Timestamp(int(c["create_time"]), unit="s", tz="UTC")
                    lines.append(f'{sid} [{_fmt_offset(t, kickoff)}, {int(c.get("like_count") or 0)} likes]: '
                                 f'{str(c["text"])[:600]}')
                body = vctx + ("\n\nLabel the video (id \"v\")" if "v" in keys else "\n\n(Video already labeled; "
                               "use it as context only.)")
                if lines:
                    body += " and these comments:\n" + "\n".join(lines) if "v" in keys else "\nLabel these comments:\n" + "\n".join(lines)
                tasks.append({"task_id": f"{year}_{vid}_{i // BATCH_ITEMS}", "keys": keys, "prompt": body,
                              "season": year})
                if limit and len(tasks) >= limit:
                    return tasks
    return tasks


def _labeled(model_key: str) -> set[str]:
    done = set()
    for year in seasons():
        p = label_path(year, model_key)
        if p.exists():
            done |= {json.loads(l)["key"] for l in p.open() if l.strip()}
    return done


def _params(model: str, prompt: str) -> dict:
    return dict(
        model=model,
        max_tokens=16000,
        output_config={"effort": "low", "format": OUTPUT_FORMAT},
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )


def _write(model_key: str, task: dict, msg) -> int:
    if msg.stop_reason != "end_turn":
        log.warning("%s %s: stop_reason=%s", model_key, task["task_id"], msg.stop_reason)
        return 0
    text = next((b.text for b in msg.content if b.type == "text"), "")
    items = json.loads(text)["items"]
    n = 0
    with label_path(task["season"], model_key).open("a") as fh:
        for it in items:
            key = task["keys"].get(it.pop("id"))
            if not key:
                continue
            fh.write(json.dumps({"key": key, "model": MODELS[model_key], "prompt": PROMPT_VERSION,
                                 "season": task["season"], **it}, ensure_ascii=False) + "\n")
            n += 1
    return n


def _pending(model_key: str, tasks: list[dict]) -> list[dict]:
    done = _labeled(model_key)
    return [t for t in tasks if any(k not in done for k in t["keys"].values())]


def run_sync(model_key: str, tasks: list[dict], client: anthropic.Anthropic) -> None:
    model = MODELS[model_key]
    for i, t in enumerate(tasks, 1):
        params = _params(model, t["prompt"])
        if model_key in ("sonnet", "opus"):  # server-side refusal fallback (not available on Haiku)
            msg = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params)
        else:
            msg = client.messages.create(**params)
        n = _write(model_key, t, msg)
        log.info("%s %d/%d %s: %d labels", model_key, i, len(tasks), t["task_id"], n)


def run_batch(model_key: str, tasks: list[dict], client: anthropic.Anthropic) -> None:
    by_id = {t["task_id"]: t for t in tasks}
    state_file = BATCH_DIR / f"{model_key}.json"
    if state_file.exists():  # resume a batch submitted earlier
        batch_id = json.loads(state_file.read_text())["id"]
    else:
        batch = client.messages.batches.create(requests=[
            Request(custom_id=t["task_id"], params=MessageCreateParamsNonStreaming(**_params(MODELS[model_key], t["prompt"])))
            for t in tasks
        ])
        batch_id = batch.id
        state_file.write_text(json.dumps({"id": batch_id, "tasks": list(by_id)}))
        log.info("%s: submitted batch %s with %d requests", model_key, batch_id, len(tasks))
    while (b := client.messages.batches.retrieve(batch_id)).processing_status != "ended":
        log.info("%s batch %s: %s (%d processing, %d done)", model_key, batch_id, b.processing_status,
                 b.request_counts.processing, b.request_counts.succeeded)
        time.sleep(60)
    retry = []
    n = 0
    for r in client.messages.batches.results(batch_id):
        t = by_id.get(r.custom_id)
        if t is None:
            continue
        if r.result.type == "succeeded" and r.result.message.stop_reason == "end_turn":
            n += _write(model_key, t, r.result.message)
        else:
            retry.append(t)
    state_file.unlink()
    log.info("%s: batch done, %d labels, %d tasks to retry synchronously", model_key, n, len(retry))
    if retry:
        run_sync(model_key, retry, client)


def run(model_keys: list[str], limit: int | None = None, sync: bool = False) -> None:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    tasks = build_tasks(limit)
    log.info("%d tasks, %d items", len(tasks), sum(len(t["keys"]) for t in tasks))
    client = anthropic.Anthropic()
    for mk in model_keys:
        todo = _pending(mk, tasks)
        log.info("%s (%s): %d tasks pending", mk, MODELS[mk], len(todo))
        if todo:
            (run_sync if sync else run_batch)(mk, todo, client)
