/* Big Game Pulse: dashboard front end. Data comes from the FastAPI backend (/api/*). */
const $ = (s) => document.querySelector(s);
const state = { index: null, year: null, data: null, compare: null, charts: {}, cursor: -180, timer: null };

/* ---------------- utilities ---------------- */
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const C = () => ({
  st: css("--stanford"), ca: css("--cal"), neu: css("--neutral"), unc: css("--unclear"),
  ink: css("--ink"), ink2: css("--ink-2"), ink3: css("--ink-3"), line: css("--line"),
  surf: css("--surface"), accent: css("--accent"),
});
const fmt = (n) => n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n);
const sgn = (v, d = 2) => v == null ? "–" : (v > 0 ? "+" : "") + Number(v).toFixed(d);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const tLabel = (m) => {
  if (m === 0) return "KO";
  const a = Math.abs(m), h = Math.floor(a / 60), mm = Math.round(a % 60);
  return (m < 0 ? "−" : "+") + (h ? `${h}h` : "") + (mm ? `${String(mm).padStart(h ? 2 : 1, "0")}m` : "");
};
const sideName = { stanford: "Stanford", cal: "Cal", neutral: "Neutral", unclear: "Unclear" };
const emojiAxe = "🪓";
async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function chart(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  if (state.charts[id]) state.charts[id].dispose();
  el.innerHTML = "";  // drop any previous empty-state message
  const c = echarts.init(el, null, { renderer: "canvas" });
  state.charts[id] = c;
  return c;
}
function emptyChart(id, msg) {
  if (state.charts[id]) { state.charts[id].dispose(); delete state.charts[id]; }
  document.getElementById(id).innerHTML = `<div class="empty">${esc(msg)}</div>`;
}
window.addEventListener("resize", () => Object.values(state.charts).forEach((c) => c.resize()));

function baseAxis(c) {
  return {
    axisLine: { lineStyle: { color: c.line } }, axisTick: { show: false },
    axisLabel: { color: c.ink2, fontSize: 11 }, splitLine: { lineStyle: { color: c.line, width: 1 } },
  };
}
function tooltip(c, extra = {}) {
  return {
    trigger: "axis", backgroundColor: c.surf, borderColor: c.line, textStyle: { color: c.ink, fontSize: 12 },
    axisPointer: { type: "line", lineStyle: { color: c.ink3, width: 1 } }, ...extra,
  };
}

/* ---------------- season nav ---------------- */
function renderNav() {
  const nav = $("#seasons");
  const open = !$("#markets").classList.contains("hidden");
  nav.innerHTML = [...state.index.seasons].sort((a, b) => b.year - a.year).map((s) => `
    <button role="tab" class="w-${s.winner}" data-year="${s.year}" aria-selected="${state.year === s.year}">
      <span class="y">${s.year}</span>
      <span class="r"><i class="dot ${s.winner}"></i>${s.winner === "stanford" ? "Stanford" : "Cal"} ${Math.max(s.stanford, s.cal)}–${Math.min(s.stanford, s.cal)}</span>
    </button>`).join("") + `
    <button role="tab" class="compare" data-year="compare" aria-selected="${state.year === "compare"}">
      <span class="y">All years</span><span class="r">Compare 2020–2025</span>
    </button>
    <button class="odds-tab" id="go-odds" aria-expanded="${open}" aria-controls="markets" title="Show the Polymarket betting odds">
      <span class="y">2026 odds</span><span class="r">📈 ${open ? "Hide" : "Polymarket"}</span>
    </button>`;
  nav.querySelectorAll("button[data-year]").forEach((b) => b.onclick = () => select(b.dataset.year === "compare" ? "compare" : +b.dataset.year));
  $("#go-odds").onclick = () => showOdds($("#markets").classList.contains("hidden"));
}

async function select(year) {
  stopReplay();
  state.year = year;
  try { localStorage.setItem("bg-year", String(year)); } catch (e) {}
  renderNav();
  const isCompare = year === "compare";
  $("#season-view").classList.toggle("hidden", isCompare);
  $("#compare-view").classList.toggle("hidden", !isCompare);
  if (isCompare) {
    state.compare = state.compare || await api("/api/compare");
    renderCompare();
  } else {
    state.data = await api(`/api/season/${year}`);
    renderSeason();
  }
}

