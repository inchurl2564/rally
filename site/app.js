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
const fmtDate = (iso, opts) => iso ? new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", ...(opts || { year: "numeric" }), timeZone: "UTC" }) : "";
const short = (iso) => fmtDate(iso, {});
const daysBetween = (a, b) => Math.round((Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 864e5);
const addDays = (iso, n) => new Date(Date.parse(iso + "T00:00:00Z") + n * 864e5).toISOString().slice(0, 10);
const wikidata = (q) => `https://www.wikidata.org/wiki/${encodeURIComponent(q)}`;
const wikipedia = (t) => `https://en.wikipedia.org/wiki/${encodeURIComponent(t)}`;
const ext = (href, ...kids) => h("a", { href, target: "_blank", rel: "noopener" }, ...kids);
const hash = (str) => [...String(str)].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);

const REPO = (() => {
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const seg = location.pathname.split("/").filter(Boolean)[0];
  return m && seg ? `${m[1]}/${seg}` : "inchurl2564/rally";
})();

const FILTERED = new Set(["seasonal", "automated?"]);
const MYSTERY = new Set(["unexplained", "weak link", "lookup failed"]);
const STAGES = { emerging: "Just starting", peaking: "At its peak", sustained: "Still going", fading: "Cooling off" };
const NOUN = { film: "film", "TV series": "show", song: "song", album: "album", "video game": "game", book: "book", "manga/comic": "comic", musical: "musical" };
const PLURAL = { film: "films", show: "shows", song: "songs", album: "albums", game: "games", book: "books", comic: "comics", musical: "musicals" };
const noun = (k) => NOUN[k] || "work";
const CAUSE = {
  death: ["A death in the news", "looks like the reason"], legal: ["Legal headlines", "pulled it back into view"],
  streaming: ["A streaming debut", "looks like the reason"], broadcast: ["A TV airing", "looks like the reason"],
  viral: ["The internet", "is to blame: it's going viral"], "sync placement": ["A placement in a show, ad or trailer", "looks like the reason"],
  award: ["Awards buzz", "looks like the reason"], "re-release": ["A re-release or restoration", "looks like the reason"],
  "remake/sequel news": ["Remake or sequel news", "looks like the reason"], anniversary: ["An anniversary", "looks like the reason"],
  "auction/sale": ["A big auction or sale", "looks like the reason"], "sports/event": ["A big live event", "looks like the reason"],
  politics: ["Politics", "pulled it back into view"],
};
const causeSentence = (c) => (CAUSE[c] ? `${CAUSE[c][0]} ${CAUSE[c][1]}` : `Coverage points to ${c}`);
const REL = { "adaptation/based on it": "a new adaptation", sequel: "the sequel", "derivative work": "a spin-off",
  "remake/new version": "the remake", "new entry in same series": "the new entry in the series" };

function mult(r) {
  const m = Math.max(r.lift || 0, r.lift3 || 0);
  return m >= 10 ? `${Math.round(m)}×` : `${m.toFixed(1).replace(/\.0$/, "")}×`;
}

// ---------- the editorial voice: turn a finding into a story ----------
function story(r) {
  const w = r.label, yr = r.release_year, n = noun(r.kind), x = mult(r);
  const t = r.triggers && r.triggers[0];
  const upcoming = t && /\(upcoming\)$/.test(t.text);
  const strip = (str) => str.replace(/ \((upcoming|attention rose before release)\)$/, "");
  const since = `since ${short(r.spike_start)}`;
  switch (r.verdict) {
    case "death": {
      const who = t.text.split(" (")[0], role = (t.text.match(/\(([^)]+)\)/) || [])[1];
      return { kicker: "In Memoriam", hed: `Remembering ${who}: ${w} is back`,
        dek: `${who}${role ? `, ${role} on the ${yr} ${n},` : ""} died on ${fmtDate(t.date)}. Since then ${x} as many people as usual have been looking it up.` };
    }
    case "derivative": {
      const [rel, ...rest] = t.text.split(": "), nw = strip(rest.join(": "));
      const what = REL[rel] || "a new release";
      return upcoming
        ? { kicker: "Homework", hed: `Everyone's catching up on ${w} before ${nw} arrives`,
            dek: `${nw}, ${what}, is due ${fmtDate(t.date)}. Interest in the ${yr} ${n} is already ${x} its usual level.` }
        : { kicker: "The Sequel Effect", hed: `${nw} sends fans back to ${w}`,
            dek: `${nw}, ${what}, came out ${fmtDate(t.date)}, and the ${yr} ${n} is drawing ${x} its usual audience.` };
    }
    case "same-creator": {
      const m = t.text.match(/^new work by (.+?): (.+)$/) || [];
      const who = m[1] || "Its creator", nw = strip(m[2] || "a new release");
      return { kicker: "Back Catalog", hed: upcoming ? `${who}'s next release has fans revisiting ${w}` : `${who}'s new release sends fans back to ${w}`,
        dek: `${nw} ${upcoming ? `is due ${fmtDate(t.date)}` : `came out ${fmtDate(t.date)}`}. The ${yr} ${n} is drawing ${x} its usual audience.` };
    }
    case "anniversary": {
      const yrs = (t.text.match(/^(\d+)/) || [])[1];
      return { kicker: "Happy Birthday", hed: `${w} turns ${yrs}`,
        dek: `The ${n} came out on ${fmtDate(r.release)}, and people are marking the occasion: ${x} its usual audience.` };
    }
    case "common thread": {
      const who = t.text.split(" (")[0], k = (t.text.match(/credited on (\d+)/) || [])[1];
      return { kicker: "Six Degrees", hed: `${w} is one of ${k} ${who} titles spiking at once`,
        dek: `They all started rising around ${short(t.date)}. Something is going on with ${who}, but we can't say what yet.` };
    }
    case "ripple": {
      const rp = r.ripple, jumped = `${rp.name}'s own Wikipedia page jumped ${rp.ratio}× on ${short(rp.date)} (${fmt(rp.peak)} readers in a day)`;
      const hed = rp.relation === "sequel or adaptation" ? `${rp.name} is drawing crowds, and fans are going back to ${w}`
        : ["franchise", "series", "character"].includes(rp.relation) ? `${rp.name} is in the news, and ${w} is along for the ride`
        : rp.relation === "source material" ? `${rp.name} is in the news, and so is ${w}`
        : `${rp.name} is in the news, and ${w} is back`;
      return { kicker: "The Ripple Effect", hed,
        dek: `${jumped}, right as interest in the ${yr} ${n} took off.${["franchise", "series", "character", "sequel or adaptation", "source material"].includes(rp.relation) ? "" : ` Something happened involving ${rp.name}.`}` };
    }
    case "editor":
      return { kicker: "Explained", hed: `Why ${w} is back`, dek: `${r.editor_note.text} The ${yr} ${n} is drawing ${x} its usual audience.` };
    case "coverage":
      return { kicker: "Explained", hed: `Why ${w} is suddenly everywhere`,
        dek: `${causeSentence(r.cause)}, based on news and Wikipedia edits from the days interest jumped. The ${yr} ${n} is at ${x} its usual audience.` };
    case "seasonal":
      return { kicker: "Right on Schedule", hed: `It's that time of year for ${w}`,
        dek: `Interest in the ${yr} ${n} jumps around now every year. Same weeks last year: ${r.last_year_lift}× usual.` };
    case "automated?":
      return { kicker: "Probably Bots", hed: `${w}'s spike looks automated`,
        dek: `Almost all of the extra traffic comes from desktop computers, a typical sign of bots rather than people.` };
    default: {
      const heds = [
        `Nobody can explain why people are suddenly looking up ${w}`,
        `${w} is having a moment. Nobody knows why.`,
        `Why is everyone suddenly reading about ${w}?`,
        `The internet rediscovered ${w}, and we can't figure out why`,
      ];
      return { kicker: "Mystery", hed: heds[hash(r.qid) % heds.length],
        dek: `The ${yr} ${n} has drawn ${x} its usual audience ${since}, with no sequel, death, anniversary or news story we can find.` };
    }
  }
}

