# Big Game Pulse: Stanford vs. Cal on TikTok, 2020–2025

How did fans feel about the Big Game? This project collects every on-topic TikTok video and
comment from the 2020–2025 Stanford–Cal football games, has three Claude models label each one
for fan side, sentiment and emotion, and replays the mood against the scoreboard in a local
dashboard. The dashboard also includes coaches, players and box scores (ESPN) and live betting
odds (Polymarket).

**Data from TikTok · Sentiment analysis by Claude · Game records from ESPN · Odds from Polymarket**

> This repository holds code only. No TikTok data, labels or results are included: TikTok
> Research API data is confidential to the approved research team, and findings go to TikTok for
> review before publication. To run it you need your own Research API access and an Anthropic
> API key.

```
TikTok Research API ──► pipeline/collect ──► data/<year>_biggame/{videos,comments}.jsonl
ESPN game records   ──► pipeline/espn    ──► data/<year>_biggame/game.json
ESPN box score + rosters ► pipeline/football ► data/<year>_biggame/football.json
Claude Haiku/Sonnet/Opus ► pipeline/label ──► data/<year>_biggame/labels/<model>.jsonl
                           pipeline/build ──► data/dashboard/*.json
                           backend/app.py ──► http://127.0.0.1:8050  (frontend/)
```

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- TikTok Research API credentials (client key and secret)
- An Anthropic API key
- `ttresearch`, the TikTok Research API client. It isn't published here: `pyproject.toml`
  expects it in a sibling folder, `../tiktok_data`. Point `[tool.uv.sources]` at your own copy.

## Quick start

```bash
uv sync                      # Python 3.12 env; uses ttresearch from ../tiktok_data
uv run biggame status        # what's collected per season, quota left today
uv run biggame football      # coaches, rosters, box scores (ESPN)
uv run biggame label --limit 3 --sync --models haiku   # pilot: 3 requests, check the output
uv run biggame label         # all items × 3 models via the Batch API (~1h)
uv run biggame build         # combine data + labels into the dashboard dataset
uv run biggame serve         # open http://127.0.0.1:8050
```

All commands are safe to re-run. They skip work that's already done.

## Setup

`.env` (never share or commit it):

| Variable | Used for |
|---|---|
| `TIKTOK_CLIENT_ID`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | TikTok Research API (key + secret authenticate) |
| `TTR_DATA_DIR` | Data folder, default `data` |
| `ANTHROPIC_API_KEY` | LLM labeling (console.anthropic.com → API keys) |

The TikTok client code (`ttresearch`: auth, retries, quota ledger, resumable studies) lives in
the sibling project `../tiktok_data` and is installed from there as an editable dependency.
Its README documents every Research API endpoint, limit and known issue.

## Commands

| Command | What it does |
|---|---|
| `biggame games` | Refreshes kickoff time, final score and timed scoring plays from ESPN into each `game.json` |
| `biggame football` | Coaches (curated in `seasons.yaml`), full season rosters (position, class, height/weight, hometown) and every player's box-score line for the Big Game |
| `biggame collect` | For every season: 4 queries × 4 weekly windows of videos, then comments on on-topic videos (most-commented first, ≤ 1,000 each). Stops cleanly at the daily quota; re-run after 00:00 UTC (4 pm PT) |
| `biggame status` | Per-season counts and remaining quota |
| `biggame label [--models haiku,sonnet,opus] [--limit N] [--sync]` | LLM labeling; Batch API by default (50% cheaper), `--sync` for quick pilots |
| `biggame build` | Ensemble labels, compute timelines and agreement, write `data/dashboard/` |
| `biggame serve [--port 8050]` | Dashboard on localhost (also has a **Rebuild** button) |

## Seasons

Defined in `seasons.yaml` (dates, ESPN game IDs, venues). Scores and kickoffs come from ESPN.

| Year | Date | Venue | Result | Kickoff (PT) |
|---|---|---|---|---|
| 2020 | Fri Nov 27 | Berkeley | Stanford 24–23 | 1:30 pm (COVID, no fans) |
| 2021 | Sat Nov 20 | Stanford | Cal 41–11 | 4:00 pm |
| 2022 | Sat Nov 19 | Berkeley | Cal 27–20 | 2:30 pm |
| 2023 | Sat Nov 18 | Stanford | Cal 27–15 | 3:30 pm |
| 2024 | Sat Nov 23 | Berkeley | Cal 24–21 | 12:30 pm |
| 2025 | Sat Nov 22 | Stanford | Stanford 31–10 | 4:30 pm |