/* ---------------- season view ---------------- */
function renderSeason() {
  const d = state.data, g = d.game, s = d.summary || {};
  const ko = new Date(g.kickoff_utc);
  const koStr = ko.toLocaleString("en-US", { timeZone: "America/Los_Angeles", weekday: "short", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  const team = (k, cls) => `
    <div class="team ${cls} ${g.winner === k ? "win" : "lose"}">
      ${cls === "cal" ? `<div class="score">${g.teams[k].score}</div>` : ""}
      <div><div class="name">${k === "stanford" ? "Stanford" : "Cal"}</div>
        <div style="color:var(--ink-3);font-size:12px">${esc(g.teams[k].name)}${g.home === k ? " · home" : ""}</div>
        ${d.football?.coaches?.[k] ? `<div style="color:var(--ink-2);font-size:12px;margin-top:2px">HC ${esc(d.football.coaches[k].name)}${d.football.teams?.[k]?.record_after_game ? ` · ${esc(d.football.teams[k].record_after_game)} after the game` : ""}</div>` : ""}</div>
      ${cls === "stanford" ? `<div class="score">${g.teams[k].score}</div>` : ""}
    </div>`;
  $("#scoreboard").innerHTML = `${team("stanford", "stanford")}
    <div class="meta"><span class="axe">${emojiAxe}</span><b>${d.year} Big Game</b><br>${esc(g.venue)}<br>${koStr} PT
      ${state.markets?.big_game?.[d.year]?.pregame_stanford != null ? `<div class="note">Polymarket at kickoff: Stanford ${Math.round(100 * state.markets.big_game[d.year].pregame_stanford)}% · Cal ${100 - Math.round(100 * state.markets.big_game[d.year].pregame_stanford)}%</div>` : ""}
      ${g.note ? `<div class="note">${esc(g.note)}</div>` : ""}</div>
    ${team("cal", "cal")}`;

  const gw = s.game_window || {};
  const labeled = (s.items_labeled || 0) > 0;
  const tiles = [
    { l: "On-topic videos", v: fmt(s.videos_on_topic), n: `of ${fmt(s.videos_matched)} matched · ${fmt(s.creators)} creators` },
    { l: "Views", v: fmt(s.views), n: `${fmt(s.likes)} likes · ${fmt(s.shares)} shares` },
    { l: "Comments", v: fmt(s.comments_collected), n: `${fmt(s.comments_counted)} counted by TikTok` },
    { l: "Items labeled", v: fmt(s.items_labeled), n: "comments + videos, 3 models" },
    { l: "Momentum, KO to +48h", v: sgn(gw.momentum), n: gw.momentum == null ? (labeled ? "too few posts from one side" : "needs labels") : gw.momentum > 0 ? "Stanford fans happier" : "Cal fans happier" },
    { l: "Fan split", v: s.overall_n ? `${Math.round(100 * s.overall_n_stanford / s.overall_n)}/${Math.round(100 * s.overall_n_cal / s.overall_n)}` : "–", n: "% Stanford / % Cal leaning" },
  ];
  $("#tiles").innerHTML = tiles.map((t) => `<div class="tile"><div class="l">${t.l}</div><div class="v">${t.v}</div><div class="n">${t.n}</div></div>`).join("");

  const un = $("#unlabeled");
  un.classList.toggle("hidden", labeled);
  un.innerHTML = labeled ? "" : `Sentiment for ${d.year} hasn't been labeled yet, so only volume is shown. Add <code>ANTHROPIC_API_KEY</code> to <code>.env</code>, then run <code>uv run biggame label</code> and <code>uv run biggame build</code>.`;

  renderMomentum(); renderVolume(); renderMood(); renderShare(); renderEmotions(); renderTopics(); renderModels();
  renderDisagree(); renderVideos(); renderComments(); renderFootball();
  setCursor(-180);
}

function playsSeries(c, yFor) {
  const plays = (state.data.game.scoring_plays || []).filter((p) => p.t_min != null);
  return {
    type: "scatter", name: "Scoring plays", symbolSize: 11, z: 5,
    data: plays.map((p) => ({ value: [p.t_min, yFor(p)], play: p, itemStyle: { color: p.team === "stanford" ? c.st : c.ca, borderColor: c.surf, borderWidth: 2 } })),
    tooltip: { trigger: "item", formatter: (o) => `<b>${tLabel(o.data.play.t_min)} · ${esc(o.data.play.type)}</b><br>${esc(o.data.play.text)}<br>Stanford ${o.data.play.stanford} – Cal ${o.data.play.cal}` },
  };
}

function renderMomentum() {
  const tl = state.data.timeline_game || [];
  const has = tl.some((r) => r.momentum != null);
  if (!has) return emptyChart("c-momentum", (state.data.summary?.items_labeled ? `Too few posts from both sides during the ${state.data.year} game to plot momentum (at least 3 per side per hour are needed). Most reaction came afterward; see the fan-mood chart below.` : "Sentiment not labeled yet"));
  const c = C(), ch = chart("c-momentum");
  const vals = tl.map((r) => r.momentum).filter((v) => v != null);
  const lim = Math.max(1, Math.ceil(Math.max(...vals.map(Math.abs)) * 2) / 2);
  ch.setOption({
    grid: { left: 44, right: 16, top: 16, bottom: 28 },
    tooltip: tooltip(c, { formatter: (ps) => {
      const r = tl.find((x) => x.t === ps[0].value[0]); if (!r) return "";
      return `<b>${tLabel(r.t)}</b><br>Momentum <b>${sgn(r.momentum)}</b><br>Stanford fans ${sgn(r.mood_stanford)} (n=${r.n_stanford})<br>Cal fans ${sgn(r.mood_cal)} (n=${r.n_cal})`;
    } }),
    xAxis: { type: "value", min: -180, max: 420, interval: 60, ...baseAxis(c), splitLine: { show: false }, axisLabel: { color: c.ink2, fontSize: 11, formatter: tLabel } },
    yAxis: { type: "value", min: -lim, max: lim, ...baseAxis(c), axisLabel: { color: c.ink2, fontSize: 11, formatter: (v) => sgn(v, 1) } },
    visualMap: { show: false, type: "piecewise", seriesIndex: 0, dimension: 1, pieces: [{ gt: 0, lte: 99, color: c.st }, { gt: -99, lte: 0, color: c.ca }] },
    series: [
      { type: "line", name: "Momentum", data: tl.filter((r) => r.momentum != null).map((r) => [r.t, r.momentum]), smooth: 0.25, showSymbol: false,
        lineStyle: { width: 2.5, shadowBlur: 10, shadowColor: "rgba(255,255,255,.25)" }, areaStyle: { opacity: 0.18 } },
      { ...playsSeries(c, () => lim * 0.88) },
      guideSeries(momentumMarks(c, state.cursor)),
    ],
  });
}

// Reference lines live on their own invisible series: markLines on a visualMap-colored line crash ECharts.
function guideSeries(marks) {
  return { type: "line", name: "guides", data: [[-180, 0], [420, 0]], symbol: "none", silent: true, tooltip: { show: false },
    lineStyle: { opacity: 0 }, markLine: { silent: true, symbol: "none", animation: false, data: marks } };
}
function momentumMarks(c, cursor) {
  return [
    { yAxis: 0, lineStyle: { color: c.ink3, width: 1, type: "solid" }, label: { show: false } },
    { xAxis: 0, lineStyle: { color: c.ink3, width: 1, type: "solid" }, label: { formatter: "Kickoff", color: c.ink2, fontSize: 11 } },
    { xAxis: cursor, lineStyle: { color: c.accent, width: 1.5, type: "solid" }, label: { show: false } },
  ];
}

function renderVolume() {
  const tl = state.data.timeline_game || [];
  if (!tl.some((r) => r.volume)) return emptyChart("c-volume", "No posts in the game window");
  const c = C(), ch = chart("c-volume");
  ch.setOption({
    grid: { left: 44, right: 16, top: 22, bottom: 24 },
    title: { text: "Posts per 15 min", left: 0, top: 0, textStyle: { color: c.ink2, fontSize: 12, fontWeight: 500 } },
    tooltip: tooltip(c, { formatter: (ps) => `<b>${tLabel(ps[0].value[0])}</b><br>${ps[0].value[1]} comments + videos` }),
    xAxis: { type: "value", min: -180, max: 420, interval: 60, ...baseAxis(c), splitLine: { show: false }, axisLabel: { color: c.ink2, fontSize: 11, formatter: tLabel } },
    yAxis: { type: "value", ...baseAxis(c), splitNumber: 3 },
    series: [{ type: "bar", data: tl.map((r) => [r.t + 7.5, r.volume]), barWidth: "60%", itemStyle: { color: c.ink3, borderRadius: [3, 3, 0, 0] } },
      { ...playsSeries(c, () => 0), symbolSize: 8 }],
  });
}

function dayLabel(t) {
  const ko = new Date(state.data.game.kickoff_utc);
  const d = new Date(ko.getTime() + t * 60000);
  return d.toLocaleDateString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric" });
}

function renderMood() {
  const tl = state.data.timeline_daily || [];
  if (!tl.some((r) => r.mood_stanford != null || r.mood_cal != null)) return emptyChart("c-mood", "No labeled sentiment yet");
  const c = C(), ch = chart("c-mood");
  ch.setOption({
    grid: { left: 40, right: 16, top: 14, bottom: 28 },
    tooltip: tooltip(c, { formatter: (ps) => {
      const r = tl[ps[0].dataIndex];
      return `<b>${dayLabel(r.t)}</b><br><span style="color:${c.st}">●</span> Stanford fans ${sgn(r.mood_stanford)} (n=${r.n_stanford})<br><span style="color:${c.ca}">●</span> Cal fans ${sgn(r.mood_cal)} (n=${r.n_cal})`;
    } }),
    xAxis: { type: "category", data: tl.map((r) => dayLabel(r.t)), ...baseAxis(c), splitLine: { show: false } },
    yAxis: { type: "value", min: -2, max: 2, interval: 1, ...baseAxis(c) },
    series: [
      { name: "Stanford fans", type: "line", data: tl.map((r) => r.mood_stanford), connectNulls: false, symbolSize: 8, lineStyle: { width: 2, color: c.st }, itemStyle: { color: c.st, borderColor: c.surf, borderWidth: 2 },
        markLine: { silent: true, symbol: "none", data: [{ xAxis: tl.findIndex((r) => r.t === 0 || (r.t <= 0 && r.t + 1440 > 0)), lineStyle: { color: c.ink3, type: "solid", width: 1 }, label: { formatter: "Game day", color: c.ink2, fontSize: 11 } }] } },
      { name: "Cal fans", type: "line", data: tl.map((r) => r.mood_cal), connectNulls: false, symbolSize: 8, lineStyle: { width: 2, color: c.ca }, itemStyle: { color: c.ca, borderColor: c.surf, borderWidth: 2 } },
    ],
  });
}

function renderShare() {
  const tl = state.data.timeline_daily || [];
  if (!tl.some((r) => r.volume)) return emptyChart("c-share", "No posts collected");
  const c = C(), ch = chart("c-share");
  const other = tl.map((r) => Math.max(0, (r.volume || 0) - r.n_stanford - r.n_cal - r.n_neutral));
  const seg = (name, data, color, top) => ({ name, type: "bar", stack: "s", data, barWidth: "62%",
    itemStyle: { color, borderColor: c.surf, borderWidth: 1, borderRadius: top ? [3, 3, 0, 0] : 0 } });
  ch.setOption({
    grid: { left: 44, right: 16, top: 14, bottom: 28 },
    tooltip: tooltip(c, { axisPointer: { type: "shadow" } }),
    xAxis: { type: "category", data: tl.map((r) => dayLabel(r.t)), ...baseAxis(c), splitLine: { show: false } },
    yAxis: { type: "value", ...baseAxis(c) },
    series: [seg("Stanford", tl.map((r) => r.n_stanford), c.st), seg("Cal", tl.map((r) => r.n_cal), c.ca),
      seg("Neutral", tl.map((r) => r.n_neutral), c.neu), seg("Unlabeled / unclear", other, c.unc, true)],
  });
}

function renderEmotions() {
  const e = state.data.emotions || {};
  const st = e.stanford || [], ca = e.cal || [];
  if (!st.some((x) => x.n) && !ca.some((x) => x.n)) return emptyChart("c-emotions", "No labeled sentiment yet");
  const c = C(), ch = chart("c-emotions");
  const tot = (a) => a.reduce((s, x) => s + x.n, 0) || 1;
  const names = st.map((x) => x.name).filter((n, i) => (st[i].n + (ca[i]?.n || 0)) > 0);
  const pick = (a) => names.map((n) => +(100 * (a.find((x) => x.name === n)?.n || 0) / tot(a)).toFixed(1));
  ch.setOption({
    grid: { left: 84, right: 24, top: 8, bottom: 24 },
    tooltip: tooltip(c, { axisPointer: { type: "shadow" }, valueFormatter: (v) => v + "%" }),
    xAxis: { type: "value", ...baseAxis(c), axisLabel: { color: c.ink2, fontSize: 11, formatter: "{value}%" } },
    yAxis: { type: "category", data: names, inverse: true, ...baseAxis(c), splitLine: { show: false } },
    series: [
      { name: "Stanford fans", type: "bar", data: pick(st), barGap: "20%", barWidth: 7, itemStyle: { color: c.st, borderRadius: [0, 4, 4, 0] } },
      { name: "Cal fans", type: "bar", data: pick(ca), barWidth: 7, itemStyle: { color: c.ca, borderRadius: [0, 4, 4, 0] } },
    ],
  });
}

function renderTopics() {
  const t = (state.data.topics || []).filter((x) => x.n).sort((a, b) => b.n - a.n);
  if (!t.length) return emptyChart("c-topics", "No labeled topics yet");
  const c = C(), ch = chart("c-topics");
  ch.setOption({
    grid: { left: 150, right: 40, top: 8, bottom: 24 },
    tooltip: tooltip(c, { axisPointer: { type: "shadow" } }),
    xAxis: { type: "value", ...baseAxis(c) },
    yAxis: { type: "category", data: t.map((x) => x.name.replace(/_/g, " ")), inverse: true, ...baseAxis(c), splitLine: { show: false } },
    series: [{ type: "bar", name: "Items", data: t.map((x) => x.n), barWidth: 10, itemStyle: { color: c.accent, borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: c.ink2, fontSize: 11 } }],
  });
}

function renderModels() {
  const m = state.data.models || {};
  const pairs = m.pairs || [];
  $("#agree").innerHTML = pairs.length ? `<table><tr><th>Models</th><th class="num">Items</th><th class="num">Side agree</th><th class="num">Stance agree</th><th class="num">Cohen's κ</th><th class="num">Same sign</th><th class="num">Within 1 pt</th><th class="num">r</th></tr>
    ${pairs.map((p) => `<tr><td>${p.a} · ${p.b}</td><td class="num">${p.n}</td><td class="num">${p.side_agree != null ? Math.round(100 * p.side_agree) + "%" : "–"}</td><td class="num">${Math.round(100 * p.stance_agree)}%</td><td class="num">${p.stance_kappa ?? "–"}</td>
      <td class="num">${Math.round(100 * p.sentiment_sign_agree)}%</td><td class="num">${Math.round(100 * p.sentiment_within1)}%</td><td class="num">${p.sentiment_corr ?? "–"}</td></tr>`).join("")}</table>`
    : `<div class="empty">No labels yet. Each model's labels appear here once <code>biggame label</code> has run.</div>`;
  const dist = m.stance_distribution || {};
  const models = ["haiku", "sonnet", "opus"].filter((k) => dist[k]);
  if (!models.length) return emptyChart("c-models", "");
  const c = C(), ch = chart("c-models");
  const seg = (k, color, top) => ({ name: sideName[k], type: "bar", stack: "s", barWidth: 12, data: models.map((mm) => +(100 * (dist[mm][k] || 0)).toFixed(1)),
    itemStyle: { color, borderColor: c.surf, borderWidth: 1, borderRadius: top ? [0, 4, 4, 0] : 0 } });
  ch.setOption({
    grid: { left: 64, right: 16, top: 30, bottom: 20 },
    legend: { top: 0, left: 0, textStyle: { color: c.ink2, fontSize: 11 }, itemWidth: 10, itemHeight: 10, icon: "circle" },
    tooltip: tooltip(c, { axisPointer: { type: "shadow" }, valueFormatter: (v) => v + "%" }),
    xAxis: { type: "value", max: 100, ...baseAxis(c), axisLabel: { color: c.ink2, fontSize: 11, formatter: "{value}%" } },
    yAxis: { type: "category", data: models.map((x) => x[0].toUpperCase() + x.slice(1)), ...baseAxis(c), splitLine: { show: false } },
    series: [seg("stanford", c.st), seg("cal", c.ca), seg("neutral", c.neu), seg("unclear", c.unc, true)],
  });
}

function cmtHTML(x, extra = "") {
  const mood = x.sentiment == null ? "" : `<span class="chip">mood ${sgn(x.sentiment, 1)}</span>`;
  return `<div class="cmt ${x.stance || ""}">${esc(x.text)}
    <div class="m"><span>${tLabel(Math.round(x.t_min))}</span><span>♥ ${fmt(x.likes)}</span>
      ${x.stance ? `<span class="chip"><i class="dot ${x.stance}"></i>${sideName[x.stance] || x.stance}</span>` : ""}
      ${mood}${x.emotion ? `<span class="chip">${esc(x.emotion)}</span>` : ""}${x.sarcasm ? `<span class="chip">sarcasm</span>` : ""}${extra}</div></div>`;
}

function renderDisagree() {
  const d = state.data.disagreements || [];
  $("#disagree").innerHTML = d.length ? d.map((x) => cmtHTML(x, `<span class="chip">spread ${x.sentiment_spread}</span>`)).join("")
    : `<div class="empty">No strong disagreements (or no labels yet)</div>`;
}

function renderVideos() {
  const v = state.data.top_videos || [];
  $("#t-videos").innerHTML = `<tr><th>Posted (PT)</th><th class="num">vs kickoff</th><th>Creator</th><th>Caption</th><th class="num">Views</th><th class="num">Likes</th><th class="num">Comments</th><th>Side</th><th class="num">Mood</th></tr>` +
    v.map((x) => `<tr><td>${esc(x.created_pt)}</td><td class="num">${tLabel(x.t_min)}</td><td><a href="${esc(x.url)}" target="_blank" rel="noopener">@${esc(x.username)}</a></td>
      <td>${esc(x.caption)}</td><td class="num">${fmt(x.views)}</td><td class="num">${fmt(x.likes)}</td><td class="num">${fmt(x.comments)}</td>
      <td>${x.stance ? `<span class="chip"><i class="dot ${x.stance}"></i>${sideName[x.stance]}</span>` : "–"}</td>
      <td class="num">${x.sentiment == null ? "–" : `<span class="sent">${sgn(x.sentiment, 1)}</span>`}</td></tr>`).join("");
}

function renderComments() {
  const q = $("#q").value.toLowerCase(), f = $("#f-stance").value;
  const rows = (state.data.top_comments || []).filter((x) => (!q || String(x.text).toLowerCase().includes(q)) && (!f || x.stance === f));
  $("#t-comments").innerHTML = `<tr><th>Comment</th><th class="num">vs kickoff</th><th class="num">Likes</th><th>Side</th><th class="num">Mood</th><th>Emotion</th></tr>` +
    (rows.length ? rows.map((x) => `<tr><td>${esc(x.text)}</td><td class="num">${tLabel(Math.round(x.t_min))}</td><td class="num">${fmt(x.likes)}</td>
      <td>${x.stance ? `<span class="chip"><i class="dot ${x.stance}"></i>${sideName[x.stance] || x.stance}</span>` : "–"}</td>
      <td class="num"><span class="sent">${sgn(x.sentiment, 1)}</span></td><td>${esc(x.emotion || "")}${x.sarcasm ? " · sarcasm" : ""}</td></tr>`).join("")
      : `<tr><td colspan="6" style="color:var(--ink-3)">No labeled comments${q || f ? " match" : " yet"}</td></tr>`);
}
$("#q").oninput = renderComments;
$("#f-stance").onchange = renderComments;

/* ---------------- teams & players ---------------- */
const TUG_STATS = ["Total Yards", "Passing", "Rushing", "1st Downs", "3rd down efficiency", "Turnovers", "Penalties", "Possession"];
function statNum(label, v) {
  if (v == null) return null;
  v = String(v);
  if (label === "Possession" && v.includes(":")) { const [m, s] = v.split(":").map(Number); return m + s / 60; }
  if (/efficiency/i.test(label) && v.includes("-")) { const [a, b] = v.split("-").map(Number); return b ? (100 * a) / b : 0; }
  if (label === "Penalties" && v.includes("-")) return Number(v.split("-")[0]);
  const n = parseFloat(v); return Number.isFinite(n) ? n : null;
}
function renderFootball() {
  const f = state.data.football;
  if (!f) { $("#coaches").innerHTML = `<div class="empty">Run <code>uv run biggame football</code> to add coaches and players</div>`; return; }
  $("#coaches").innerHTML = ["stanford", "cal"].map((k) => { const c = f.coaches[k] || {}, t = f.teams[k] || {};
    return `<div class="coach ${k}"><div class="ten">${k === "stanford" ? "Stanford" : "Cal"} head coach</div><div class="who">${esc(c.name || "–")}</div>
      <div class="ten">${esc(c.tenure || "")}</div><div class="nt">${esc(c.note || "")}</div>
      <div class="rec">Record after the Big Game: <b>${esc(t.record_after_game || "–")}</b></div></div>`; }).join("");

  const ts = { st: f.teams.stanford?.team_stats || {}, ca: f.teams.cal?.team_stats || {} };
  const keys = TUG_STATS.filter((k) => ts.st[k] != null && ts.ca[k] != null);
  $("#tug").innerHTML = keys.map((k) => {
    const a = statNum(k, ts.st[k]) || 0, b = statNum(k, ts.ca[k]) || 0, tot = a + b || 1;
    const pa = Math.max(2, Math.round((100 * a) / tot));
    return `<div class="row"><div class="lab">${esc(k)}</div><div class="v">${esc(ts.st[k])}</div>
      <div class="bar" title="${esc(k)}: Stanford ${esc(ts.st[k])}, Cal ${esc(ts.ca[k])}"><i style="width:${pa}%"></i><i style="width:${100 - pa}%"></i></div>
      <div class="v r">${esc(ts.ca[k])}</div></div>`; }).join("") || `<div class="empty">No team stats</div>`;

  const maxImp = Math.max(1, ...["stanford", "cal"].flatMap((k) => (f.teams[k]?.performers || []).map((p) => p.impact)));
  for (const k of ["stanford", "cal"]) {
    const ps = (f.teams[k]?.performers || []).slice(0, 8);
    $(`#perf-${k}`).innerHTML = ps.map((p) => `<div class="pl ${k}">
      ${p.headshot ? `<img src="${esc(p.headshot)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'ph'}))">` : `<div class="ph"></div>`}
      <div><div class="nm">${esc(p.name)} <span class="ps">${p.jersey ? "#" + esc(p.jersey) + " · " : ""}${esc(p.position || "")}${p.class ? " · " + esc(p.class) : ""}</span></div>
        <div class="ln">${esc(p.line || "")}</div></div>
      <div class="im"><b>${p.impact.toFixed(1)}</b><div class="meter"><i style="width:${Math.max(0, (100 * p.impact) / maxImp)}%"></i></div></div></div>`).join("")
      || `<div class="empty">No box score</div>`;
  }

  const buzz = (f.buzz || []).slice(0, 15);
  if (!buzz.length) emptyChart("c-buzz", "No coach or player was named in this season's comments");
  else {
    const c = C(), ch = chart("c-buzz");
    ch.setOption({
      grid: { left: 150, right: 40, top: 8, bottom: 24 },
      tooltip: { trigger: "item", backgroundColor: c.surf, borderColor: c.line, textStyle: { color: c.ink, fontSize: 12 },
        formatter: (o) => { const b = buzz[o.dataIndex]; return `<b>${esc(b.name)}</b> · ${esc(b.role)}${b.position && b.position !== "HC" ? " (" + esc(b.position) + ")" : ""}${b.played ? "" : " · on ESPN roster only"}<br>${b.mentions} mentions · ${fmt(b.likes)} likes<br>Average sentiment ${sgn(b.sentiment)}<br>From Stanford fans ${b.from_stanford} · Cal fans ${b.from_cal}`; } },
      xAxis: { type: "value", minInterval: 1, ...baseAxis(c) },
      yAxis: { type: "category", inverse: true, data: buzz.map((b) => b.name), ...baseAxis(c), splitLine: { show: false } },
      series: [{ type: "bar", barWidth: 10, data: buzz.map((b) => ({ value: b.mentions, itemStyle: { color: b.team === "stanford" ? c.st : c.ca, borderRadius: [0, 4, 4, 0] } })),
        label: { show: true, position: "right", color: c.ink2, fontSize: 11 } }],
    });
  }
  $("#buzz-list").innerHTML = buzz.length ? buzz.map((b) => `<div class="cmt ${b.team}"><b>${esc(b.name)}</b>: ${esc(b.top_text)}
      <div class="m"><span>♥ ${fmt(b.top_likes)}</span><span class="chip">${b.mentions} mentions</span>${b.sentiment != null ? `<span class="chip">mood ${sgn(b.sentiment, 1)}</span>` : ""}${b.played ? "" : `<span class="chip">ESPN roster only</span>`}</div></div>`).join("")
    : `<div class="empty">No mentions</div>`;

  const pos = [...new Set(["stanford", "cal"].flatMap((k) => (f.teams[k]?.roster || []).map((p) => p.position)).filter(Boolean))].sort();
  const sel = $("#r-pos"), cur = sel.value;
  sel.innerHTML = `<option value="">All positions</option>` + pos.map((p) => `<option ${p === cur ? "selected" : ""}>${esc(p)}</option>`).join("");
  renderRoster();
}
function renderRoster() {
  const f = state.data?.football; if (!f) return;
  const q = $("#rq").value.toLowerCase(), team = $("#r-team").value, pos = $("#r-pos").value, played = $("#r-played").value;
  const perf = {}; for (const k of ["stanford", "cal"]) for (const p of f.teams[k]?.performers || []) perf[p.id] = p;
  const rows = ["stanford", "cal"].filter((k) => !team || k === team).flatMap((k) => (f.teams[k]?.roster || []).map((p) => ({ ...p, team: k })))
    .filter((p) => (!q || `${p.name} ${p.hometown}`.toLowerCase().includes(q)) && (!pos || p.position === pos) && (!played || p.played))
    .sort((a, b) => (perf[b.id]?.impact ?? -99) - (perf[a.id]?.impact ?? -99) || String(a.name).localeCompare(b.name));
  $("#t-roster").innerHTML = `<tr><th>Team</th><th class="num">#</th><th>Name</th><th>Pos</th><th>Class</th><th>Ht / Wt</th><th>Hometown</th><th>Big Game stats</th><th class="num">Impact</th></tr>` +
    rows.slice(0, 400).map((p) => `<tr><td><i class="dot ${p.team}"></i> ${p.team === "stanford" ? "STAN" : "CAL"}</td><td class="num">${esc(p.jersey || "")}</td><td>${esc(p.name)}</td>
      <td>${esc(p.position || "")}</td><td>${esc(p.class || "")}</td><td>${esc(p.height || "")}${p.weight ? " · " + esc(p.weight) : ""}</td><td>${esc(p.hometown || "")}</td>
      <td>${esc(perf[p.id]?.line || "")}</td><td class="num">${perf[p.id] ? perf[p.id].impact.toFixed(1) : ""}</td></tr>`).join("")
    + (rows.length ? "" : `<tr><td colspan="9" style="color:var(--ink-3)">No players match</td></tr>`);
}
["#rq", "#r-team", "#r-pos", "#r-played"].forEach((id) => { $(id).oninput = renderRoster; $(id).onchange = renderRoster; });

/* ---------------- replay ---------------- */
function setCursor(t) {
  state.cursor = t;
  $("#scrub").value = t;
  const ko = new Date(state.data.game.kickoff_utc);
  const wall = new Date(ko.getTime() + t * 60000).toLocaleTimeString("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" });
  $("#clock").textContent = `${tLabel(t)} · ${wall} PT`;
  const plays = (state.data.game.scoring_plays || []).filter((p) => p.t_min != null && p.t_min <= t);
  const last = plays[plays.length - 1];
  $("#live-score").innerHTML = t < 0 ? `<span style="color:var(--ink-3);font-size:14px">Pre-game</span>`
    : `<span class="s">STAN ${last ? last.stanford : 0}</span> – <span class="c">${last ? last.cal : 0} CAL</span>`;
  const cm = state.charts["c-momentum"];
  if (cm) cm.setOption({ series: [{}, {}, { markLine: { data: momentumMarks(C(), t) } }] });
  const near = (state.data.feed || []).filter((x) => x.t_min >= t - 30 && x.t_min < t + 15).sort((a, b) => b.likes - a.likes).slice(0, 25);
  $("#feed-sub").textContent = `Most-liked comments from ${tLabel(t - 30)} to ${tLabel(t + 15)}`;
  $("#feed").innerHTML = near.length ? near.map((x) => cmtHTML(x)).join("") : `<div class="empty">${(state.data.feed || []).length ? "No labeled comments in this window" : "Labeled comments appear here once sentiment has run"}</div>`;
}
function stopReplay() { clearInterval(state.timer); state.timer = null; $("#play").textContent = "▶ Replay"; }
$("#scrub").oninput = (e) => { stopReplay(); setCursor(+e.target.value); };
$("#play").onclick = () => {
  if (state.timer) return stopReplay();
  if (state.cursor >= 420) setCursor(-180);
  $("#play").textContent = "❚❚ Pause";
  state.timer = setInterval(() => { if (state.cursor >= 420) return stopReplay(); setCursor(state.cursor + 15); }, 450);
};

/* ---------------- compare view ---------------- */
function renderCompare() {
  const c = C(), seasons = state.compare.seasons;
  $("#multiples").innerHTML = seasons.map((s) => `<div class="mini"><div class="t"><b>${s.year}</b><span><i class="dot ${s.winner}"></i> ${s.winner === "stanford" ? "Stanford" : "Cal"} won</span></div><div class="chart" id="m-${s.year}"></div></div>`).join("");
  seasons.forEach((s) => {
    const tl = s.timeline_game || [];
    if (!tl.some((r) => r.momentum != null)) return emptyChart(`m-${s.year}`, (s.summary?.items_labeled ? "Too few in-game posts from both sides" : "Not labeled yet"));
    const ch = chart(`m-${s.year}`);
    ch.setOption({
      grid: { left: 30, right: 8, top: 8, bottom: 20 },
      tooltip: tooltip(c, { formatter: (ps) => `<b>${s.year} · ${tLabel(ps[0].value[0])}</b><br>Momentum ${sgn(ps[0].value[1])}` }),
      xAxis: { type: "value", min: -180, max: 420, interval: 120, ...baseAxis(c), splitLine: { show: false }, axisLabel: { color: c.ink2, fontSize: 10, formatter: tLabel } },
      yAxis: { type: "value", min: -2, max: 2, interval: 1, ...baseAxis(c), axisLabel: { color: c.ink2, fontSize: 10 } },
      visualMap: { show: false, type: "piecewise", seriesIndex: 0, dimension: 1, pieces: [{ gt: 0, lte: 99, color: c.st }, { gt: -99, lte: 0, color: c.ca }] },
      series: [{ type: "line", data: tl.filter((r) => r.momentum != null).map((r) => [r.t, r.momentum]), smooth: 0.25, showSymbol: false, lineStyle: { width: 2 }, areaStyle: { opacity: 0.16 } },
        guideSeries([{ yAxis: 0, lineStyle: { color: c.ink3, type: "solid", width: 1 }, label: { show: false } }, { xAxis: 0, lineStyle: { color: c.ink3, type: "solid", width: 1 }, label: { show: false } }])],
    });
  });

  const igm = seasons.map((s) => s.summary?.game_window?.momentum ?? null);
  if (igm.every((v) => v == null)) emptyChart("c-yoy", "No labeled sentiment yet");
  else chart("c-yoy").setOption({
    grid: { left: 40, right: 16, top: 16, bottom: 28 },
    tooltip: tooltip(c, { axisPointer: { type: "shadow" }, valueFormatter: (v) => sgn(v) }),
    xAxis: { type: "category", data: seasons.map((s) => `${s.year} (${s.winner === "stanford" ? "STAN" : "CAL"} W)`), ...baseAxis(c), splitLine: { show: false } },
    yAxis: { type: "value", ...baseAxis(c) },
    series: [{ type: "bar", name: "In-game momentum", barWidth: 18, data: igm.map((v) => ({ value: v, itemStyle: { color: v > 0 ? c.st : c.ca, borderRadius: v > 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] } })),
      label: { show: true, position: "top", color: c.ink2, fontSize: 11, formatter: (o) => o.value == null ? "" : sgn(o.value) },
      markLine: { silent: true, symbol: "none", label: { show: false }, data: [{ yAxis: 0, lineStyle: { color: c.ink3, type: "solid", width: 1 } }] } }],
  });

  chart("c-yoy-vol").setOption({
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    tooltip: tooltip(c, { axisPointer: { type: "shadow" }, formatter: (ps) => { const s = seasons[ps[0].dataIndex].summary || {}; return `<b>${seasons[ps[0].dataIndex].year}</b><br>${fmt(s.comments_collected)} comments collected<br>${fmt(s.videos_on_topic)} on-topic videos · ${fmt(s.views)} views`; } }),
    xAxis: { type: "category", data: seasons.map((s) => String(s.year)), ...baseAxis(c), splitLine: { show: false } },
    yAxis: { type: "value", ...baseAxis(c) },
    series: [{ type: "bar", barWidth: 18, data: seasons.map((s) => s.summary?.comments_collected || 0), itemStyle: { color: c.ink2, borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: "top", color: c.ink2, fontSize: 11, formatter: (o) => fmt(o.value) } }],
  });

  const idx = state.index.seasons;
  $("#t-seasons").innerHTML = `<tr><th>Season</th><th>Result</th><th>Venue</th><th class="num">On-topic videos</th><th class="num">Views</th><th class="num">Comments</th><th class="num">Labeled</th><th class="num">Overall mood</th><th class="num">Momentum KO→+4h</th><th class="num">Momentum KO→+48h</th></tr>` +
    seasons.map((s, i) => { const x = idx[i], sm = s.summary || {}; return `<tr><td><b>${s.year}</b></td>
      <td><i class="dot ${x.winner}"></i> ${x.winner === "stanford" ? "Stanford" : "Cal"} ${Math.max(x.stanford, x.cal)}–${Math.min(x.stanford, x.cal)}</td><td>${esc(x.venue)}</td>
      <td class="num">${fmt(sm.videos_on_topic)}</td><td class="num">${fmt(sm.views)}</td><td class="num">${fmt(sm.comments_collected)}</td><td class="num">${fmt(sm.items_labeled)}</td>
      <td class="num">${sgn(sm.overall_sentiment)}</td><td class="num">${sgn(sm.in_game?.momentum)}</td><td class="num">${sgn(sm.game_window?.momentum)}</td></tr>`; }).join("");
}