function sharedStory(t) {
  const works = t.works.map((q) => state.byQid[q]).filter(Boolean);
  const kinds = [...new Set(works.map((w) => noun(w.kind)))];
  const what = kinds.length === 1 ? `${PLURAL[kinds[0]] || "works"}` : "favorites";
  if (t.type === "death") {
    const who = t.text.split(" (")[0];
    return { kicker: "In Memoriam", hed: `Remembering ${who}: ${works.length} old ${what} are back`,
      dek: `${who} died on ${fmtDate(t.date)}, and fans went back to the work.` };
  }
  const nw = t.text.split(": ").slice(1).join(": ").replace(/ \((upcoming|attention rose before release)\)$/, "") || t.text;
  const up = /\(upcoming\)$/.test(t.text);
  return { kicker: up ? "Homework" : "The Sequel Effect",
    hed: up ? `${nw} lands ${short(t.date)}, and fans are revisiting the old ${what}` : `${nw} is sending fans back to the old ${what}`,
    dek: `${works.length} earlier titles are drawing far more readers than usual.` };
}

function sourceLine(note) {
  if (!note || !note.source) return null;
  let host = note.source;
  try { host = new URL(note.source).hostname.replace(/^www\./, ""); } catch (e) { /* keep raw */ }
  return h("p", { class: "source" }, "Editor's note · Source: ", ext(note.source, host));
}

function threadStory(t) {
  const roles = [...new Set(t.works.map((w) => w.role))];
  const how = roles.length === 1 && roles[0] === "cast member" ? "starring"
    : roles.length === 1 && roles[0] === "director" ? "directed by"
    : roles.length === 1 && roles[0] === "performer" ? "by" : "featuring";
  const pj = t.person_jump;
  const cause = t.editor_note ? t.editor_note.text
    : pj ? `${t.name}'s own Wikipedia page jumped ${pj.ratio}× on ${short(pj.date)} (${fmt(pj.peak)} readers in a day), so this is about ${t.name}.${t.cause ? ` ${causeSentence(t.cause)}.` : ""}`
    : t.cause ? `${causeSentence(t.cause)}, based on news and Wikipedia edits.` : "Wikidata doesn't record why. Maybe you know?";
  return { kicker: "Six Degrees", hed: `Something's going on with ${t.name}`,
    dek: `${t.works.length} titles ${how} ${t.name} all started spiking around ${short(t.around)}. ${cause}` };
}

// ---------- media: free Commons image, or a typographic tile ----------
function media(image, name, year, kind, width = 640) {
  const tile = () => h("div", { class: `tile k-${slug(kind || "film")}` }, h("span", { class: "yr" }, [year, kind].filter(Boolean).join(" · ")), h("span", { class: "nm" }, name));
  if (!image) return h("div", { class: "media" }, tile());
  const img = h("img", { src: `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(image)}?width=${width}`,
    alt: name, loading: "lazy", decoding: "async" });
  const wrap = h("div", { class: "media" }, img,
    ext(`https://commons.wikimedia.org/wiki/File:${encodeURIComponent(image)}`, h("span", { class: "credit" }, "Image: Wikimedia Commons")));
  img.addEventListener("error", () => wrap.replaceChildren(tile()));
  return wrap;
}