The collection window runs from 12 days before to 15 days after each game.

## Method

**Relevance.** TikTok matches keywords fuzzily, so most matches aren't about the game. A rule
filter (`pipeline/relevance.py`) reads the caption, hashtags, transcript and on-screen text, and
sorts each video into `big_game`, `team_football`, `off_topic` (big-game *hunting*) or
`unrelated`. Only `big_game` videos are analyzed. Each year's final score (e.g. "31-10") also
counts as a rivalry marker.

**Labels.** Each request carries one video's context (season result, caption, transcript,
on-screen text) and up to 40 of its comments, each stamped with its time relative to kickoff.
The prompt explains rivalry emojis (🌲 🐻 🪓, 😭💀 = laughter, 🤡 = mockery). For each item, the
model returns this schema (`pipeline/label.py`):

| Field | Values |
|---|---|
| `relevant` | about the game, rivalry, teams, fans or schools? |
| `stance` | the side the author is on: `stanford` · `cal` · `neutral` · `unclear` |
| `sentiment` | the author's own valence, −2 … +2 (gloating is positive for the gloater) |
| `target` | who the sentiment is aimed at |
| `emotion` | joy, pride, banter, mockery, anger, frustration, sadness, surprise, nostalgia, support, neutral |
| `topics` | score, specific play, players, coach, Axe, band, fans/tailgate, … |
| `sarcasm`, `confidence` | |

Three models label every item independently: `claude-haiku-5-5`, `claude-sonnet-5-5` and
`claude-opus-5-5`, all at low effort with structured JSON output. Sonnet and Opus retry refusals
on a fallback model (server-side fallback in `--sync` mode; batch refusals are retried
synchronously).

**Ensemble** (`pipeline/build.py`): majority vote for categories (ties go to Opus, then Sonnet),
mean for sentiment, and topics named by at least half the models. The dashboard reports pairwise
agreement (side agreement on Stanford / Cal / no side, exact stance agreement and Cohen's κ, sentiment sign agreement, share within 1 point,
correlation) and lists the comments where the models disagree most.

**Coaches and players.** Season rosters and box scores come from ESPN. Head coaches are curated
in `seasons.yaml` because ESPN's coach endpoint returns today's coach for every past season.
Players are ranked within each game by a fantasy-style **impact score**: pass yds/25 + 4·TD
− 2·INT, rush/receiving yds/10 + 6·TD + 0.5·rec, tackles + 3·sacks + TFL + PD + 5·INT, and
kicking points. **Fan buzz** counts comments and captions naming a coach or player: the full name
always counts, and the last name alone counts only when it isn't an English word or a very common
name, plus a few nicknames such as "JKS". Each entry shows the average sentiment of those
mentions. ESPN rosters sometimes still list players who had left (e.g. Fernando Mendoza on the
2025 Cal roster); the dashboard tags anyone without game stats as "ESPN roster only".

**Momentum** for a time bin = mean sentiment of Stanford-leaning items − mean sentiment of
Cal-leaning items, shown only when each side has ≥ 3 items. Positive means Stanford fans feel
better at that moment. Game-day bins are 15 minutes, from −3h to +7h around kickoff. Scoring
plays use ESPN wall-clock times.

**Estimated LLM cost:** a few thousand items through the Batch API costs roughly $10–15 in total,
mostly Opus. Run `--limit` pilots first.

## Dashboard

- **Season view:**
  - Scoreboard and stat tiles.
  - **Game-day replay:** a momentum curve with scoring plays, a volume chart, and a Replay
    button and scrubber that step through the game, updating the live score and showing the
    most-liked comments at each moment.
  - Daily fan mood for each side, and who's talking (side mix per day).
  - Emotions by side, and topics.
  - Model agreement, and where the models disagree.
  - Top videos, and a searchable comment table.
  - **Teams & players:** head coaches with tenure and the record after the game, a side-by-side
    team box score, the top performers on each side (headshot, stat line, impact score), fan
    buzz (most-named coaches and players, with sentiment), and a searchable season roster with
    each player's Big Game stats.
