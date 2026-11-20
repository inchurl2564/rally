"use strict";

// ---------- helpers (text always via textContent: data comes from Wikidata/news) ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const SVG = "http://www.w3.org/2000/svg";
const s = (tag, attrs) => { const el = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v); return el; };
const $ = (id) => document.getElementById(id);
const slug = (v) => String(v).replace(/[ /]/g, "-").replace(/[?+]/g, "");
const fmt = (n) => (n == null ? "–" : Math.round(n).toLocaleString("en-US"));
const pct = (x) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const fmtDate = (iso) => iso ? new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "";
const daysBetween = (a, b) => Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 864e5);
const addDays = (iso, n) => new Date(Date.parse(iso + "T00:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const wikidata = (q) => `https://www.wikidata.org/wiki/${encodeURIComponent(q)}`;
const wikipedia = (t) => `https://en.wikipedia.org/wiki/${encodeURIComponent(t)}`;
const ext = (href, ...kids) => h("a", { href, target: "_blank", rel: "noopener" }, ...kids);

// Repo for "report a correction" and "watch" links, worked out from the Pages URL.
const REPO = (() => {
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const seg = location.pathname.split("/").filter(Boolean)[0];
  return m && seg ? `${m[1]}/${seg}` : "inchurl2564/rally";
})();

const VERDICT_ORDER = ["unexplained", "coverage", "common thread", "derivative", "same-creator", "death",
  "anniversary", "weak link", "seasonal", "automated?", "lookup failed"];
const FILTERED = new Set(["seasonal", "automated?"]);
const STAGES = { emerging: "Emerging", peaking: "Peaking", sustained: "Sustained", fading: "Fading" };
const CAUSE_LABEL = {
  death: "a death", legal: "legal news", streaming: "a streaming release", broadcast: "a TV broadcast",
  viral: "social media / viral", "sync placement": "use in a show, ad or trailer", award: "an award",
  "re-release": "a re-release or restoration", "remake/sequel news": "remake or sequel news",
  anniversary: "an anniversary", "auction/sale": "an auction or sale", "sports/event": "a big live event",
  politics: "politics",
};

// ---------- audiences ----------
const PHYSICAL = ["album", "video game", "book", "manga/comic", "film"];
const VIEWS = {
  overview: {
    label: "Overview",
    intro: "Older works whose Wikipedia attention has jumped, with the likely reason. Pick a view above for what matters to you.",
    panels: ["shared", "threads"], preset: {},
  },
  journalists: {
    label: "Journalists",
    intro: "Story leads: big revivals nobody has explained, works that rose together around one person, and causes suggested by news and Wikipedia edits. Newest first.",
    panels: ["threads"], preset: { verdicts: ["unexplained", "coverage", "common thread"], sort: "start" },
    feeds: ["unexplained"],
  },
  rights: {
    label: "Rights holders",
    intro: "Catalog titles gaining attention now, and what's coming. Emerging titles are the time to promote, reissue, pitch to streaming or license. Sorted by strength.",
    panels: ["coming-mini"], preset: { stages: ["emerging", "peaking", "sustained"], hideFiltered: true },
    feeds: ["film-tv", "music", "games", "books", "coming-up"],
  },
  retail: {
    label: "Retail",
    intro: "Physical media, games and books with emerging or sustained demand. Sustained interest is more likely to turn into sales than a one-day spike.",
    panels: ["coming-mini"], preset: { kinds: PHYSICAL, stages: ["emerging", "sustained"], hideFiltered: true, sort: "recent" },
    feeds: ["music", "games", "books"],
  },
  programmers: {
    label: "Programmers",
    intro: "For cinemas, broadcasters and streaming curators: films and TV people are rediscovering, plus anniversaries worth scheduling around.",
    panels: ["anniversaries-mini"], preset: { kinds: ["film", "TV series", "musical"], hideFiltered: true },
    feeds: ["film-tv", "coming-up"],
  },
  research: {
    label: "Researchers",
    intro: "Everything as open data: daily snapshots, a flat CSV and the accuracy record. Data is CC0. Method below.",
    panels: ["downloads", "method"], preset: {},
  },
  coming: { label: "Coming up", page: "coming" },
  accuracy: { label: "Accuracy", page: "accuracy" },
  alerts: { label: "Get alerts", page: "alerts" },
};

const state = { index: null, data: null, labels: {}, accuracy: null, view: "overview",
  verdicts: new Set(), kinds: new Set(), stages: new Set(), hideFiltered: false, q: "", sort: "score" };

// ---------- loading ----------
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function init() {
  try {
    state.index = await getJSON("data/index.json");
  } catch (e) {
    return fail("No data yet. The first scheduled run hasn't finished.");
  }
  state.labels = state.index.verdict_labels || {};
  getJSON("data/accuracy.json").then((a) => { state.accuracy = a; if (state.view === "accuracy") render(); }).catch(() => {});
  const runs = state.index.runs || [];
  const sel = $("run");
  for (const r of runs) sel.append(h("option", { value: r.id }, `${fmtDate(r.id)} · ${r.n} revivals`));
  const params = new URLSearchParams(location.search);
  const first = runs.some((r) => r.id === params.get("run")) ? params.get("run") : runs[0] && runs[0].id;
  if (!first) return fail("No runs found.");
  sel.value = first;
  sel.addEventListener("change", () => loadRun(sel.value));
  state.view = VIEWS[params.get("tab")] ? params.get("tab") : "overview";
  renderTabs();
  await loadRun(first);
}

async function loadRun(id) {
  setStatus("Loading…");
  try {
    state.data = await getJSON(`data/runs/${encodeURIComponent(id)}.json`);
  } catch (e) {
    return fail(`Couldn't load the run for ${id}.`);
  }
  state.byQid = Object.fromEntries(state.data.results.map((r) => [r.qid, r]));
  applyPreset();
  render();
  syncURL();
}

function syncURL() {
  const p = new URLSearchParams();
  if ($("run").value && $("run").value !== (state.index.runs[0] || {}).id) p.set("run", $("run").value);
  if (state.view !== "overview") p.set("tab", state.view);
  const q = p.toString();
  history.replaceState(null, "", (q ? `?${q}` : location.pathname) + location.hash);
}

function setStatus(msg, error) {
  $("view").replaceChildren(h("p", { class: `status${error ? " error" : ""}`, role: "status" }, msg));
}
const fail = (msg) => setStatus(msg, true);

// ---------- tabs ----------
function renderTabs() {
  $("tabs").replaceChildren(...Object.entries(VIEWS).map(([key, v]) =>
    h("button", { type: "button", class: "tab", "aria-current": key === state.view ? "page" : null,
      onclick: () => { state.view = key; applyPreset(); renderTabs(); render(); syncURL(); window.scrollTo({ top: 0 }); } }, v.label)));
}

function applyPreset() {
  const p = VIEWS[state.view].preset || {};
  state.verdicts = new Set(p.verdicts || []);
  state.kinds = new Set(p.kinds || []);
  state.stages = new Set(p.stages || []);
  state.hideFiltered = !!p.hideFiltered;
  state.sort = p.sort || "score";
  state.q = "";
}

// ---------- page ----------
function render() {
  if (!state.data) return;
  const v = VIEWS[state.view];
  const parts = [];
  if (v.page === "coming") parts.push(...comingPage());
  else if (v.page === "accuracy") parts.push(...accuracyPage());
  else if (v.page === "alerts") parts.push(...alertsPage());
  else {
    parts.push(h("p", { class: "intro" }, v.intro));
    if (state.view === "overview") parts.push(stats());
    const panels = (v.panels || []).map(panel).filter(Boolean);
    if (panels.length) parts.push(h("section", { class: `panels n${panels.length}` }, panels));
    if (v.feeds) parts.push(feedStrip(v.feeds));
    parts.push(listSection());
  }
  $("view").replaceChildren(...parts);
  if (!v.page) renderList();
  const { meta } = state.data;
  const health = meta.health || {};
  const issues = [];
  if (health.pages_skipped) issues.push(`${health.pages_skipped} pages skipped`);
  if (health.lookups_failed) issues.push(`${health.lookups_failed} Wikidata lookups failed`);
  if ((health.sources_off || []).length) issues.push(`unavailable: ${health.sources_off.join(", ")}`);
  $("generated").textContent = ` Window ${fmtDate(meta.window_start)} – ${fmtDate(meta.window_end)}. Generated ${meta.generated}.` +
    (issues.length ? ` Run issues: ${issues.join("; ")}.` : "");
}

function stats() {
  const { meta, results } = state.data;
  const live = results.filter((r) => !FILTERED.has(r.verdict));
  const unexplained = live.filter((r) => ["unexplained", "common thread"].includes(r.verdict)).length;
  const early = live.filter((r) => r.early).length;
  const emerging = live.filter((r) => r.stage === "emerging").length;
  const items = [
    [fmt(live.length), "older works with 2.5–3×+ attention"],
    [fmt(emerging), "emerging right now"],
    [fmt(early), "caught early, before the top-1,000 list"],
    [fmt(unexplained), "with no recorded cause"],
  ];
  return h("section", { class: "stats" }, items.map(([b, t]) => h("div", { class: "stat" }, h("b", {}, b), h("span", {}, t))));
}

function workLinks(qids, roles) {
  const out = [];
  qids.forEach((q, i) => {
    const w = state.byQid[q];
    if (!w) return;
    if (out.length) out.push(", ");
    out.push(h("a", { href: `#w-${q}`, onclick: (e) => { e.preventDefault(); focusCard(q); } }, w.label));
    out.push(h("span", { class: "muted" }, ` (${roles ? roles[i] : `${w.kind}, ${w.release_year}`})`));
  });
  return out;
}

function evidenceList(ev, limit = 4) {
  if (!ev || !ev.length) return null;
  return h("ul", { class: "evidence" }, ev.slice(0, limit).map((e) =>
    h("li", {}, h("span", { class: "src" }, e.source), " ", e.url ? ext(e.url, e.text) : e.text,
      h("span", { class: "d" }, fmtDate(e.date)))));
}

function burstNote(b) {
  if (!b) return null;
  return b.burst ? h("span", { class: "burst" }, `Wikipedia editors were busy: ${b.edits} edits around the spike (usually ~${b.usual_per_5_days}).`) : null;
}

function panel(name) {
  const d = state.data;
  if (name === "shared") {
    const kindName = { death: "Death", derivative: "New release", "same-creator": "New release", anniversary: "Anniversary" };
    const items = (d.shared_triggers || []).map((t) => {
      const what = t.type === "death" ? t.text.split(" (")[0] : t.text.split(": ").slice(1).join(": ") || t.text;
      return h("li", {},
        h("div", { class: "when" }, `${kindName[t.type] || "Event"} · ${fmtDate(t.date)}`),
        h("div", {}, ext(wikidata(t.qid), h("b", {}, what)), ` → ${t.works.length} older works spiked`),
        h("div", { class: "works" }, workLinks(t.works)));
    });
    return box("Shared triggers", "One event linked to several older works spiking at once.", items);
  }
  if (name === "threads") {
    const items = (d.common_threads || []).map((t) => h("li", {},
      h("div", { class: "when" }, `Spikes began around ${fmtDate(t.around)}`),
      h("div", {}, ext(wikidata(t.qid), h("b", {}, t.name)), ` → ${t.works.length} works spiked together`),
      h("div", { class: "works" }, workLinks(t.works.map((w) => w.qid), t.works.map((w) => w.role))),
      t.cause ? h("div", { class: "cause" }, `Likely cause: ${CAUSE_LABEL[t.cause] || t.cause}`) : null,
      burstNote(t.edit_burst), evidenceList(t.evidence, 3)));
    return box("Hidden common threads", "Unexplained spikes on works that share a credited person and started rising within a week of each other.", items);
  }
  if (name === "coming-mini") {
    const items = (d.coming_up?.derivatives || []).slice(0, 8).map(derivItem);
    return box("Coming up", "Sequels, adaptations and remakes of older works due soon. Expect renewed interest.", items,
      h("button", { type: "button", class: "more", onclick: () => goto("coming") }, "All upcoming →"));
  }
  if (name === "anniversaries-mini") {
    const items = (d.coming_up?.anniversaries || []).slice(0, 8).map(annItem);
    return box("Anniversaries ahead", "Round-number release anniversaries in the next 60 days, biggest audiences first.", items,
      h("button", { type: "button", class: "more", onclick: () => goto("coming") }, "All upcoming →"));
  }
  if (name === "downloads") {
    const run = $("run").value;
    return h("div", { class: "panel" }, h("h2", {}, "Downloads"),
      h("ul", { class: "plain" },
        h("li", {}, h("a", { href: "data/latest.csv", download: "" }, "latest.csv"), " (spreadsheet of today's revivals)"),
        h("li", {}, h("a", { href: `data/runs/${run}.json` }, `runs/${run}.json`), " (full snapshot with 12-month series, triggers and evidence)"),
        h("li", {}, h("a", { href: "data/index.json" }, "index.json"), " (every archived daily run)"),
        h("li", {}, h("a", { href: "data/accuracy.json" }, "accuracy.json"), " · ", h("a", { href: "data/forecast_checks.json" }, "forecast_checks.json")),
        h("li", {}, ext(`https://github.com/${REPO}`, "Source code and full history on GitHub"))),
      h("p", { class: "sub" }, "Data is derived from CC0 sources. Please cite as “Revival Radar (open data from Wikimedia and Wikidata)”."));
  }
  if (name === "method") return method();
  return null;
}

function box(title, sub, items, extra) {
  return h("div", { class: "panel" }, h("h2", {}, title), h("p", { class: "sub" }, sub),
    h("ul", { class: "events" }, items.length ? items : h("li", { class: "empty" }, "None this run.")), extra || null);
}

function goto(view) { state.view = view; applyPreset(); renderTabs(); render(); syncURL(); window.scrollTo({ top: 0 }); }

function derivItem(c) {
  return h("li", {},
    h("div", { class: "when" }, `${fmtDate(c.date)} · ${c.new_kind}`),
    h("div", {}, ext(wikidata(c.new), h("b", {}, c.new_label)), ` ${c.rel} `,
      ext(wikipedia(c.old_title), c.old_label), h("span", { class: "muted" }, ` (${c.old_kind}, ${c.old_release.slice(0, 4)})`)));
}
function annItem(a) {
  return h("li", {},
    h("div", { class: "when" }, `${fmtDate(a.date)} · ${a.years}th anniversary`),
    h("div", {}, ext(wikipedia(a.title), h("b", {}, a.label)), h("span", { class: "muted" }, ` (${a.kind}, ${a.release.slice(0, 4)})`)),
    a.audience ? h("div", { class: "works muted" }, `Usually ${fmt(a.audience)} Wikipedia views a day`) : null);
}

function feedStrip(names) {
  return h("p", { class: "feedstrip" }, "Follow this view: ",
    names.map((n, i) => [i ? " · " : "", h("a", { href: `feeds/${n}.xml` }, `${n}.xml`)]),
    " · ", h("button", { type: "button", class: "linkish", onclick: () => goto("alerts") }, "email alerts"));
}

// ---------- list ----------
function listSection() {
  const kinds = [...new Set(state.data.results.map((r) => r.kind))].sort();
  const kindSel = h("select", { id: "kind", "aria-label": "Filter by type" },
    h("option", { value: "" }, state.kinds.size > 1 ? "Preset types" : "All types"),
    kinds.map((k) => h("option", { value: k, selected: state.kinds.size === 1 && state.kinds.has(k) ? "" : null }, k)));
  kindSel.addEventListener("change", (e) => { state.kinds = new Set(e.target.value ? [e.target.value] : []); renderList(); });
  const stageSel = h("select", { id: "stage", "aria-label": "Filter by stage" },
    h("option", { value: "" }, state.stages.size > 1 ? "Preset stages" : "All stages"),
    Object.entries(STAGES).map(([k, v]) => h("option", { value: k, selected: state.stages.size === 1 && state.stages.has(k) ? "" : null }, v)));
  stageSel.addEventListener("change", (e) => { state.stages = new Set(e.target.value ? [e.target.value] : []); renderList(); });
  const sortSel = h("select", { id: "sort", "aria-label": "Sort" },
    [["score", "Strongest revival"], ["lift", "Biggest lift"], ["recent", "Most views now"], ["start", "Newest spike"], ["age", "Oldest work"]]
      .map(([k, l]) => h("option", { value: k, selected: state.sort === k ? "" : null }, `Sort: ${l}`)));
  sortSel.addEventListener("change", (e) => { state.sort = e.target.value; renderList(); });
  const q = h("input", { id: "q", type: "search", placeholder: "Search titles, people, causes…", "aria-label": "Search" });
  q.addEventListener("input", (e) => { state.q = e.target.value.trim().toLowerCase(); renderList(); });
  return h("section", { id: "list-section" },
    h("div", { class: "list-head" }, h("h2", {}, "Revivals ", h("span", { id: "count", class: "muted" }))),
    h("div", { class: "filters" }, q, kindSel, stageSel, sortSel),
    h("div", { id: "chips", class: "chips", role: "group", "aria-label": "Filter by verdict" }),
    h("div", { id: "cards", class: "cards" }));
}

function renderChips(results) {
  const counts = {};
  for (const r of results) counts[r.verdict] = (counts[r.verdict] || 0) + 1;
  const order = [...VERDICT_ORDER, ...Object.keys(counts).filter((v) => !VERDICT_ORDER.includes(v))];
  $("chips").replaceChildren(...order.filter((v) => counts[v]).map((v) => {
    const b = h("button", { class: `chip v-${slug(v)}`, type: "button", "aria-pressed": String(state.verdicts.has(v)) },
      state.labels[v] || v, h("span", { class: "n" }, counts[v]));
    b.addEventListener("click", () => {
      state.verdicts.has(v) ? state.verdicts.delete(v) : state.verdicts.add(v);
      b.setAttribute("aria-pressed", String(state.verdicts.has(v)));
      renderList();
    });
    return b;
  }));
}

const SORTS = {
  score: (a, b) => b.score - a.score, lift: (a, b) => Math.max(b.lift, b.lift3 || 0) - Math.max(a.lift, a.lift3 || 0),
  recent: (a, b) => b.recent_mean - a.recent_mean, start: (a, b) => b.spike_start.localeCompare(a.spike_start) || b.score - a.score,
  age: (a, b) => a.release.localeCompare(b.release),
};

function matches(r) {
  if (state.verdicts.size && !state.verdicts.has(r.verdict)) return false;
  if (state.kinds.size && !state.kinds.has(r.kind)) return false;
  if (state.stages.size && !state.stages.has(r.stage)) return false;
  if (state.hideFiltered && FILTERED.has(r.verdict)) return false;
  if (state.q) {
    const hay = [r.label, r.title, r.kind, r.cause, ...r.triggers.map((t) => t.text), ...(r.evidence || []).map((e) => e.text)].join(" ").toLowerCase();
    if (!hay.includes(state.q)) return false;
  }
  return true;
}

function renderList() {
  const all = state.data.results;
  const pool = all.filter((r) => (!state.kinds.size || state.kinds.has(r.kind)) && (!state.stages.size || state.stages.has(r.stage)) && !(state.hideFiltered && FILTERED.has(r.verdict)));
  renderChips(pool);
  const list = all.filter(matches).sort((a, b) => {
    if (!state.verdicts.size) { const fa = FILTERED.has(a.verdict), fb = FILTERED.has(b.verdict); if (fa !== fb) return fa ? 1 : -1; }
    return SORTS[state.sort](a, b);
  });
  $("count").textContent = list.length === all.length ? `(${all.length})` : `(${list.length} of ${all.length})`;
  $("cards").replaceChildren(...(list.length ? list.map(card) : [h("p", { class: "status" }, "Nothing matches these filters.")]));
}

function correctionLink(r) {
  const top = r.triggers[0];
  const body = [`**Work:** ${r.label} (${r.release_year}) ${wikidata(r.qid)}`, `**Run:** ${$("run").value}`,
    `**Radar said:** ${state.labels[r.verdict] || r.verdict}${top ? ` (${top.text})` : ""}${r.cause ? `; likely cause: ${r.cause}` : ""}`,
    "", "**What actually happened (with a link if you have one):**", ""].join("\n");
  const url = `https://github.com/${REPO}/issues/new?labels=feedback&title=${encodeURIComponent(`Correction: ${r.label}`)}&body=${encodeURIComponent(body)}`;
  return ext(url, "Report a correction");
}

function card(r) {
  const triggers = r.triggers.length
    ? h("ul", { class: "triggers" }, r.triggers.map((t) => h("li", { class: `v-${slug(t.type)}` },
        t.qid ? ext(wikidata(t.qid), t.text) : t.text, h("span", { class: "d" }, fmtDate(t.date)))))
    : r.cause ? null
    : h("p", { class: "none" }, "No credited deaths, sequels, adaptations, new releases or anniversaries found near the spike.");

  const checks = [];
  const add = (node) => { if (checks.length) checks.push(" · "); checks.push(node); };
  if (r.last_year_lift != null) add(h("span", { class: r.last_year_lift >= 2.5 ? "warn" : "" }, `Same weeks last year: ${r.last_year_lift}×`));
  if (r.desktop_share != null) add(h("span", { class: r.desktop_share >= 0.85 ? "warn" : "" }, `${Math.round(r.desktop_share * 100)}% desktop`));
  if (r.corroborated === true) add(h("span", { class: "ok" }, "✓ backed by news/edits"));
  if (r.corroborated === false) add(h("span", { class: "warn" }, "Evidence doesn't mention this trigger"));

  return h("article", { class: `card v-${slug(r.verdict)}`, id: `w-${r.qid}` },
    h("div", { class: "card-head" },
      h("div", {},
        h("h3", {}, ext(wikipedia(r.title), r.label)),
        h("div", { class: "meta" }, `${r.kind} · ${r.release_year} · ${r.age} years old`)),
      h("div", { class: "badges" },
        h("span", { class: "badge" }, state.labels[r.verdict] || r.verdict),
        r.stage ? h("span", { class: `stage s-${r.stage}` }, STAGES[r.stage] || r.stage) : null,
        r.early ? h("span", { class: "stage s-early", title: "Spotted by the watchlist before reaching Wikipedia's top 1,000" }, "Caught early") : null)),
    sparkline(r),
    h("dl", { class: "nums" },
      h("div", {}, h("dt", {}, "14-day lift"), h("dd", {}, `${r.lift}×`)),
      h("div", {}, h("dt", {}, "Last 3 days"), h("dd", {}, `${r.lift3 ?? "–"}×`)),
      h("div", {}, h("dt", {}, "Usual views"), h("dd", {}, `${fmt(r.baseline)}/day`)),
      h("div", {}, h("dt", {}, "Spike began"), h("dd", {}, fmtDate(r.spike_start)))),
    r.cause ? h("p", { class: "cause" }, `Likely cause: ${CAUSE_LABEL[r.cause] || r.cause}`) : null,
    triggers,
    burstNote(r.edit_burst) ? h("p", { class: "note" }, burstNote(r.edit_burst)) : null,
    r.evidence && r.evidence.length ? h("details", { class: "ev" }, h("summary", {}, `Evidence (${r.evidence.length})`), evidenceList(r.evidence, 8)) : null,
    h("p", { class: "checks" }, checks, checks.length ? " · " : "", correctionLink(r)));
}

// ---------- sparkline ----------
function sparkline(r) {
  const vals = r.spark, n = vals.length, W = n - 1, H = 60;
  const top = Math.max(...vals, r.baseline * 2, 1);
  const lg = (x) => Math.log10(1 + x);
  const y = (x) => H - (lg(x) / lg(top)) * (H - 4);
  const pts = vals.map((x, i) => `${i},${y(x).toFixed(1)}`).join(" ");
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `Daily views over 12 months for ${r.label}. Usually ${fmt(r.baseline)} a day, peak ${fmt(r.peak)} on ${fmtDate(r.peak_day)}.` });
  svg.append(s("polygon", { class: "area", points: `0,${H} ${pts} ${W},${H}` }));
  svg.append(s("line", { class: "base", x1: 0, x2: W, y1: y(r.baseline), y2: y(r.baseline) }));
  const si = daysBetween(r.spark_start, r.spike_start);
  if (si >= 0 && si < n) svg.append(s("line", { class: "start", x1: si, x2: si, y1: 0, y2: H }));
  svg.append(s("polyline", { class: "line", points: pts }));
  const cursor = s("line", { class: "cursor", x1: 0, x2: 0, y1: 0, y2: H, visibility: "hidden" });
  svg.append(cursor);
  const tip = $("tip");
  const move = (e) => {
    const box = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - box.left) / box.width) * W)));
    cursor.setAttribute("x1", i); cursor.setAttribute("x2", i); cursor.setAttribute("visibility", "visible");
    tip.textContent = `${fmtDate(addDays(r.spark_start, i))} · ${fmt(vals[i])} views`;
    tip.style.left = `${box.left + (i / W) * box.width}px`; tip.style.top = `${box.top}px`; tip.hidden = false;
  };
  const leave = () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerdown", move); svg.addEventListener("pointerleave", leave);
  return h("div", { class: "spark" }, svg, h("div", { class: "spark-legend" },
    h("span", {}, "Last 12 months, log scale"), h("span", {}, h("span", { class: "k" }, "usual"), "  ", h("span", { class: "s" }, "spike began"))));
}