// ---------- views ----------
const PHYSICAL = ["album", "video game", "book", "manga/comic", "film"];
const VIEWS = {
  today: { label: "Today", page: "today" },
  mysteries: { label: "Mysteries", page: "mysteries" },
  coming: { label: "Coming Soon", page: "coming" },
  accuracy: { label: "Track Record", page: "accuracy" },
  alerts: { label: "Get Alerts", page: "alerts" },
  // professional views
  journalists: { pro: true, label: "Journalists",
    intro: "Story leads: big revivals nobody has explained, works that rose together around one person, and causes suggested by news and Wikipedia edits.",
    panels: ["threads"], preset: { verdicts: ["unexplained", "coverage", "common thread", "weak link"], sort: "start" }, feeds: ["unexplained"] },
  rights: { pro: true, label: "Rights holders",
    intro: "Catalog titles gaining attention now, and what's coming. Titles that are just starting to rise are the ones to promote, reissue, pitch or license.",
    panels: ["coming-mini"], preset: { stages: ["emerging", "peaking", "sustained"], hideFiltered: true }, feeds: ["film-tv", "music", "games", "books", "coming-up"] },
  retail: { pro: true, label: "Retail",
    intro: "Physical media, games and books with fresh or lasting demand. Lasting interest is more likely to turn into sales than a one-day spike.",
    panels: ["coming-mini"], preset: { kinds: PHYSICAL, stages: ["emerging", "sustained"], hideFiltered: true, sort: "recent" }, feeds: ["music", "games", "books"] },
  programmers: { pro: true, label: "Programmers",
    intro: "For cinemas, broadcasters and streaming curators: films and TV people are rediscovering, plus anniversaries worth scheduling around.",
    panels: ["anniversaries-mini"], preset: { kinds: ["film", "TV series", "musical"], hideFiltered: true }, feeds: ["film-tv", "coming-up"] },
  research: { pro: true, label: "Researchers & data",
    intro: "Everything as open data: daily snapshots, a flat CSV and the accuracy record. CC0, with the method below.",
    panels: ["downloads", "method"], preset: {} },
};

const state = { index: null, data: null, labels: {}, accuracy: null, view: "today", proOpen: false,
  verdicts: new Set(), kinds: new Set(), stages: new Set(), hideFiltered: false, q: "", sort: "score" };

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function init() {
  $("today").textContent = new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  try { state.index = await getJSON("data/index.json"); }
  catch (e) { return fail("No data yet. The first daily run hasn't finished."); }
  state.labels = state.index.verdict_labels || {};
  getJSON("data/accuracy.json").then((a) => { state.accuracy = a; if (state.view === "accuracy") render(); }).catch(() => {});
  const runs = state.index.runs || [];
  const sel = $("run");
  runs.forEach((r, i) => sel.append(h("option", { value: r.id }, i === 0 ? `Latest edition · ${short(r.id)}` : `Edition of ${fmtDate(r.id)}`)));
  const params = new URLSearchParams(location.search);
  const first = runs.some((r) => r.id === params.get("run")) ? params.get("run") : runs[0] && runs[0].id;
  if (!first) return fail("No editions yet.");
  sel.value = first;
  sel.addEventListener("change", () => loadRun(sel.value));
  const tab = params.get("tab");
  state.view = VIEWS[tab] ? tab : tab === "overview" ? "today" : "today";
  state.proOpen = !!VIEWS[state.view].pro;
  renderTabs();
  await loadRun(first);
}

async function loadRun(id) {
  setStatus("Loading…");
  try { state.data = await getJSON(`data/runs/${encodeURIComponent(id)}.json`); }
  catch (e) { return fail(`Couldn't load the edition for ${id}.`); }
  state.byQid = Object.fromEntries(state.data.results.map((r) => [r.qid, r]));
  applyPreset();
  render();
  syncURL();
  if (location.hash.startsWith("#w-")) setTimeout(() => focusCard(location.hash.slice(3)), 50);
}

function syncURL() {
  const p = new URLSearchParams();
  if ($("run").value && $("run").value !== (state.index.runs[0] || {}).id) p.set("run", $("run").value);
  if (state.view !== "today") p.set("tab", state.view);
  const q = p.toString();
  history.replaceState(null, "", (q ? `?${q}` : location.pathname) + location.hash);
}
function setStatus(msg, error) { $("view").replaceChildren(h("p", { class: `status${error ? " error" : ""}`, role: "status" }, msg)); }
const fail = (msg) => setStatus(msg, true);

function renderTabs() {
  const tab = (key) => h("button", { type: "button", class: "tab", "aria-current": key === state.view ? "page" : null, onclick: () => goto(key) }, VIEWS[key].label);
  const pros = Object.keys(VIEWS).filter((k) => VIEWS[k].pro);
  $("tabs").replaceChildren(...Object.keys(VIEWS).filter((k) => !VIEWS[k].pro).map(tab),
    h("button", { type: "button", class: "tab toggle", "aria-expanded": String(state.proOpen), "aria-controls": "protabs",
      onclick: () => { state.proOpen = !state.proOpen; renderTabs(); } }, state.proOpen ? "For Pros ▴" : "For Pros ▾"));
  $("protabs").replaceChildren(...pros.map(tab));
  $("protabs").hidden = !state.proOpen;
}