/* ---------------- Polymarket ---------------- */
const pct = (p) => p == null ? "–" : `${Math.round(100 * p)}%`;
function probChart(id, hist, opts = {}) {
  const c = C();
  if (!hist || hist.length < 2) return emptyChart(id, opts.emptyMsg || "No trading history yet");
  const ch = chart(id);
  const st = hist.map(([t, p]) => [t * 1000, +(100 * p).toFixed(1)]);
  const ca = hist.map(([t, p]) => [t * 1000, +(100 * (1 - p)).toFixed(1)]);
  const marks = [{ yAxis: 50, lineStyle: { color: c.ink3, width: 1, type: "solid" }, label: { show: false } }];
  if (opts.kickoff) marks.push({ xAxis: opts.kickoff, lineStyle: { color: c.accent, width: 1.5, type: "solid" }, label: { formatter: "Kickoff", color: c.ink2, fontSize: 11 } });
  ch.setOption({
    grid: { left: 40, right: 14, top: 14, bottom: 26 },
    tooltip: tooltip(c, { valueFormatter: (v) => v + "%" }),
    xAxis: { type: "time", ...baseAxis(c), splitLine: { show: false }, axisLabel: { color: c.ink2, fontSize: 10, hideOverlap: true,
      formatter: (v) => new Date(v).toLocaleDateString("en-US", { timeZone: "America/Los_Angeles", month: "short", day: "numeric" }) } },
    yAxis: { type: "value", min: 0, max: 100, interval: 25, ...baseAxis(c), axisLabel: { color: c.ink2, fontSize: 10, formatter: "{value}%" } },
    series: [
      { name: "Stanford", type: "line", data: st, showSymbol: false, lineStyle: { width: 2, color: c.st }, itemStyle: { color: c.st },
        markLine: { silent: true, symbol: "none", data: marks } },
      { name: "Cal", type: "line", data: ca, showSymbol: false, lineStyle: { width: 2, color: c.ca }, itemStyle: { color: c.ca } },
    ],
  });
}
function renderMarkets() {
  const m = state.markets;
  if (!m) return;
  const next = m.big_game?.["2026"], last = m.big_game?.["2025"], ng = m.next_game || {};
  if (next) {
    $("#pm-next-title").textContent = `${ng.year || 2026} Big Game · ${next.title}`;
    const ko = ng.kickoff_utc ? new Date(ng.kickoff_utc) : null;
    $("#pm-next-sub").textContent = ko ? `${ko.toLocaleString("en-US", { timeZone: "America/Los_Angeles", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} PT · ${ng.venue || ""}` : "";
    const days = ko ? Math.ceil((ko - Date.now()) / 864e5) : null;
    $("#pm-countdown").textContent = days == null ? "" : days > 1 ? `${days} days to kickoff` : days === 1 ? "Tomorrow" : days === 0 ? "Game day" : "Final";
    $("#pm-odds").innerHTML = `<div class="teams"><div><div class="who">Stanford</div><div class="pct st">${pct(next.stanford_prob)}</div></div>
      <div style="text-align:right"><div class="who">Cal</div><div class="pct ca">${pct(next.cal_prob)}</div></div></div>
      <div class="split" title="Implied win probability"><i style="width:${100 * (next.stanford_prob || 0.5)}%"></i><i style="width:${100 * (next.cal_prob || 0.5)}%"></i></div>
      <div class="meta2">Moneyline · ${next.moneyline_volume ? "$" + fmt(next.moneyline_volume) + " traded" : "no trades yet, so these are the current quotes"}${next.spread ? " · " + esc(next.spread) : ""}</div>`;
    $("#pm-next-link").href = next.url;
    probChart("c-pm-next", next.history_stanford, { emptyMsg: "No trades yet" });
  } else { $("#pm-odds").innerHTML = `<div class="empty">Market unavailable${m.errors?.length ? ": " + esc(m.errors[0]) : ""}</div>`; }

  const wt = m.win_totals || {};
  const lines = [...new Set(["stanford", "cal"].flatMap((k) => (wt[k]?.ladder || []).map((l) => l.line)))].sort((a, b) => a - b);
  if (!lines.length) emptyChart("c-pm-wins", "Win-total markets unavailable");
  else {
    const c = C(), ch = chart("c-pm-wins");
    const val = (k, line) => { const l = (wt[k]?.ladder || []).find((x) => x.line === line); return l ? { value: +(100 * l.yes).toFixed(1), closed: l.closed } : { value: null }; };
    const ser = (k, name, color) => ({ name, type: "bar", barWidth: 8, barGap: "30%",
      data: lines.map((ln) => { const v = val(k, ln); return { value: v.value, closed: v.closed, itemStyle: { color, opacity: v.closed ? 0.45 : 1, borderRadius: [0, 4, 4, 0] } }; }),
      label: { show: true, position: "right", color: c.ink2, fontSize: 10, formatter: (o) => o.value == null ? "" : o.data.closed ? (o.value >= 50 ? "✓ hit" : "✗ out") : o.value + "%" } });
    ch.setOption({
      grid: { left: 70, right: 46, top: 6, bottom: 24 },
      tooltip: tooltip(c, { axisPointer: { type: "shadow" }, formatter: (ps) => `<b>Over ${ps[0].axisValue.replace("> ", "")}</b><br>` + ps.map((p) => `${p.marker}${p.seriesName}: ${p.value == null ? "no market" : p.value + "%"}${p.data.closed ? " (settled)" : ""}`).join("<br>") }),
      xAxis: { type: "value", min: 0, max: 100, ...baseAxis(c), axisLabel: { color: c.ink2, fontSize: 10, formatter: "{value}%" } },
      yAxis: { type: "category", inverse: true, data: lines.map((l) => `> ${l} wins`), ...baseAxis(c), splitLine: { show: false } },
      series: [ser("stanford", "Stanford", c.st), ser("cal", "Cal", c.ca)],
    });
  }
  $("#pm-win-links").innerHTML = ["stanford", "cal"].filter((k) => wt[k]).map((k) => `<a href="${esc(wt[k].url)}" target="_blank" rel="noopener">${k === "stanford" ? "Stanford" : "Cal"} win total ↗</a>`).join("");

  if (last) {
    $("#pm-2025-sub").innerHTML = `Stanford opened at <b>${pct(last.opening_stanford)}</b> and was <b>${pct(last.pregame_stanford)}</b> at kickoff, then won 31–10. $${fmt(last.volume)} traded.`;
    probChart("c-pm-2025", last.history_stanford, { kickoff: last.end ? new Date(last.end).getTime() : null });
    $("#pm-2025-link").innerHTML = `<a href="${esc(last.url)}" target="_blank" rel="noopener">2025 market on Polymarket ↗</a>`;
  }
  $("#pm-foot").textContent = `Prices are Polymarket's implied probabilities, read from its public API (updated ${new Date(m.fetched_at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}, refreshed every 2 minutes). They're shown for context only, not as betting advice, and Polymarket may not be available where you live.`;
}
async function loadMarkets() {
  try {
    const first = !state.markets;
    state.markets = await api("/api/markets"); if (!$("#markets").classList.contains("hidden")) renderMarkets();
    if (first && state.data && state.year !== "compare" && state.markets.big_game?.[state.year]) renderSeason();
  } catch (e) { $("#pm-odds").innerHTML = `<div class="empty">Couldn't reach Polymarket: ${esc(e.message)}</div>`; }
}
function showOdds(open = true) {
  const sec = $("#markets");
  sec.classList.toggle("hidden", !open);
  $("#go-odds").setAttribute("aria-expanded", String(open));
  $("#go-odds .r").textContent = open ? "📈 Hide" : "📈 Polymarket";
  if (open) { renderMarkets(); sec.scrollIntoView({ behavior: "smooth" }); }  // charts need a visible container to size
}
$("#cta-odds").onclick = () => showOdds(true);
$("#close-odds").onclick = () => { showOdds(false); $("#dash").scrollIntoView({ behavior: "smooth" }); };