- **All years:** small multiples of the six game-day momentum curves on a shared clock, in-game
  momentum by year, comment volume, and a season table.

The dashboard uses a single light theme. Stanford red (`#c8342f`) and Cal blue (`#2a78d6`) passed
the colorblind-safety validator on its surface. Commenter names are never written to the dashboard
data.

## Betting markets (Polymarket)

The **2026 odds** tab at the end of the season bar (or **2026 betting odds** on the front page) opens a panel of live prediction-market odds from Polymarket's public APIs (Gamma
for markets and prices, CLOB for price history; no account or key). Results are cached for 2
minutes, and closed markets are cached on disk. Market slugs are listed in `seasons.yaml` →
`polymarket`.

| Card | Market |
|---|---|
| Next Big Game | `cfb-stan-cah-2026-11-21`: moneyline odds, a countdown to kickoff, price history and a link |
| 2026 win totals | `ncaa-football-stanford-2026-win-total` and `ncaa-football-california-2026-win-total`: odds of finishing above each win line; settled lines are marked ✓/✗ |
| 2025 market vs result | `cfb-cah-stan-2025-11-22`: Stanford opened at 43.5% and was 36.5% at kickoff, then won 31–10 ($225K traded) |

The 2025 scoreboard also shows the kickoff odds. Prices are implied probabilities shown for
context, not betting advice. Endpoint: `GET /api/markets`.

## Project layout

```
README.md  LICENSE  pyproject.toml  uv.lock  seasons.yaml  .env.example  (.env is local only)
pipeline/            Python package: the data + analysis code
  env.py             loads .env, pins the data dir
  config.py          seasons.yaml → Season objects
  espn.py            game facts from ESPN
  football.py        coaches, rosters, box scores from ESPN
  markets.py         Polymarket odds and price history
  collect.py         TikTok collection inside the daily quota
  relevance.py       rule-based relevance tiers
  label.py           multi-model LLM labeling (Batch API)
  build.py           ensemble, timelines, agreement → data/dashboard/
  status.py, cli.py
backend/app.py       FastAPI: /api/index, /api/season/{year}, /api/compare, /api/markets, /api/rebuild, static frontend
frontend/            index.html, app.js, styles.css, vendor/echarts.min.js (5.5.1, bundled), assets/ (hero, logo, favicon)
data/                (local only, git-ignored)
  <year>_biggame/    videos.jsonl, comments.jsonl, state.json, runs.jsonl, game.json,
                     football.json, labels/<model>.jsonl
  .cache/espn/       cached ESPN athlete records
  dashboard/         built JSON the backend serves
  .quota.json        local request ledger
logs/                collection and server logs (git-ignored)
```

## Caveats and rules

- **TikTok Confidential.** Research Data, even aggregated, may only be shared within the
  approved team. `data/` and `.env` are git-ignored; keep it that way. The dashboard binds to
  `127.0.0.1` only. Publications go to TikTok 7 days in
  advance, with no individual users identifiable. This folder syncs to OneDrive; check that this
  meets the data-security terms, or point `TTR_DATA_DIR` at local encrypted storage.
- **LLM processing** sends comment text to the Anthropic API. The project owner confirmed this is
  permitted for this project.
- **Refresh at least every 30 days.** The Terms require re-fetching stored data. Re-running
  collection after deleting `state.json` re-queries everything.
- **Coverage.** The API returns only public content from adults, under-returns content from
  before 2021 (2020 is thin), and makes new videos searchable only after up to 48h. Engagement
  counts are as of collection time. Comment timestamps are exact, which is why comments drive
  the timeline.
- **LLM labels are measurements with error.** For publishable estimates, hand-label a random
  sample of about 300 items and correct the estimates with design-based supervised learning
  (Egami et al., NeurIPS 2023).

## License

The code is released under the [MIT License](LICENSE).

The images in `frontend/assets/` and the team names, logos and marks they show belong to their
owners (Stanford University, the University of California, Berkeley, and others). They are not
covered by the MIT License. ECharts (`frontend/vendor/`) is Apache-2.0 licensed. This is an
independent research project, not affiliated with or endorsed by either university, TikTok,
Anthropic, ESPN or Polymarket.