function goto(view) {
  state.view = view;
  if (VIEWS[view].pro) state.proOpen = true;
  applyPreset(); renderTabs(); render(); syncURL(); window.scrollTo({ top: 0 });
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

function render() {
  if (!state.data) return;
  const v = VIEWS[state.view];
  const page = { today: todayPage, mysteries: mysteriesPage, coming: comingPage, accuracy: accuracyPage, alerts: alertsPage }[v.page];
  $("view").replaceChildren(...(page ? page() : proPage(v)));
  if ($("cards")) renderList();
  const { meta } = state.data, health = meta.health || {};
  const issues = [];
  if (health.pages_skipped) issues.push(`${health.pages_skipped} pages skipped`);
  if (health.lookups_failed) issues.push(`${health.lookups_failed} Wikidata lookups failed`);
  if ((health.sources_off || []).length) issues.push(`unavailable: ${health.sources_off.join(", ")}`);
  $("generated").textContent = `This edition covers ${fmtDate(meta.window_start)} – ${fmtDate(meta.window_end)} and was generated ${meta.generated}.` +
    (issues.length ? ` Run issues: ${issues.join("; ")}.` : "");
}

const live = () => state.data.results.filter((r) => !FILTERED.has(r.verdict)).sort((a, b) => b.score - a.score);

function sectionHead(title, sub, moreLabel, moreView) {
  return h("div", { class: "section-head" },
    h("div", {}, h("h2", {}, title), sub ? h("p", {}, sub) : null),
    moreView ? h("button", { type: "button", class: "more", onclick: () => goto(moreView) }, `${moreLabel} →`) : null);
}

function bigstat(r, withSpark = true) {
  return h("div", { class: "bigstat" }, h("b", {}, mult(r)),
    h("span", {}, `the usual audience · ${STAGES[r.stage] ? STAGES[r.stage].toLowerCase() : `since ${short(r.spike_start)}`}`),
    withSpark ? sparkline(r, true) : null);
}

function link(r, ...kids) { return h("a", { href: `#w-${r.qid}`, onclick: (e) => { e.preventDefault(); focusCard(r.qid); } }, ...kids); }

// ---------- Today ----------
function todayPage() {
  const L = live();
  if (!L.length) return [h("p", { class: "status" }, "A quiet day: no revivals in this edition.")];
  // Lead with a story people will recognise: a real everyday audience, ideally a picture.
  const known = L.slice(0, 12).filter((r) => r.baseline >= 100);
  const lead = known.find((r) => r.image) || known[0] || L.find((r) => r.image) || L[0];
  const rest = L.filter((r) => r !== lead);
  const st = story(lead);
  const out = [
    h("section", { class: "front" },
      h("article", { class: "lead" },
        ext(wikipedia(lead.title), media(lead.image, lead.label, lead.release_year, lead.kind, 1200)),
        h("span", { class: "kicker" }, st.kicker),
        h("h2", { class: "hed" }, link(lead, st.hed)),
        h("p", { class: "dek" }, st.dek),
        sourceLine(lead.editor_note),
        bigstat(lead)),
      h("aside", { class: "index" },
        h("h2", {}, "The Revival Index"),
        h("p", {}, "The biggest comebacks in this edition"),
        h("ol", {}, rest.slice(0, 10).map((r) => h("li", {}, h("div", {},
          h("div", { class: "t" }, link(r, r.label)),
          h("div", { class: "s" }, `${mult(r)} usual · ${story(r).kicker}`))))))),
  ];
  const shared = state.data.shared_triggers || [];
  if (shared.length) {
    out.push(sectionHead("Because Of…", "One event, many old favorites back at once."));
    out.push(h("div", {}, shared.map((t) => {
      const sst = sharedStory(t), first = state.byQid[t.works[0]];
      return h("article", { class: "feature" },
        t.image ? media(t.image, t.text.split(": ").pop().split(" (")[0], "", "", 300)
          : media(first && first.image, first && first.label, first && first.release_year, first && first.kind, 300),
        h("div", {}, h("span", { class: "kicker" }, sst.kicker), h("h3", { class: "hed" }, sst.hed), h("p", { class: "dek" }, sst.dek),
          h("div", { class: "chips" }, t.works.map((q) => state.byQid[q]).filter(Boolean).map((w) =>
            h("a", { class: "chip", href: `#w-${w.qid}`, onclick: (e) => { e.preventDefault(); focusCard(w.qid); } }, `${w.label} (${w.release_year})`)))));
    })));
  }
  const threads = state.data.common_threads || [];
  if (threads.length) {
    out.push(sectionHead("Six Degrees", "Unexplained spikes that share a person and the same timing.", "All mysteries", "mysteries"));
    out.push(h("div", {}, threads.slice(0, 4).map(threadFeature)));
  }
  const myst = rest.filter((r) => MYSTERY.has(r.verdict)).slice(0, 6);
  const solved = rest.filter((r) => ["ripple", "editor", "coverage"].includes(r.verdict)).slice(0, 6);
  if (myst.length) {
    out.push(sectionHead("The Mysteries", "Big comebacks with no obvious reason. Know why? Tell us.", "All mysteries", "mysteries"));
    out.push(h("div", { class: "grid" }, myst.map(storyCard)));
  }
  if (solved.length) {
    out.push(sectionHead("The Ripple Effect", "Old favorites riding a bigger story: news about a star, a franchise or a new adaptation."));
    out.push(h("div", { class: "grid" }, solved.map(storyCard)));
  }
  const cu = state.data.coming_up || {};
  if ((cu.derivatives || []).length) {
    out.push(sectionHead("Coming Soon", "Sequels, remakes and adaptations on the way. Expect the originals to come roaring back.", "Full calendar", "coming"));
    out.push(h("div", { class: "rail" }, cu.derivatives.slice(0, 10).map(derivMini)));
  }
  if ((cu.anniversaries || []).length) {
    out.push(sectionHead("Happy Anniversary", "Big birthdays in the next two months.", "Full calendar", "coming"));
    out.push(h("div", { class: "rail" }, cu.anniversaries.slice(0, 10).map(annMini)));
  }
  out.push(sectionHead(`Every Revival (${state.data.results.length})`, "Search, filter and dig into the numbers."));
  out.push(listSection());
  return out;
}

function threadFeature(t) {
  const st = threadStory(t);
  return h("article", { class: "feature" },
    ext(wikidata(t.qid), media(t.image, t.name, "", "", 300)),
    h("div", {}, h("span", { class: "kicker" }, st.kicker), h("h3", { class: "hed" }, st.hed), h("p", { class: "dek" }, st.dek),
      h("div", { class: "chips" }, t.works.map((w) => state.byQid[w.qid]).filter(Boolean).map((w) =>
        h("a", { class: "chip", href: `#w-${w.qid}`, onclick: (e) => { e.preventDefault(); focusCard(w.qid); } }, `${w.label} (${w.release_year})`))),
      sourceLine(t.editor_note), evidenceList(t.evidence, 3)));
}

function storyCard(r) {
  const st = story(r);
  return h("article", { class: "story" },
    ext(wikipedia(r.title), media(r.image, r.label, r.release_year, r.kind)),
    h("span", { class: "kicker" }, st.kicker),
    h("h3", { class: "hed" }, link(r, st.hed)),
    h("p", { class: "dek" }, st.dek),
    sourceLine(r.editor_note),
    bigstat(r),
    MYSTERY.has(r.verdict) ? h("div", {}, correctionLink(r, "Know why? Tell us →", "ask")) : null);
}

function derivMini(c) {
  return h("article", { class: "mini" },
    ext(wikidata(c.new), media(c.new_image || c.old_image, c.new_label, c.date.slice(0, 4), c.new_kind, 480)),
    h("div", { class: "when" }, `Due ${short(c.date)}`),
    h("h3", { class: "hed" }, c.new_label),
    h("p", { class: "dek" }, `${c.rel[0].toUpperCase()}${c.rel.slice(1)} `, ext(wikipedia(c.old_title), c.old_label), ` (${c.old_release.slice(0, 4)}). Expect a revival.`));
}
function annMini(a) {
  return h("article", { class: "mini" },
    ext(wikipedia(a.title), media(a.image, a.label, a.release.slice(0, 4), a.kind, 480)),
    h("div", { class: "when" }, short(a.date)),
    h("h3", { class: "hed" }, `${a.label} turns ${a.years}`),
    h("p", { class: "dek" }, `${noun(a.kind)[0].toUpperCase()}${noun(a.kind).slice(1)}, ${a.release.slice(0, 4)}${a.audience ? ` · ${fmt(a.audience)} readers on a normal day` : ""}`));
}

// ---------- Mysteries ----------
function mysteriesPage() {
  const L = live().filter((r) => MYSTERY.has(r.verdict) || ["coverage", "common thread", "ripple", "editor"].includes(r.verdict))
    .sort((a, b) => b.spike_start.localeCompare(a.spike_start) || b.score - a.score);
  const threads = state.data.common_threads || [];
  return [
    h("p", { class: "intro" }, "Old favorites are suddenly back, and we can't always say why. These are the open cases. If you know the answer, tell us."),
    threads.length ? sectionHead("Six Degrees", "Spikes that share a person and the same timing.") : null,
    threads.length ? h("div", {}, threads.map(threadFeature)) : null,
    sectionHead("Open Cases", "Newest first. Some have a likely cause from news and Wikipedia edits; most don't, yet."),
    h("div", { class: "grid" }, L.filter((r) => r.verdict !== "common thread").map(storyCard)),
  ].filter(Boolean);
}

// ---------- pro views ----------
function proPage(v) {
  const panels = (v.panels || []).map(panel).filter(Boolean);
  return [
    h("p", { class: "intro" }, v.intro),
    v.feeds ? feedStrip(v.feeds) : null,
    ...panels,
    sectionHead("Revivals", null),
    listSection(),
  ].filter(Boolean);
}

function panel(name) {
  const cu = state.data.coming_up || {};
  if (name === "threads") {
    const t = state.data.common_threads || [];
    return t.length ? h("div", {}, sectionHead("Six Degrees", "Unexplained spikes sharing a person and timing."), t.map(threadFeature)) : null;
  }
  if (name === "coming-mini" && (cu.derivatives || []).length)
    return h("div", {}, sectionHead("Coming Soon", "Sequels, adaptations and remakes of older works due soon.", "Full calendar", "coming"),
      h("div", { class: "rail" }, cu.derivatives.slice(0, 10).map(derivMini)));
  if (name === "anniversaries-mini" && (cu.anniversaries || []).length)
    return h("div", {}, sectionHead("Anniversaries Ahead", "Round-number birthdays in the next 60 days, biggest audiences first.", "Full calendar", "coming"),
      h("div", { class: "rail" }, cu.anniversaries.slice(0, 10).map(annMini)));
  if (name === "downloads") {
    const run = $("run").value;
    return h("div", { class: "block" }, sectionHead("Downloads", "Data is derived from CC0 sources. Please cite as “Revival Radar (open data from Wikimedia and Wikidata)”."),
      h("ul", { class: "plain" },
        h("li", {}, h("a", { href: "data/latest.csv", download: "" }, h("b", {}, "latest.csv")), " · spreadsheet of this edition"),
        h("li", {}, h("a", { href: `data/runs/${run}.json` }, h("b", {}, `runs/${run}.json`)), " · full snapshot with 12-month series, triggers and evidence"),
        h("li", {}, h("a", { href: "data/index.json" }, h("b", {}, "index.json")), " · every archived edition"),
        h("li", {}, h("a", { href: "data/accuracy.json" }, h("b", {}, "accuracy.json")), " · ", h("a", { href: "data/forecast_checks.json" }, "forecast_checks.json")),
        h("li", {}, ext(`https://github.com/${REPO}`, h("b", {}, "Source code and full history on GitHub")))));
  }
  if (name === "method") return method();
  return null;
}

function feedStrip(names) {
  return h("p", { class: "feedstrip" }, "Follow this view: ",
    names.map((n, i) => [i ? " · " : "", h("a", { href: `feeds/${n}.xml` }, `${n}.xml`)]),
    " · ", h("button", { type: "button", class: "linkish", onclick: () => goto("alerts") }, "email alerts"));
}

// ---------- the full list ----------
function listSection() {
  const kinds = [...new Set(state.data.results.map((r) => r.kind))].sort();
  const kindSel = h("select", { "aria-label": "Filter by type" },
    h("option", { value: "" }, state.kinds.size > 1 ? "Preset types" : "All types"),
    kinds.map((k) => h("option", { value: k, selected: state.kinds.size === 1 && state.kinds.has(k) ? "" : null }, k)));
  kindSel.addEventListener("change", (e) => { state.kinds = new Set(e.target.value ? [e.target.value] : []); renderList(); });
  const stageSel = h("select", { "aria-label": "Filter by stage" },
    h("option", { value: "" }, state.stages.size > 1 ? "Preset stages" : "Any stage"),
    Object.entries(STAGES).map(([k, v]) => h("option", { value: k, selected: state.stages.size === 1 && state.stages.has(k) ? "" : null }, v)));
  stageSel.addEventListener("change", (e) => { state.stages = new Set(e.target.value ? [e.target.value] : []); renderList(); });
  const sortSel = h("select", { "aria-label": "Sort" },
    [["score", "Biggest comeback"], ["lift", "Biggest jump"], ["recent", "Most readers now"], ["start", "Newest"], ["age", "Oldest work"]]
      .map(([k, l]) => h("option", { value: k, selected: state.sort === k ? "" : null }, `Sort: ${l}`)));
  sortSel.addEventListener("change", (e) => { state.sort = e.target.value; renderList(); });
  const q = h("input", { id: "q", type: "search", placeholder: "Search titles, people, causes…", "aria-label": "Search" });
  q.addEventListener("input", (e) => { state.q = e.target.value.trim().toLowerCase(); renderList(); });
  return h("section", { id: "list-section" },
    h("div", { class: "filters" }, q, kindSel, stageSel, sortSel),
    h("div", { id: "chips", class: "chips", role: "group", "aria-label": "Filter by type of story" }),
    h("p", { id: "count", class: "small muted" }),
    h("div", { id: "cards", class: "cards" }));
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
    const st = story(r);
    const hay = [r.label, r.title, r.kind, r.cause, st.hed, st.dek, ...r.triggers.map((t) => t.text), ...(r.evidence || []).map((e) => e.text)].join(" ").toLowerCase();
    if (!hay.includes(state.q)) return false;
  }
  return true;
}
function renderList() {
  const all = state.data.results;
  const pool = all.filter((r) => (!state.kinds.size || state.kinds.has(r.kind)) && (!state.stages.size || state.stages.has(r.stage)) && !(state.hideFiltered && FILTERED.has(r.verdict)));
  const counts = {};
  for (const r of pool) { const k = story(r).kicker; counts[k] = (counts[k] || 0) + 1; }
  // chips filter by story type (kicker), which maps to verdicts
  const byKicker = {};
  for (const r of all) (byKicker[story(r).kicker] = byKicker[story(r).kicker] || new Set()).add(r.verdict);
  $("chips").replaceChildren(...Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => {
    const vs = byKicker[k];
    const on = [...vs].every((v) => state.verdicts.has(v));
    const b = h("button", { class: "chip", type: "button", "aria-pressed": String(on) }, k, h("span", { class: "n" }, n));
    b.addEventListener("click", () => { vs.forEach((v) => (on ? state.verdicts.delete(v) : state.verdicts.add(v))); renderList(); });
    return b;
  }));
  const list = all.filter(matches).sort((a, b) => {
    if (!state.verdicts.size) { const fa = FILTERED.has(a.verdict), fb = FILTERED.has(b.verdict); if (fa !== fb) return fa ? 1 : -1; }
    return SORTS[state.sort](a, b);
  });
  $("count").textContent = list.length === all.length ? `${all.length} revivals` : `${list.length} of ${all.length} revivals`;
  const open = !!VIEWS[state.view].pro;
  $("cards").replaceChildren(...(list.length ? list.map((r) => card(r, open)) : [h("p", { class: "status" }, "Nothing matches these filters.")]));
}

