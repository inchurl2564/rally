"use strict";

// ---------- tiny DOM helper (text is always set via textContent: data comes from Wikidata) ----------
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  return el;
}
const $ = (id) => document.getElementById(id);
const slug = (v) => v.replace(/ /g, "-").replace(/\?/g, "");
const fmt = (n) => Math.round(n).toLocaleString("en-US");
const fmtDate = (iso) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const daysBetween = (a, b) => Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 864e5);
const addDays = (iso, n) => new Date(Date.parse(iso + "T00:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const wikidata = (q) => `https://www.wikidata.org/wiki/${encodeURIComponent(q)}`;
const wikipedia = (title) => `https://en.wikipedia.org/wiki/${encodeURIComponent(title)}`;

// Display order for verdict chips; unknown verdicts are appended.
const VERDICT_ORDER = ["unexplained", "common thread", "derivative", "same-creator", "death",
  "anniversary", "weak link", "seasonal", "automated?", "lookup failed"];
const FILTERED = new Set(["seasonal", "automated?"]);

const state = { data: null, labels: {}, verdicts: new Set(), kind: "", q: "", sort: "score" };

// ---------- loading ----------
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function init() {
  let index;
  try {
    index = await getJSON("data/index.json");
  } catch (e) {
    return fail("No data yet. The first scheduled run hasn't finished, or data/index.json is missing.");
  }
  state.labels = index.verdict_labels || {};
  const runs = index.runs || [];
  const sel = $("run");
  for (const r of runs) {
    sel.append(h("option", { value: r.id }, `${fmtDate(r.id)} · ${r.n} revivals`));
  }
  const wanted = new URLSearchParams(location.search).get("run");
  const first = runs.find((r) => r.id === wanted) ? wanted : runs[0] && runs[0].id;
  if (!first) return fail("No runs found.");
  sel.value = first;
  sel.addEventListener("change", () => loadRun(sel.value, true));

  $("q").addEventListener("input", (e) => { state.q = e.target.value.trim().toLowerCase(); renderList(); });
  $("kind").addEventListener("change", (e) => { state.kind = e.target.value; renderList(); });
  $("sort").addEventListener("change", (e) => { state.sort = e.target.value; renderList(); });

  await loadRun(first, false);
}

async function loadRun(id, push) {
  $("status").hidden = false;
  $("status").className = "status";
  $("status").textContent = "Loading…";
  try {
    state.data = await getJSON(`data/runs/${encodeURIComponent(id)}.json`);
  } catch (e) {
    return fail(`Couldn't load the run for ${id}.`);
  }
  if (push) history.replaceState(null, "", `?run=${encodeURIComponent(id)}`);
  state.byQid = Object.fromEntries(state.data.results.map((r) => [r.qid, r]));
  state.verdicts = new Set();
  state.kind = ""; state.q = "";
  $("q").value = "";
  $("status").hidden = true;
  render();
}

function fail(msg) {
  $("status").hidden = false;
  $("status").className = "status error";
  $("status").textContent = msg;
}

// ---------- rendering ----------
function render() {
  const { meta, results } = state.data;
  renderStats(meta, results);
  renderHighlights();
  renderKinds(results);
  renderChips(results);
  renderList();
  const health = meta.health || {};
  const issues = [];
  if (health.pages_skipped) issues.push(`${health.pages_skipped} pages skipped`);
  if (health.lookups_failed) issues.push(`${health.lookups_failed} Wikidata lookups failed`);
  $("generated").textContent = ` Window ${fmtDate(meta.window_start)} – ${fmtDate(meta.window_end)}. Generated ${meta.generated}.` +
    (issues.length ? ` Run issues: ${issues.join(", ")}.` : "");
}

function renderStats(meta, results) {
  const unexplained = results.filter((r) => r.verdict === "unexplained" || r.verdict === "common thread").length;
  const explained = results.filter((r) => !["unexplained", "common thread", "lookup failed"].includes(r.verdict) && !FILTERED.has(r.verdict)).length;
  const items = [
    [fmt(meta.articles_scanned || 0), "trending articles scanned"],
    [fmt(meta.candidates || 0), `works ${meta.min_age}+ years old`],
    [fmt(results.filter((r) => !FILTERED.has(r.verdict)).length), "revivals (3×+ attention)"],
    [fmt(unexplained), `with no recorded cause · ${explained} explained`],
  ];
  const el = $("stats");
  el.replaceChildren(...items.map(([b, t]) => h("div", { class: "stat" }, h("b", {}, b), h("span", {}, t))));
  el.hidden = false;
}

function workLinks(qids, roles) {
  const out = [];
  qids.forEach((q, i) => {
    const w = state.byQid[q];
    if (!w) return;
    if (out.length) out.push(", ");
    out.push(h("a", { href: `#w-${q}`, onclick: (e) => { e.preventDefault(); focusCard(q); } }, w.label));
    const extra = roles ? roles[i] : `${w.kind}, ${w.release_year}`;
    out.push(h("span", { class: "muted" }, ` (${extra})`));
  });
  return out;
}

function renderHighlights() {
  const { shared_triggers = [], common_threads = [] } = state.data;
  const kindName = { death: "Death", derivative: "New release", "same-creator": "New release", anniversary: "Anniversary" };

  const sh = shared_triggers.map((t) => {
    const what = t.type === "death" ? t.text.split(" (")[0] : t.text.split(": ").slice(1).join(": ") || t.text;
    return h("li", {},
      h("div", { class: "when" }, `${kindName[t.type] || "Event"} · ${fmtDate(t.date)}`),
      h("div", {}, h("a", { class: "what", href: wikidata(t.qid) }, what), ` → ${t.works.length} older works spiked`),
      h("div", { class: "works" }, workLinks(t.works)));
  });
  $("shared").replaceChildren(...(sh.length ? sh : [h("li", { class: "empty" }, "None this run.")]));

  const th = common_threads.map((t) => h("li", {},
    h("div", { class: "when" }, `Spikes began around ${fmtDate(t.around)}`),
    h("div", {}, h("a", { class: "what", href: wikidata(t.qid) }, t.name), ` → ${t.works.length} works spiked together`),
    h("div", { class: "works" }, workLinks(t.works.map((w) => w.qid), t.works.map((w) => w.role)))));
  $("threads").replaceChildren(...(th.length ? th : [h("li", { class: "empty" }, "None this run.")]));
  $("highlights").hidden = false;
}

function renderKinds(results) {
  const kinds = [...new Set(results.map((r) => r.kind))].sort();
  $("kind").replaceChildren(h("option", { value: "" }, "All types"), ...kinds.map((k) => h("option", { value: k }, k)));
}

function renderChips(results) {
  const counts = {};
  for (const r of results) counts[r.verdict] = (counts[r.verdict] || 0) + 1;
  const order = [...VERDICT_ORDER, ...Object.keys(counts).filter((v) => !VERDICT_ORDER.includes(v))];
  const chips = order.filter((v) => counts[v]).map((v) => {
    const b = h("button", { class: `chip v-${slug(v)}`, type: "button", "aria-pressed": "false" },
      state.labels[v] || v, h("span", { class: "n" }, counts[v]));
    b.addEventListener("click", () => {
      state.verdicts.has(v) ? state.verdicts.delete(v) : state.verdicts.add(v);
      b.setAttribute("aria-pressed", String(state.verdicts.has(v)));
      renderList();
    });
    return b;
  });
  $("chips").replaceChildren(...chips);
}

function matches(r) {
  if (state.verdicts.size && !state.verdicts.has(r.verdict)) return false;
  if (state.kind && r.kind !== state.kind) return false;
  if (state.q) {
    const hay = [r.label, r.title, r.kind, ...r.triggers.map((t) => t.text)].join(" ").toLowerCase();
    if (!hay.includes(state.q)) return false;
  }
  return true;
}

const SORTS = {
  score: (a, b) => b.score - a.score,
  lift: (a, b) => b.lift - a.lift,
  recent: (a, b) => b.recent_mean - a.recent_mean,
  start: (a, b) => b.spike_start.localeCompare(a.spike_start),
  age: (a, b) => a.release.localeCompare(b.release),
};

function renderList() {
  const all = state.data.results;
  // With no verdict chip selected, filtered-out items (seasonal, likely bots) go to the end.
  const list = all.filter(matches).sort((a, b) => {
    if (!state.verdicts.size) {
      const fa = FILTERED.has(a.verdict), fb = FILTERED.has(b.verdict);
      if (fa !== fb) return fa ? 1 : -1;
    }
    return SORTS[state.sort](a, b);
  });
  $("count").textContent = list.length === all.length ? `(${all.length})` : `(${list.length} of ${all.length})`;
  $("cards").replaceChildren(...(list.length ? list.map(card) : [h("p", { class: "status" }, "Nothing matches these filters.")]));
  $("list-section").hidden = false;
}

function card(r) {
  const v = slug(r.verdict);
  const triggers = r.triggers.length
    ? h("ul", { class: "triggers" }, r.triggers.map((t) => h("li", { class: `v-${slug(t.type)}` },
        t.qid ? h("a", { href: wikidata(t.qid) }, t.text) : t.text,
        h("span", { class: "d" }, fmtDate(t.date)))))
    : h("p", { class: "none" }, "No credited deaths, sequels, adaptations, new releases or anniversaries found near the spike.");

  const checks = [];
  if (r.last_year_lift != null) checks.push(h("span", { class: r.last_year_lift >= 2.5 ? "warn" : "" }, `Same weeks last year: ${r.last_year_lift}× baseline`));
  if (r.desktop_share != null) {
    if (checks.length) checks.push(" · ");
    checks.push(h("span", { class: r.desktop_share >= 0.85 ? "warn" : "" }, `${Math.round(r.desktop_share * 100)}% desktop`));
  }
  if (r.still_elevated) { checks.push(" · "); checks.push("still elevated"); }

  return h("article", { class: `card v-${v}`, id: `w-${r.qid}` },
    h("div", { class: "card-head" },
      h("div", {},
        h("h3", {}, h("a", { href: wikipedia(r.title) }, r.label)),
        h("div", { class: "meta" }, `${r.kind} · ${r.release_year} · ${r.age} years old`)),
      h("span", { class: "badge" }, state.labels[r.verdict] || r.verdict)),
    sparkline(r),
    h("dl", { class: "nums" },
      h("div", {}, h("dt", {}, "Lift"), h("dd", {}, `${r.lift}×`)),
      h("div", {}, h("dt", {}, "Peak"), h("dd", {}, `${r.peak_lift}×`)),
      h("div", {}, h("dt", {}, "Usual views"), h("dd", {}, `${fmt(r.baseline)}/day`)),
      h("div", {}, h("dt", {}, "Spike began"), h("dd", {}, fmtDate(r.spike_start)))),
    triggers,
    checks.length ? h("p", { class: "checks" }, checks) : null);
}

// ---------- sparkline with hover readout ----------
function sparkline(r) {
  const vals = r.spark, n = vals.length, W = n - 1, H = 60;
  const top = Math.max(...vals, r.baseline * 2, 1);
  const lg = (x) => Math.log10(1 + x);
  const y = (x) => H - (lg(x) / lg(top)) * (H - 4);
  const pts = vals.map((x, i) => `${i},${y(x).toFixed(1)}`).join(" ");

  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `Daily views over 12 months for ${r.label}. Usual ${fmt(r.baseline)} a day, peak ${fmt(r.peak)} on ${fmtDate(r.peak_day)}.` });
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
    tip.style.left = `${box.left + (i / W) * box.width}px`;
    tip.style.top = `${box.top}px`;
    tip.hidden = false;
  };
  const leave = () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", move);
  svg.addEventListener("pointerdown", move);
  svg.addEventListener("pointerleave", leave);

  return h("div", { class: "spark" }, svg,
    h("div", { class: "spark-legend" },
      h("span", {}, "Last 12 months, log scale"),
      h("span", {}, h("span", { class: "k" }, "usual"), "  ", h("span", { class: "s" }, "spike began"))));
}

function focusCard(qid) {
  let el = $(`w-${qid}`);
  if (!el) { // hidden by filters: clear them
    state.verdicts.clear(); state.kind = ""; state.q = "";
    $("q").value = ""; $("kind").value = "";
    document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
    renderList();
    el = $(`w-${qid}`);
  }
  if (!el) return;
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 1600);
}

window.addEventListener("scroll", () => { $("tip").hidden = true; }, { passive: true });
init();