function focusCard(qid) {
  let el = $(`w-${qid}`);
  if (!el) {
    state.verdicts.clear(); state.kinds.clear(); state.stages.clear(); state.hideFiltered = false; state.q = "";
    if ($("q")) $("q").value = "";
    renderList();
    el = $(`w-${qid}`);
  }
  if (!el) return;
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600);
}

// ---------- other pages ----------
function comingPage() {
  const cu = state.data.coming_up || { derivatives: [], anniversaries: [] };
  const dRows = cu.derivatives.map((c) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(c.date)),
    h("td", {}, ext(wikidata(c.new), c.new_label), h("div", { class: "muted small" }, c.new_kind)),
    h("td", {}, c.rel),
    h("td", {}, ext(wikipedia(c.old_title), c.old_label), h("div", { class: "muted small" }, `${c.old_kind}, ${c.old_release.slice(0, 4)}`))));
  const aRows = cu.anniversaries.map((a) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(a.date)),
    h("td", {}, ext(wikipedia(a.title), a.label), h("div", { class: "muted small" }, `${a.kind}, ${a.release.slice(0, 4)}`)),
    h("td", { class: "num" }, `${a.years}th`),
    h("td", { class: "num" }, a.audience ? fmt(a.audience) : "–")));
  return [
    h("p", { class: "intro" }, "What's likely to bring older works back: sequels, adaptations, remakes and new series entries due soon, plus round-number anniversaries. Use it to plan reissues, stock, promotions and programming before interest arrives. The Accuracy tab tracks how often these forecasts come true."),
    h("section", { class: "panel" }, h("h2", {}, "Upcoming sequels, adaptations and remakes"),
      h("p", { class: "sub" }, "Due in the next ~5 months, linked to a notable older work. From Wikidata; release dates can slip."),
      table(["Due", "New work", "Relation", "Older work likely to revive"], dRows)),
    h("section", { class: "panel" }, h("h2", {}, "Anniversaries in the next 60 days"),
      h("p", { class: "sub" }, "Ranked by the work's usual daily Wikipedia audience. Works whose exact release day isn't known are left out."),
      table(["Date", "Work", "Years", "Usual views/day"], aRows)),
  ];
}