function correctionLink(r, label = "Report a correction", cls) {
  const top = r.triggers[0];
  const body = [`**Work:** ${r.label} (${r.release_year}) ${wikidata(r.qid)}`, `**Edition:** ${$("run").value}`,
    `**Radar said:** ${story(r).hed}${top ? ` (${top.text})` : ""}${r.cause ? `; likely cause: ${r.cause}` : ""}`,
    "", "**What actually happened (with a link if you have one):**", ""].join("\n");
  const url = `https://github.com/${REPO}/issues/new?labels=feedback&title=${encodeURIComponent(`About ${r.label}`)}&body=${encodeURIComponent(body)}`;
  return h("a", { href: url, target: "_blank", rel: "noopener", class: cls || null }, label);
}

function evidenceList(ev, limit = 4) {
  if (!ev || !ev.length) return null;
  return h("ul", { class: "evidence" }, ev.slice(0, limit).map((e) =>
    h("li", {}, h("span", { class: "src" }, e.source), e.url ? ext(e.url, e.text) : e.text, h("span", { class: "d" }, short(e.date)))));
}

function card(r, open) {
  const st = story(r);
  const checks = [];
  const add = (node) => { if (checks.length) checks.push(" · "); checks.push(node); };
  if (r.last_year_lift != null) add(h("span", { class: r.last_year_lift >= 2.5 ? "warn" : "" }, `Same weeks last year: ${r.last_year_lift}×`));
  if (r.desktop_share != null) add(h("span", { class: r.desktop_share >= 0.85 ? "warn" : "" }, `${Math.round(r.desktop_share * 100)}% desktop`));
  if (r.corroborated === true) add(h("span", { class: "ok" }, "✓ backed by news/edits"));
  if (r.corroborated === false) add(h("span", { class: "warn" }, "Evidence doesn't mention this trigger"));
  if (r.edit_burst && r.edit_burst.burst) add(`${r.edit_burst.edits} Wikipedia edits around the spike (usually ~${r.edit_burst.usual_per_5_days})`);
  add(correctionLink(r));
  return h("article", { class: "card", id: `w-${r.qid}` },
    ext(wikipedia(r.title), media(r.image, r.label, r.release_year, r.kind, 240)),
    h("div", {},
      h("span", { class: "kicker" }, st.kicker),
      h("h3", { class: "hed" }, ext(wikipedia(r.title), st.hed)),
      h("p", { class: "dek" }, st.dek),
      sourceLine(r.editor_note),
      h("div", { class: "tags" },
        h("span", { class: "tagx" }, `${r.label} · ${r.release_year}`),
        r.stage === "emerging" ? h("span", { class: "tagx hot" }, "Just starting") : r.stage ? h("span", { class: "tagx" }, STAGES[r.stage]) : null,
        r.early ? h("span", { class: "tagx", title: "Spotted by our watchlist before it reached Wikipedia's top 1,000" }, "Caught early") : null),
      h("details", { class: "more-info", open: open ? "" : null }, h("summary", {}, "The numbers"),
        sparkline(r),
        h("dl", { class: "nums" },
          h("div", {}, h("dt", {}, "14-day lift"), h("dd", {}, `${r.lift}×`)),
          h("div", {}, h("dt", {}, "Last 3 days"), h("dd", {}, `${r.lift3 ?? "–"}×`)),
          h("div", {}, h("dt", {}, "Usual"), h("dd", {}, `${fmt(r.baseline)}/day`)),
          h("div", {}, h("dt", {}, "Began"), h("dd", {}, short(r.spike_start)))),
        r.triggers.length ? h("ul", { class: "triggers" }, r.triggers.map((t) =>
          h("li", {}, t.qid ? ext(wikidata(t.qid), t.text) : t.text, h("span", { class: "d" }, short(t.date))))) : null,
        evidenceList(r.evidence, 8),
        h("p", { class: "checks" }, checks))));
}