/* ---------------- hero ---------------- */
function countUp(el, to, fmtFn = fmt, ms = 1100) {
  const t0 = performance.now();
  const step = (t) => { const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3); el.textContent = fmtFn(Math.round(to * e)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function renderHero() {
  const ss = state.index.seasons;
  const sum = (k) => ss.reduce((a, s) => a + (s[k] || 0), 0);
  const judged = ss.filter((s) => s.momentum_48h != null);
  const match = judged.filter((s) => (s.momentum_48h > 0) === (s.winner === "stanford")).length;
  const stats = [
    { l: "Big Games", v: ss.length, f: String },
    { l: "On-topic videos", v: sum("videos_on_topic") },
    { l: "Comments read", v: sum("comments_collected") },
    { l: "Mood picked the winner", v: match, f: (n) => `${n}/${judged.length}` },
  ];
  $("#hero-stats").innerHTML = stats.map((s, i) => `<div class="hs"><div class="v" id="hs-${i}">0</div><div class="l">${s.l}</div></div>`).join("");
  stats.forEach((s, i) => countUp(document.getElementById(`hs-${i}`), s.v, s.f || fmt));
  const items = ss.map((s) => `<span>${s.year} · <b class="${s.winner === "stanford" ? "st" : "ca"}">${s.winner === "stanford" ? "Stanford" : "Cal"}</b> ${Math.max(s.stanford, s.cal)}–${Math.min(s.stanford, s.cal)} · ${esc(s.venue)}${s.momentum_48h != null ? ` · fan mood ${sgn(s.momentum_48h)}` : ""}</span>`).join("<span>🪓</span>");
  $("#ticker").innerHTML = items + "<span>🪓</span>" + items + "<span>🪓</span>";
  const latest = ss[ss.length - 1].year;
  $("#cta-replay").textContent = `▶ Replay ${latest}`;
  $("#cta-replay").onclick = async () => { await select(latest); $("#dash").scrollIntoView({ behavior: "smooth" }); setTimeout(() => !state.timer && $("#play").click(), 700); };
  $("#cta-compare").onclick = async () => { await select("compare"); $("#dash").scrollIntoView({ behavior: "smooth" }); };
}

/* ---------------- rebuild + boot ---------------- */
$("#rebuild").onclick = async () => {
  const b = $("#rebuild"); b.textContent = "Rebuilding…"; b.disabled = true;
  try { await fetch("/api/rebuild", { method: "POST" }).then((r) => { if (!r.ok) throw new Error("rebuild failed"); });
    state.index = await api("/api/index"); state.compare = null; await select(state.year); }
  catch (e) { alert(e.message); }
  b.textContent = "↻ Rebuild"; b.disabled = false;
};

(async function boot() {
  try {
    state.index = await api("/api/index");
  } catch (e) {
    document.querySelector("main").innerHTML = `<div class="callout">No dashboard data yet: ${esc(e.message)}</div>`; return;
  }
  renderHero();
  loadMarkets(); setInterval(loadMarkets, 120000);
  let saved = null; try { saved = localStorage.getItem("bg-year"); } catch (e) {}
  const years = state.index.seasons.map((s) => s.year);
  await select(saved === "compare" ? "compare" : years.includes(+saved) ? +saved : years[years.length - 1]);
})();