function table(head, rows) {
  if (!rows.length) return h("p", { class: "empty" }, "Nothing yet. This list fills in once the daily run has built its watchlist.");
  return h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, head.map((x) => h("th", {}, x)))), h("tbody", {}, rows)));
}

function accuracyPage() {
  const a = state.accuracy;
  if (!a) return [h("p", { class: "status" }, "No accuracy data yet. It builds up as daily runs accumulate.")];
  const f = a.forecasts || {}, c = a.corroboration || {}, p = a.persistence || {}, rr = a.reader_reports || {};
  const stat = (big, label, sub) => h("div", { class: "stat" }, h("b", {}, big), h("span", {}, label), sub ? h("small", {}, sub) : null);
  const recent = (f.recent || []).map((x) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(x.date)), h("td", {}, x.label), h("td", {}, x.detail),
    h("td", { class: "num" }, `${x.ratio}×`), h("td", {}, x.hit ? h("span", { class: "ok" }, "Came true") : h("span", { class: "muted" }, "No rise"))));
  const corrRows = Object.entries(c).filter(([k]) => k !== "all").map(([k, v]) => h("tr", {},
    h("td", {}, state.labels[k] || k), h("td", { class: "num" }, v.checked), h("td", { class: "num" }, pct(v.rate))));
  return [
    h("p", { class: "intro" }, "How often the radar is right, measured openly and updated daily. Small numbers early on: treat rates as provisional until there are dozens of checks."),
    h("section", { class: "stats" },
      stat(pct(f.all?.rate), "forecasts came true", `${f.all?.hits ?? 0} of ${f.all?.checked ?? 0} checked`),
      stat(pct(c.all?.rate), "explanations backed by news/edits", `${c.all?.agree ?? 0} of ${c.all?.checked ?? 0} with evidence`),
      stat(p.median_days == null ? "–" : `${p.median_days} days`, "typical time on the radar", p.share_over_7_days == null ? "" : `${pct(p.share_over_7_days)} last over a week`),
      stat(`${rr.correct ?? 0} / ${rr.wrong ?? 0}`, "reader reports: right / wrong", `${rr.open ?? 0} awaiting review`)),
    h("section", { class: "panel" }, h("h2", {}, "Forecast checks"),
      h("p", { class: "sub" }, "A forecast came true if the older work's attention reached 2× its usual level within a week of the date."),
      table(["Date", "Work", "Forecast", "Peak vs usual", "Result"], recent)),
    h("section", { class: "panel" }, h("h2", {}, "Explanations vs. independent evidence"),
      h("p", { class: "sub" }, "For explained spikes, whether Wikipedia edit summaries or news from the same days mention the trigger."),
      table(["Trigger type", "Checked", "Backed by evidence"], corrRows)),
    h("section", { class: "panel" }, h("h2", {}, "Help check it"),
      h("p", {}, "Every card has a ", h("b", {}, "Report a correction"), " link that opens a pre-filled GitHub issue. Maintainers label reports ",
        h("code", {}, "verified-correct"), " or ", h("code", {}, "verified-wrong"), " and the counts above update the next day."),
      h("p", {}, ext(`https://github.com/${REPO}/issues?q=label%3Afeedback`, "See all reports →"))),
  ];
}