// ---------- sparkline ----------
function sparkline(r, compact) {
  const vals = r.spark, n = vals.length, W = n - 1, H = 60;
  const top = Math.max(...vals, r.baseline * 2, 1);
  const lg = (x) => Math.log10(1 + x);
  const y = (x) => H - (lg(x) / lg(top)) * (H - 4);
  const pts = vals.map((x, i) => `${i},${y(x).toFixed(1)}`).join(" ");
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `Daily Wikipedia views over 12 months for ${r.label}. Usually ${fmt(r.baseline)} a day, peak ${fmt(r.peak)} on ${fmtDate(r.peak_day)}.` });
  svg.append(s("polygon", { class: "area", points: `0,${H} ${pts} ${W},${H}` }));
  svg.append(s("line", { class: "base", x1: 0, x2: W, y1: y(r.baseline), y2: y(r.baseline) }));
  const si = daysBetween(r.spark_start, r.spike_start);
  if (si >= 0 && si < n && !compact) svg.append(s("line", { class: "start", x1: si, x2: si, y1: 0, y2: H }));
  svg.append(s("polyline", { class: "line", points: pts }));
  const cursor = s("line", { class: "cursor", x1: 0, x2: 0, y1: 0, y2: H, visibility: "hidden" });
  svg.append(cursor);
  const tip = $("tip");
  const move = (e) => {
    const box = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - box.left) / box.width) * W)));
    cursor.setAttribute("x1", i); cursor.setAttribute("x2", i); cursor.setAttribute("visibility", "visible");
    tip.textContent = `${fmtDate(addDays(r.spark_start, i))} · ${fmt(vals[i])} readers`;
    tip.style.left = `${box.left + (i / W) * box.width}px`; tip.style.top = `${box.top}px`; tip.hidden = false;
  };
  const leave = () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerdown", move); svg.addEventListener("pointerleave", leave);
  return h("div", { class: "spark" }, svg, compact ? null : h("div", { class: "spark-legend" }, h("span", {}, "Daily readers, last 12 months"), h("span", {}, "dashed line = usual")));
}

function focusCard(qid) {
  let el = $(`w-${qid}`);
  if (!el && !$("cards")) { goto("today"); el = $(`w-${qid}`); }
  if (!el) {
    state.verdicts.clear(); state.kinds.clear(); state.stages.clear(); state.hideFiltered = false; state.q = "";
    if ($("q")) $("q").value = "";
    renderList();
    el = $(`w-${qid}`);
  }
  if (!el) return;
  const d = el.querySelector("details");
  if (d) d.open = true;
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800);
}

// ---------- Coming Soon ----------
function comingPage() {
  const cu = state.data.coming_up || { derivatives: [], anniversaries: [] };
  const dRows = (cu.derivatives || []).map((c) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(c.date)),
    h("td", {}, ext(wikidata(c.new), h("b", {}, c.new_label)), h("div", { class: "small muted" }, c.new_kind)),
    h("td", {}, c.rel),
    h("td", {}, ext(wikipedia(c.old_title), c.old_label), h("div", { class: "small muted" }, `${c.old_kind}, ${c.old_release.slice(0, 4)}`))));
  const aRows = (cu.anniversaries || []).map((a) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(a.date)),
    h("td", {}, ext(wikipedia(a.title), h("b", {}, a.label)), h("div", { class: "small muted" }, `${a.kind}, ${a.release.slice(0, 4)}`)),
    h("td", { class: "num" }, `${a.years}th`),
    h("td", { class: "num" }, a.audience ? fmt(a.audience) : "–")));
  return [
    h("p", { class: "intro" }, "What's about to bring old favorites back: sequels, remakes and adaptations on the way, plus the big birthdays. We check later whether we were right."),
    sectionHead("On the Way", "Due in the next five months, each tied to an older work. From Wikidata; release dates can slip."),
    (cu.derivatives || []).length ? h("div", { class: "rail" }, cu.derivatives.slice(0, 12).map(derivMini)) : null,
    table(["Due", "New release", "Relation", "The original"], dRows),
    sectionHead("Big Birthdays", "Round-number anniversaries in the next 60 days, ranked by how many people normally read about them."),
    (cu.anniversaries || []).length ? h("div", { class: "rail" }, cu.anniversaries.slice(0, 12).map(annMini)) : null,
    table(["Date", "Work", "Turns", "Readers on a normal day"], aRows),
  ].filter(Boolean);
}
function table(head, rows) {
  if (!rows.length) return h("p", { class: "muted" }, "Nothing here yet. This fills in once the daily run has built its watchlist.");
  return h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, head.map((x) => h("th", {}, x)))), h("tbody", {}, rows)));
}