function alertsPage() {
  const base = new URL(".", location.href).href;
  const feeds = [
    ["all", "Everything new: revivals, shared triggers, common threads, forecasts"],
    ["unexplained", "Journalists: unexplained spikes, common threads and causes found in coverage"],
    ["coming-up", "Rights holders, retail, programmers: upcoming sequels, adaptations and remakes"],
    ["film-tv", "Film & TV"], ["music", "Songs, albums and musicals"], ["games", "Video games"], ["books", "Books, manga and comics"],
  ];
  return [
    h("p", { class: "intro" }, "Get new findings without checking the site. Every alert is a new finding since the previous day."),
    h("section", { class: "panel" }, h("h2", {}, "Daily email digest"),
      h("ol", {},
        h("li", {}, "Sign in to GitHub (free) and open ", ext(`https://github.com/${REPO}`, `github.com/${REPO}`), "."),
        h("li", {}, "Click ", h("b", {}, "Watch"), " → ", h("b", {}, "Custom"), " → tick ", h("b", {}, "Issues"), " → ", h("b", {}, "Apply"), "."),
        h("li", {}, "Each morning's digest is posted as an issue, so it arrives in your inbox.")),
      h("p", { class: "sub" }, "No GitHub account? Paste any feed below into a free RSS-to-email service.")),
    h("section", { class: "panel" }, h("h2", {}, "Feeds (Atom/RSS)"),
      h("p", { class: "sub" }, "Paste a link into any feed reader (Feedly, Inoreader, NetNewsWire, Outlook, Slack's RSS app…)."),
      h("ul", { class: "plain feeds" }, feeds.map(([n, d]) => h("li", {},
        h("a", { href: `feeds/${n}.xml` }, `${n}.xml`),
        h("button", { type: "button", class: "copy", onclick: (e) => copy(`${base}feeds/${n}.xml`, e.target) }, "Copy link"),
        h("div", { class: "muted small" }, d))))),
    h("section", { class: "panel" }, h("h2", {}, "Raw data"),
      h("p", {}, "Build your own alerts from ", h("a", { href: "data/latest.json" }, "latest.json"), " or ", h("a", { href: "data/latest.csv" }, "latest.csv"),
        ", which are refreshed daily at about 04:30 UTC.")),
  ];
}