// ---------- Track Record ----------
function accuracyPage() {
  const a = state.accuracy;
  if (!a) return [h("p", { class: "intro" }, "How often are we right? We're keeping score in public."), h("p", { class: "muted" }, "The scorecard builds up as daily editions accumulate. Check back in a week or two.")];
  const f = a.forecasts || {}, c = a.corroboration || {}, p = a.persistence || {}, rr = a.reader_reports || {};
  const stat = (big, label, sub) => h("div", { class: "stat" }, h("b", {}, big), h("span", {}, label), sub ? h("small", {}, sub) : null);
  const recent = (f.recent || []).map((x) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(x.date)), h("td", {}, h("b", {}, x.label)), h("td", {}, x.detail),
    h("td", { class: "num" }, `${x.ratio}×`), h("td", {}, x.hit ? h("span", { class: "ok" }, "✓ Came true") : h("span", { class: "muted" }, "No bump"))));
  const corrRows = Object.entries(c).filter(([k]) => k !== "all").map(([k, v]) => h("tr", {},
    h("td", {}, state.labels[k] || k), h("td", { class: "num" }, v.checked), h("td", { class: "num" }, pct(v.rate))));
  return [
    h("p", { class: "intro" }, "How often are we right? We're keeping score in public, every day."),
    h("p", { class: "intro-sub" }, "Early on the numbers are small, so treat these rates as provisional until there are dozens of checks."),
    h("section", { class: "stats" },
      stat(pct(f.all?.rate), "of predictions came true", `${f.all?.hits ?? 0} of ${f.all?.checked ?? 0} checked`),
      stat(pct(c.all?.rate), "of explanations backed by news or edits", `${c.all?.agree ?? 0} of ${c.all?.checked ?? 0} with evidence`),
      stat(p.median_days == null ? "–" : `${p.median_days}d`, "a typical revival lasts", p.share_over_7_days == null ? "" : `${pct(p.share_over_7_days)} last over a week`),
      stat(`${rr.correct ?? 0}/${rr.wrong ?? 0}`, "reader reports: right / wrong", `${rr.open ?? 0} awaiting review`)),
    sectionHead("Did the Prediction Come True?", "A prediction counts if the older work hit 2× its usual readers within a week of the date."),
    table(["Date", "Work", "We predicted", "Peak vs usual", "Result"], recent),
    sectionHead("Do Our Explanations Hold Up?", "For explained spikes: did news or Wikipedia edits from the same days mention the same cause?"),
    table(["Story type", "Checked", "Backed by evidence"], corrRows),
    sectionHead("Help Us Check", null),
    h("p", {}, "Every story has a ", h("b", {}, "Report a correction"), " link. Reports become GitHub issues; once reviewed and labelled ",
      h("code", {}, "verified-correct"), " or ", h("code", {}, "verified-wrong"), ", they count above. ",
      ext(`https://github.com/${REPO}/issues?q=label%3Afeedback`, h("b", {}, "See all reports →"))),
  ];
}

// ---------- Alerts ----------
function alertsPage() {
  const base = new URL(".", location.href).href;
  const feeds = [
    ["all", "Everything new: comebacks, shared causes, six-degrees threads, predictions"],
    ["unexplained", "The mysteries: unexplained spikes and causes found in coverage. Great for journalists."],
    ["coming-up", "Coming soon: sequels, remakes and adaptations of older works"],
    ["film-tv", "Film & TV"], ["music", "Songs, albums and musicals"], ["games", "Video games"], ["books", "Books, manga and comics"],
  ];
  return [
    h("p", { class: "intro" }, "Get the day's comebacks without checking the site."),
    sectionHead("By Email", "A short daily digest, free."),
    h("ol", {},
      h("li", {}, "Sign in to GitHub (free) and open ", ext(`https://github.com/${REPO}`, h("b", {}, `github.com/${REPO}`)), "."),
      h("li", {}, "Click ", h("b", {}, "Watch"), " → ", h("b", {}, "Custom"), " → tick ", h("b", {}, "Issues"), " → ", h("b", {}, "Apply"), "."),
      h("li", {}, "Each morning's digest arrives in your inbox.")),
    h("p", { class: "muted" }, "No GitHub account? Paste any feed below into a free RSS-to-email service."),
    sectionHead("By Feed", "Paste a link into any feed reader (Feedly, Inoreader, NetNewsWire, Outlook, Slack…)."),
    h("ul", { class: "plain" }, feeds.map(([n, d]) => h("li", {},
      h("a", { href: `feeds/${n}.xml` }, h("b", {}, `${n}.xml`)),
      h("button", { type: "button", class: "copy", onclick: (e) => copy(`${base}feeds/${n}.xml`, e.target) }, "Copy link"),
      h("div", { class: "small muted" }, d)))),
    sectionHead("Raw Data", null),
    h("p", {}, "Build your own alerts from ", h("a", { href: "data/latest.json" }, h("b", {}, "latest.json")), " or ",
      h("a", { href: "data/latest.csv" }, h("b", {}, "latest.csv")), ", refreshed daily around 04:30 UTC."),
  ];
}
function copy(text, btn) {
  (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject()).then(
    () => { btn.textContent = "Copied"; setTimeout(() => (btn.textContent = "Copy link"), 1500); },
    () => { window.prompt("Copy this link:", text); });
}

function method() {
  return h("div", { class: "block" }, sectionHead("How It Works", null),
    h("ol", {},
      h("li", {}, h("b", {}, "Watch."), " Every day, read Wikimedia's bulk pageview file for ~35,000 notable older works (10+ language editions, released 10+ years ago), plus English Wikipedia's daily top 1,000."),
      h("li", {}, h("b", {}, "Measure."), " Compare each work's last 3 and 14 days with its median over the previous ~11 months. 3× over 14 days, or 2.5× over 3 days, counts. Stages: just starting (began in the last 4 days), at its peak, still going (10+ days), cooling off."),
      h("li", {}, h("b", {}, "Explain."), " Look in Wikidata near the spike for deaths of credited people, sequels, adaptations, remakes, new series entries, new work by the same creator, and anniversaries. For spikes it can't explain, read Wikipedia edit summaries, edit bursts and GDELT news headlines from the same days."),
      h("li", {}, h("b", {}, "Connect."), " Group spikes by a shared event, and unexplained spikes by a shared person with the same timing."),
      h("li", {}, h("b", {}, "Filter."), " Set aside seasonal items (also up this time last year) and spikes that are almost all desktop traffic (likely bots)."),
      h("li", {}, h("b", {}, "Predict and check."), " List upcoming sequels, adaptations and anniversaries, then check later whether attention rose.")),
    h("p", { class: "muted" }, h("b", {}, "Limits. "), "Wikipedia attention isn't sales or streams. Wikidata is volunteer-edited. News and edit lookups are best-effort and sometimes rate-limited. Two-title threads can be coincidence. Headlines are generated from the data. Verify before publishing or acting."));
}

window.addEventListener("scroll", () => { $("tip").hidden = true; }, { passive: true });
init();