function copy(text, btn) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
    () => { btn.textContent = "Copied"; setTimeout(() => (btn.textContent = "Copy link"), 1500); },
    () => { window.prompt("Copy this link:", text); });
}

function method() {
  return h("details", { class: "panel about", open: "" }, h("summary", {}, "How it works"),
    h("ol", {},
      h("li", {}, h("b", {}, "Watch."), " Every day, read Wikimedia's bulk pageview file and track ~35,000 notable older works (10+ language editions, released 10+ years ago). Also scan English Wikipedia's daily top 1,000."),
      h("li", {}, h("b", {}, "Measure."), " Compare each work's last 3 and 14 days with its median over the previous ~11 months. 3× over 14 days, or 2.5× over 3 days, counts. Stages: emerging (began in the last 4 days), peaking, sustained (elevated 10+ days), fading."),
      h("li", {}, h("b", {}, "Explain."), " Search Wikidata near the spike start for deaths of credited people, sequels, adaptations, remakes, new series entries (released or upcoming), new work by the same creator, and anniversaries. For spikes it can't explain, read Wikipedia edit summaries, edit bursts and GDELT news headlines from the same days."),
      h("li", {}, h("b", {}, "Connect."), " Group spikes by a shared event, and unexplained spikes by a shared person with the same timing."),
      h("li", {}, h("b", {}, "Filter."), " Set aside items that were also up this time last year (seasonal) and spikes that are almost all desktop traffic (likely bots)."),
      h("li", {}, h("b", {}, "Forecast and check."), " List upcoming sequels/adaptations and anniversaries for older works, then check later whether attention actually rose.")),
    h("p", {}, h("b", {}, "Limits. "), "Wikipedia attention isn't sales or streams. Wikidata is volunteer-edited and can be wrong or incomplete. News and edit-history lookups are best-effort and sometimes rate-limited. Two-work threads can be coincidence. Verify before publishing or acting."));
}

window.addEventListener("scroll", () => { $("tip").hidden = true; }, { passive: true });
init();
