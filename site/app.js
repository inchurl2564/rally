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

// Where "Know why? Tell us" tips go: an on-page form that posts to a form service.
//   Google Forms: action = "https://docs.google.com/forms/d/e/<form id>/formResponse",
//                 fields = the form's "entry.123456" names (from its "Get pre-filled link").
//   Formspree or similar: action = the endpoint URL, fields = any names you like.
// While `action` is empty, tips fall back to a GitHub issue.
const TIPS_FORM = {
  // "The Rallyback: reader tips" Google Form. Tips land in its Responses tab, not on GitHub.
  action: "https://docs.google.com/forms/d/e/1FAIpQLSehhvp1CIt7-yHlXQnbXQsH8uWOLBOq69jgRHVQHKd5xb2Tqg/formResponse",
  fields: { work: "entry.1483552552", why: "entry.35323025", link: "entry.1249623889", email: "entry.134841440" },
};

const FILTERED = new Set(["seasonal", "automated?", "front page"]);
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
// The reason itself links to the article it came from (no source named in the text).
// An editor's note links to its source the same way (outside sources only, never Wikipedia).
function dekWithLink(text, cause, link, note) {
  const [phrase, url] = note && note.source && !/wikipedia\.org/.test(note.source) && text.includes(note.text)
    ? [note.text, note.source] : [cause ? causeSentence(cause) : null, link && link.url];
  if (!url || !phrase || !text.includes(phrase)) return text;
  const i = text.indexOf(phrase);
  return [text.slice(0, i), ext(url, phrase), text.slice(i + phrase.length)];
}
const REL = { "adaptation/based on it": "a new adaptation", sequel: "the sequel", "derivative work": "a spin-off",
  "remake/new version": "the remake", "new entry in same series": "the new entry in the series" };

function mult(r) {
  const m = Math.max(r.lift || 0, r.lift3 || 0);
  return m >= 10 ? `${Math.round(m)}×` : `${m.toFixed(1).replace(/\.0$/, "")}×`;
}

// ---------- the editorial voice: turn a finding into a story ----------
function story(r) {
  const reason = reasonOf(r);
  return { ...storyText(r), reason, kicker: reason === OTHER ? SET_ASIDE[r.verdict] || reason.label : reason.label };
}
function storyText(r) {
  const w = r.label, yr = r.release_year, n = noun(r.kind), x = mult(r);
  const t = r.triggers && r.triggers[0];
  const upcoming = t && /\(upcoming\)$/.test(t.text);
  const strip = (str) => str.replace(/ \((upcoming|attention rose before release)\)$/, "");
  const since = `since ${short(r.spike_start)}`;
  switch (r.verdict) {
    case "death": {
      const who = t.text.split(" (")[0], role = (t.text.match(/\(([^)]+)\)/) || [])[1];
      return { kicker: "In Memoriam", hed: `${w} is back as fans remember ${who}`,
        dek: `The ${yr} ${n} has drawn ${x} its usual interest since ${who}${role ? `, its ${role},` : ""} died on ${fmtDate(t.date)}.` };
    }
    case "derivative": {
      const [rel, ...rest] = t.text.split(": "), nw = strip(rest.join(": "));
      const what = REL[rel] || "a new release";
      // A new version with the original's own name: "thanks to Zelda" would read as nonsense.
      if (sameName(nw, w)) return upcoming
        ? { kicker: "Homework", hed: `${w} is back, just ahead of a new version of the same name`,
            dek: `The ${yr} ${n} is already at ${x} its usual interest, with a new version of the same name due ${fmtDate(t.date)}.` }
        : { kicker: "The Sequel Effect", hed: `${w} is back, thanks to a new version of the same name`,
            dek: `The ${yr} ${n} is drawing ${x} its usual interest since a new version of the same name came out ${fmtDate(t.date)}.` };
      return upcoming
        ? { kicker: "Homework", hed: `${w} is back, just ahead of ${nw}`,
            dek: `The ${yr} ${n} is already at ${x} its usual interest, with ${what}, ${nw}, due ${fmtDate(t.date)}.` }
        : { kicker: "The Sequel Effect", hed: `${w} is back, thanks to ${nw}`,
            dek: `The ${yr} ${n} is drawing ${x} its usual interest since ${what}, ${nw}, came out ${fmtDate(t.date)}.` };
    }
    case "same-creator": {
      const m = t.text.match(/^new work by (.+?): (.+)$/) || [];
      const who = m[1] || "Its creator", nw = strip(m[2] || "a new release");
      return { kicker: "Back Catalog", hed: upcoming ? `${w} is back as ${who}'s next release nears` : `${w} is back after ${who}'s new release`,
        dek: `The ${yr} ${n} is drawing ${x} its usual interest. ${who}'s ${nw} ${upcoming ? `is due ${fmtDate(t.date)}` : `came out ${fmtDate(t.date)}`}.` };
    }
    case "anniversary": {
      const yrs = (t.text.match(/^(\d+)/) || [])[1];
      return { kicker: "Happy Birthday", hed: `${w} turns ${yrs}`,
        dek: `The ${n} came out on ${fmtDate(r.release)}, and people are marking the occasion: ${x} its usual interest.` };
    }
    case "common thread": {
      const who = t.text.split(" (")[0], k = (t.text.match(/credited on (\d+)/) || [])[1];
      // If its group is explained (an editor's note, the person's own spike, a likely cause), say so.
      const grp = (state.data.common_threads || []).find((g) => threadExplained(g) && g.works.some((x) => x.qid === r.qid));
      // Two titles sharing someone is often coincidence: unexplained, it's told as a plain mystery.
      if (!grp && +k < MIN_LINKED) return mysteryText(r, w, yr, n, x, since);
      return { kicker: "Six Degrees", hed: `${w} is one of ${k} ${who} titles back at once`,
        dek: grp ? threadStory(grp).dek : `They all started rising around ${short(t.date)}. Something is going on with ${who}, but we can't say what yet.` };
    }
    case "ripple": {
      const rp = r.ripple;
      const hed = rp.relation === "sequel or adaptation" ? `${w} is back as ${rp.name} draws crowds`
        : ["franchise", "series", "character"].includes(rp.relation) ? `${w} rides the ${rp.name} wave`
        : rp.relation === "source material" ? (rp.name === w ? `The ${yr} ${n} of ${w} is back as the original makes news` : `${w} is back as ${rp.name} makes news`)
        : `${w} draws new interest amid news about ${rp.name}`;
      return { kicker: "The Ripple Effect", hed,
        dek: `Interest in the ${yr} ${n} took off right as interest in ${rp.name} jumped ${rp.ratio}× on ${short(rp.date)}.${["franchise", "series", "character", "sequel or adaptation", "source material"].includes(rp.relation) ? "" : ` Something happened involving ${rp.name}.`}` };
    }
    case "editor-release":
    case "editor-death":
    case "editor":
      return { kicker: "Explained", hed: `Why interest in ${w} is up`, dek: `${r.editor_note.text} The ${yr} ${n} is drawing ${x} its usual interest.` };
    case "coverage":
      return { kicker: "Explained", hed: `Why ${w} is suddenly everywhere`,
        dek: `${causeSentence(r.cause)}. The ${yr} ${n} is at ${x} its usual interest.` };
    case "seasonal":
      return { kicker: "Right on Schedule", hed: `It's that time of year for ${w}`,
        dek: `Interest in the ${yr} ${n} jumps around now every year. Same weeks last year: ${r.last_year_lift}× usual.` };
    case "front page":
      return { kicker: "Wikipedia's Doing", hed: `${w} was on Wikipedia's front page`,
        dek: `The ${yr} ${n} was ${r.front_page.kind === "Today's featured article" ? "Today's Featured Article" : `in “${r.front_page.kind}”`} on ${fmtDate(r.front_page.date)}, which brings a one-day flood of visitors. Not a comeback.` };
    case "automated?":
      return { kicker: "Probably Bots", hed: `${w}'s spike looks automated`,
        dek: `Almost all of the extra traffic comes from desktop computers, a typical sign of bots rather than people.` };
    default:
      return mysteryText(r, w, yr, n, x, since);
  }
}
const MIN_LINKED = 3;     // an unexplained "linked by one person" group needs 3+ titles
function mysteryText(r, w, yr, n, x, since) {
  const heds = [
    `Nobody can explain why people are suddenly looking up ${w}`,
    `${w} is having a moment. Nobody knows why.`,
    `Why is everyone suddenly reading about ${w}?`,
    `The internet rediscovered ${w}, and we can't figure out why`,
  ];
  return { kicker: "Mystery", hed: heds[hash(r.qid) % heds.length],
    dek: `The ${yr} ${n} has drawn ${x} its usual interest ${since}, with no sequel, death, anniversary or news story we can find.` };
}

// "A, B and 10 more": the old works themselves, biggest comeback first.
function oldNames(works) {
  const ws = [...works].sort((a, b) => (b.score || 0) - (a.score || 0));
  const nm = (w) => (ws.filter((o) => o.label === w.label).length > 1 ? `${w.label} (${w.release_year})` : w.label);
  if (ws.length === 1) return nm(ws[0]);
  if (ws.length === 2) return `${nm(ws[0])} and ${nm(ws[1])}`;
  return `${nm(ws[0])}, ${nm(ws[1])} and ${ws.length - 2} more`;
}
// A group's headline jumps to the card of its biggest comeback (the first one it names).
const topOf = (works) => [...works].sort((a, b) => (b.score || 0) - (a.score || 0))[0];
const hedLink = (r, text) => (r ? link(r, text) : text);

// The biggest old work in a group that has a photo, so groups are pictured by what came back.
const topPictured = (works) => {
  const ws = [...works].sort((a, b) => (b.score || 0) - (a.score || 0));
  return ws.find((w) => w.image && !w.image_of) || ws.find((w) => w.image);   // its own photo first
};

const sameName = (a, b) => plain(String(a)).toLowerCase().trim() === plain(String(b)).toLowerCase().trim();
function sharedStory(t) {
  const works = t.works.map((q) => state.byQid[q]).filter(Boolean);
  const names = oldNames(works);
  if (t.type === "death") {
    const who = t.text.split(" (")[0];
    return { reason: STREAM_TYPES[3], kicker: "In memoriam", hed: `${names} ${works.length === 1 ? "is" : "are"} back as fans remember ${who}`,
      dek: `${works.length} older titles are getting far more interest than usual since ${who} died on ${fmtDate(t.date)}.` };
  }
  const nw = t.text.split(": ").slice(1).join(": ").replace(/ \((upcoming|attention rose before release)\)$/, "") || t.text;
  const up = /\(upcoming\)$/.test(t.text);
  const are = works.length === 1 ? "is" : "are";
  if (works.length && works.every((w) => sameName(w.label, nw))) return { reason: STREAM_TYPES[1], kicker: "New release",
    hed: `${names} ${are} back, ${up ? "just ahead of" : "thanks to"} a new version of the same name`,
    dek: `A new version of the same name ${up ? `is due ${fmtDate(t.date)}` : `came out ${fmtDate(t.date)}`}.` };
  return { reason: STREAM_TYPES[1], kicker: "New release",
    hed: up ? `${names} ${are} back, just ahead of ${nw}` : `${names} ${are} back, thanks to ${nw}`,
    dek: `${works.length} older titles are getting far more interest than usual. ${nw} ${up ? `is due ${fmtDate(t.date)}` : `came out ${fmtDate(t.date)}`}.` };
}

// Where a story's information comes from. Never in headlines or subheads; one tap away instead.
// Confirmation from outside English Wikipedia: charts, Steam, other languages, Bluesky.
function elsewhere(r) {
  const items = (r.signals || []).map((x) => h("li", {}, h("span", { class: "src" }, x.source), x.text));
  const up = (r.global || {}).up || [];
  if (up.length) items.push(h("li", {}, h("span", { class: "src" }, "Other Wikipedias"),
    `Also rising in ${up.slice(0, 5).map((x) => `${x.name} (${x.lift}×)`).join(", ")}${up.length > 5 ? ` and ${up.length - 5} more` : ""}, of ${r.global.checked} languages checked`));
  const c = r.chatter;
  if (c && c.week) items.push(h("li", {}, h("span", { class: "src" }, "Bluesky"),
    `About ${fmt(c.week >= 1000 ? Math.round(c.week / 100) * 100 : c.week)} posts a week since it took off${c.usual ? `, ${c.ratio}× the weeks before` : ", up from almost none"}`,
    c.top ? [h("br"), ext(c.top.url, `“${c.top.text.slice(0, 140)}${c.top.text.length > 140 ? "…" : ""}”`), ` @${c.top.handle}`] : null));
  return items.length ? h("ul", { class: "evidence" }, items) : null;
}

function sourcesFor(r) {
  const out = [h("p", { class: "small" }, titleLink(r.qid, `Every comeback of ${plain(r.label)} →`)),
    h("p", { class: "small" }, ext(wikipedia(r.title), `${r.label} on Wikipedia →`))];
  if (r.editor_note) out.push(sourceLine(r.editor_note));
  const rp = r.ripple;
  if (rp) out.push(h("p", { class: "small" }, `${rp.name}'s Wikipedia page jumped ${rp.ratio}× on ${short(rp.date)} (${fmt(rp.peak)} views in a day), as interest in this ${noun(r.kind)} took off.`));
  if (r.verdict === "coverage" && r.cause) out.push(h("p", { class: "small" }, "Likely cause read from news headlines and Wikipedia edits from the days interest jumped."));
  out.push(elsewhere(r));
  if ((r.evidence || []).length) out.push(evidenceList(r.evidence, 4));
  out.push(h("p", { class: "small muted" }, `Interest is measured from daily Wikipedia views: usually ${fmt(r.baseline)} a day for this ${noun(r.kind)}.`));
  return out;
}
function threadSources(t) {
  const out = t.title ? [h("p", { class: "small" }, ext(wikipedia(t.title), `${t.name} on Wikipedia →`))] : [];
  if (t.editor_note) out.push(sourceLine(t.editor_note));
  if (t.person_jump) out.push(h("p", { class: "small" }, `${t.name}'s Wikipedia page jumped ${t.person_jump.ratio}× on ${short(t.person_jump.date)} (${fmt(t.person_jump.peak)} views in a day).`));
  if (t.cause) out.push(h("p", { class: "small" }, "Likely cause read from news headlines and Wikipedia edits."));
  if ((t.evidence || []).length) out.push(evidenceList(t.evidence, 3));
  return out;
}
function sourcesBox(nodes) {
  nodes = (nodes || []).filter(Boolean);
  return nodes.length ? h("details", { class: "more-info sources" }, h("summary", {}, "Sources"), ...nodes) : null;
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
    : pj ? `Interest in ${t.name} jumped ${pj.ratio}× on ${short(pj.date)}, so this is about ${t.name}.${t.cause ? ` ${causeSentence(t.cause)}.` : ""}`
    : t.cause ? `${causeSentence(t.cause)}.` : "We don't know why yet. Maybe you know?";
  const works = t.works.map((w) => state.byQid[w.qid]).filter(Boolean);
  const known = !!(t.editor_note || pj || t.cause);
  const sec = t.editor_note ? STREAM_TYPES[NOTE_SECTION[t.editor_note.cause] ?? 0] : STREAM_TYPES[0];
  return { reason: known ? sec : STREAM_TYPES[2], kicker: known ? sec.label : "Unexplained",
    hed: `${oldNames(works)}: ${t.works.length} titles ${how} ${t.name}, all back at once`,
    dek: `They all started rising around ${short(t.around)}. ${cause}` };
}

// ---------- photos: only real, freely licensed Wikimedia Commons images ----------
// No photo → no image slot at all; the story runs as text. If a photo fails to load,
// its slot is removed and the layout falls back to text-only.
// `of` names who is pictured when the photo is of a person behind the work (no free image of the work itself).
function pic(href, image, alt, width = 640, of = null, fallback = null) {
  if (!image) return null;
  const img = h("img", { src: `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(image)}?width=${width}`,
    alt: of || alt || "", loading: "lazy", decoding: "async" });
  const box = h("div", { class: "media" }, href ? ext(href, img) : img,
    ext(`https://commons.wikimedia.org/wiki/File:${encodeURIComponent(image)}`,
      h("span", { class: "credit" }, of ? `Pictured: ${of}` : "Photo: Wikimedia Commons")));
  img.addEventListener("error", () => {
    if (fallback) { box.replaceWith(fallback()); return; }
    box.closest(".has-media")?.classList.remove("has-media"); box.remove();
  });
  return box;
}
// An article that gets a .has-media class only when it actually has a photo.
function withPic(tag, cls, photo, ...kids) {
  return h(tag, { class: `${cls}${photo ? " has-media" : ""}` }, photo, ...kids);
}

// ---------- views ----------
const PHYSICAL = ["album", "video game", "book", "manga/comic", "film"];
const VIEWS = {
  today: { label: "Today", page: "today" },
  week: { label: "This week", page: "week" },
  mysteries: { label: "Unexplained", page: "mysteries" },
  coming: { label: "Coming up", page: "coming" },
  accuracy: { label: "Track record", page: "accuracy" },
  about: { label: "About us", page: "about" },
  // reached from links, not the menu
  work: { hidden: true, label: "Title", page: "work" },
  search: { hidden: true, label: "Search", page: "search" },
  following: { hidden: true, label: "Following", page: "following" },
  // professional views
  journalists: { pro: true, label: "Journalists",
    intro: "Story leads: big comebacks nobody has explained, works that rose together around one person, and causes suggested by news and Wikipedia edits.",
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
  getJSON("data/accuracy.json").then((a) => { state.accuracy = a; if (state.view === "accuracy" || state.view === "coming") render(); }).catch(() => {});
  const runs = state.index.runs || [];
  const sel = $("run");
  runs.forEach((r, i) => sel.append(h("option", { value: r.id }, i === 0 ? `Latest edition · ${short(r.id)}` : `Edition of ${fmtDate(r.id)}`)));
  const params = new URLSearchParams(location.search);
  const first = runs.some((r) => r.id === params.get("run")) ? params.get("run") : runs[0] && runs[0].id;
  if (!first) return fail("No editions yet.");
  sel.value = first;
  sel.addEventListener("change", () => loadRun(sel.value));
  const tab = params.get("tab");
  // Old links: ?tab=alerts now opens About us (where the feeds moved).
  state.view = VIEWS[tab] ? tab : tab === "alerts" ? "about" : "today";
  if (params.get("work")) { state.view = "work"; state.workId = params.get("work"); }
  if (params.get("q")) state.searchQ = params.get("q");
  const ms = $("msearch");
  if (ms) ms.closest("form").addEventListener("submit", (e) => { e.preventDefault(); state.searchQ = ms.value.trim(); goto("search"); });
  renderTabs();
  await loadRun(first);
}

async function loadRun(id) {
  setStatus("Loading…");
  try { state.data = await getJSON(`data/runs/${encodeURIComponent(id)}.json`); }
  catch (e) { return fail(`Couldn't load the edition for ${id}.`); }
  state.byQid = Object.fromEntries(state.data.results.map((r) => [r.qid, r]));
  // Works in an explained "same person, same time" group are in the news, not unexplained.
  state.explainedByThread = new Set((state.data.common_threads || []).filter(threadExplained).flatMap((t) => t.works.map((w) => w.qid)));
  buildCauseGroups();
  applyPreset();
  render();
  syncURL();
  if (state.view !== "work") setTitle();
  if (location.hash.startsWith("#w-")) setTimeout(() => focusCard(location.hash.slice(3)), 50);
}

function syncURL() {
  const p = new URLSearchParams();
  if ($("run").value && $("run").value !== (state.index.runs[0] || {}).id) p.set("run", $("run").value);
  if (state.view === "work" && state.workId) p.set("work", state.workId);
  else if (state.view !== "today") p.set("tab", state.view);
  if (state.view === "search" && state.searchQ) p.set("q", state.searchQ);
  const q = p.toString();
  history.replaceState(null, "", (q ? `?${q}` : location.pathname) + location.hash);
}
function setStatus(msg, error) { $("view").replaceChildren(h("p", { class: `status${error ? " error" : ""}`, role: "status" }, msg)); }
const fail = (msg) => setStatus(msg, true);

// Contact address, put together in the browser so simple spam bots reading the page source don't find it.
const CONTACT = ["hello", "therallyback.com"].join("@");
const contactLink = () => h("a", { href: "mailto:" + CONTACT }, CONTACT);

// The weekly newsletter (Beehiiv, free plan). Sign-ups happen on Beehiiv's own page.
const NEWSLETTER = "https://therallyback.beehiiv.com/subscribe";
function newsletterBox() {
  return h("aside", { class: "newsletter" },
    h("div", {}, h("h3", {}, "Comebacks in your inbox, every Friday"),
      h("p", {}, "The week's 5 biggest comebacks, the best unsolved mystery and what's coming next. Free, and one email a week.")),
    newsletterForm());
}
// Beehiiv's embedded form: its loader script puts an iframe right after itself.
const NEWSLETTER_FORM = "2bf7c4db-3cb3-4be0-8b2f-9a189b360e3a";
function newsletterForm() {
  const slot = h("div", { class: "newsletter-form" });
  const js = document.createElement("script");
  js.async = true; js.src = "https://subscribe-forms.beehiiv.com/v3/loader.js";
  js.setAttribute("data-beehiiv-form", NEWSLETTER_FORM);
  slot.append(js, h("a", { class: "newsletter-alt small", href: NEWSLETTER, target: "_blank", rel: "noopener" }, "Form not showing? Sign up on our newsletter page"));
  return slot;
}

function renderTabs() {
  const tab = (key) => h("button", { type: "button", class: "tab", "aria-current": key === state.view ? "page" : null, onclick: () => goto(key) }, VIEWS[key].label);
  // The main menu is for everyone; the professional views are linked from the footer.
  $("tabs").replaceChildren(...Object.keys(VIEWS).filter((k) => !VIEWS[k].pro && !VIEWS[k].hidden).map(tab));
  updateFollowLink();
  const contact = $("contact");
  if (contact && !contact.firstChild) contact.replaceChildren("Contact: ", contactLink(), " · Weekly newsletter: ",
    h("a", { href: NEWSLETTER, target: "_blank", rel: "noopener" }, "subscribe free"));
  const foot = $("pro-links");
  if (foot) foot.replaceChildren("For professionals: ", ...Object.keys(VIEWS).filter((k) => VIEWS[k].pro).flatMap((k, i) => [
    i ? " · " : "", h("a", { href: `?tab=${k}`, onclick: (e) => { e.preventDefault(); goto(k); } }, VIEWS[k].label)]));
}

// The browser tab names the page you're on.
const SITE_TITLE = "The Rallyback: why old movies, shows, songs, games and books are trending again";
function setTitle() {
  const v = VIEWS[state.view];
  document.title = !v || state.view === "today" ? SITE_TITLE : `${v.label || "Title"} · The Rallyback`;
}
function goto(view) {
  state.view = view;
  applyPreset(); renderTabs(); render(); syncURL(); setTitle(); window.scrollTo({ top: 0 });
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
  const page = { today: todayPage, mysteries: mysteriesPage, coming: comingPage, accuracy: accuracyPage, about: aboutPage,
    week: weekPage, work: workPage, search: searchPage, following: followingPage }[v.page];
  $("view").replaceChildren(...(page ? page() : proPage(v)).filter((x) => x != null && x !== false));   // never print an empty slot as "null"
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

// Today's sections wear the color of their reason, matching the chart and the story labels.
const SECTION_COLOR = { "In the news": "var(--s1)", "New releases": "var(--s2)", "Unexplained": "var(--s3)",
  "In memoriam": "var(--s4)", "Coming up": "var(--s5)", "Linked by one person": "var(--s3)", "Open cases": "var(--s3)",
  "Due for a comeback": "var(--s5)", "Big anniversaries": "var(--s5)",
  "Back every year": "var(--s5)", "Recently due": "var(--s5)",
  "Documentaries and biopics": "var(--s5)", "Warming up": "var(--s5)" };
function sectionHead(title, sub, moreLabel, moreView) {
  return h("div", { class: "section-head", style: SECTION_COLOR[title] ? `--sec:${SECTION_COLOR[title]}` : null },
    h("div", {}, h("h2", {}, title), sub ? h("p", {}, sub) : null),
    moreView ? h("button", { type: "button", class: "more", onclick: () => goto(moreView) }, `${moreLabel} →`) : null);
}

const SCORE_HELP = "Rallyback Score, 0 to 100: how big the jump is, how many people usually care, how many other places confirm it, and how long it has lasted.";
// The Rallyback Score is always just the number in a yellow circle; scoreKey() explains it.
const scoreDot = (n, big, label = "Rallyback Score") => (n == null ? null
  : h("span", { class: `score-dot${big ? " big" : ""}`, title: `${label}: ${n}. ${SCORE_HELP}`, "aria-label": `${label} ${n} out of 100`, role: "img" }, String(n)));
const scorePill = (r) => scoreDot(r.rally_score, true);
const scoreKey = () => h("p", { class: "score-key small muted" }, scoreDot(72),
  h("span", {}, h("b", {}, "Rallyback Score"), ", 0 to 100: how big the jump is, how many people usually care, how many other places confirm it, and how long it has lasted."));

function bigstat(r, withSpark = true) {
  return h("div", { class: "bigstat" }, scorePill(r), h("b", {}, mult(r)),
    h("span", {}, `its usual interest · ${STAGES[r.stage] ? STAGES[r.stage].toLowerCase() : `since ${short(r.spike_start)}`}`),
    withSpark ? sparkline(r, true) : null);
}

function link(r, ...kids) { return h("a", { href: `#w-${r.qid}`, onclick: (e) => { e.preventDefault(); focusCard(r.qid); } }, ...kids); }

// ---------- The Month in Comebacks (streamgraph) ----------
// Fixed type → palette slot mapping (validated order; never re-assigned by rank).
// The five reasons an old favorite comes back. One vocabulary for the chart, story labels, top 10 and filters.
// Colors: fixed validated palette slots, in this order (never re-assigned by rank).
const STREAM_TYPES = [
  { key: "news", label: "In the news", color: "var(--s1)", verdicts: ["ripple", "editor", "coverage"] },
  { key: "release", label: "New release", color: "var(--s2)", verdicts: ["derivative", "same-creator", "editor-release"] },
  { key: "unexplained", label: "Unexplained", color: "var(--s3)", verdicts: ["unexplained", "weak link", "lookup failed", "common thread"] },
  { key: "memoriam", label: "In memoriam", color: "var(--s4)", verdicts: ["death", "editor-death"] },
  { key: "anniversary", label: "Anniversary", color: "var(--s5)", verdicts: ["anniversary"] },
];
const SET_ASIDE = { seasonal: "Seasonal", "automated?": "Likely bots", "front page": "Wikipedia feature" };
const OTHER = { key: "other", label: "Set aside", color: "var(--s-other)" };
const threadExplained = (t) => !!(t.editor_note || t.person_jump || t.cause);
const NOTE_SECTION = { release: 1, death: 3, news: 0 };
const typeOf = (r) => (r.verdict === "common thread" && state.explainedByThread && state.explainedByThread.has(r.qid)
  ? STREAM_TYPES[0] : STREAM_TYPES.find((t) => t.verdicts.includes(r.verdict)) || OTHER);
const reasonOf = typeOf;
const kickerEl = (reason, label) => h("span", { class: "kicker" },
  h("i", { class: "sw", style: `background:${reason.color}`, "aria-hidden": "true" }), label || reason.label);

function streamData(days = 45, top = 15) {
  const { meta } = state.data;
  const end = meta.window_end;
  const dates = Array.from({ length: days }, (_, i) => addDays(end, i - days + 1));
  const rows = live().map((r) => {
    const off = daysBetween(r.spark_start, dates[0]);
    const extra = dates.map((_, i) => Math.max(0, (r.spark[off + i] || 0) - r.baseline));
    return { r, extra, total: extra.reduce((a, b) => a + b, 0), type: typeOf(r) };
  }).filter((x) => x.total > 0).sort((a, b) => b.total - a.total);
  const bands = rows.slice(0, top);
  const rest = rows.slice(top);
  // Group bands by type in palette order (so only validated-adjacent hues touch), biggest first within a type.
  bands.sort((a, b) => STREAM_TYPES.indexOf(a.type) - STREAM_TYPES.indexOf(b.type) || b.total - a.total);
  const dup = (b) => bands.filter((o) => o.r.label === b.r.label).length > 1;
  const series = bands.map((b) => ({ key: b.r.qid, label: dup(b) ? `${b.r.label} (${b.r.release_year})` : b.r.label,
    r: b.r, type: b.type, extra: b.extra, total: b.total }));
  // Smaller comebacks are left out rather than merged: combined, they'd swamp the stories.
  return { dates, series, omitted: rest.length };
}

function streamSection() {
  if (typeof d3 === "undefined") return null;
  const { dates, series, omitted } = streamData();
  if (!series.length) return null;
  const main = series.filter((x) => x.r);
  // Biggest single-day wave, for the headline.
  let best = null;
  for (const x of main) x.extra.forEach((v, i) => { if (!best || v > best.v) best = { x, v, i }; });
  const chart = h("div", { class: "stream-chart" });
  const tip = h("div", { class: "tip2", hidden: "" });
  chart.append(tip);
  const present = STREAM_TYPES.filter((t) => series.some((x) => x.type === t));
  if (series.some((x) => x.type === OTHER)) present.push(OTHER);
  const table = h("table", {},
    h("thead", {}, h("tr", {}, ["Title", "Story", "Biggest day", "Extra views that day", "Extra views, 45 days"].map((x) => h("th", {}, x)))),
    h("tbody", {}, series.map((x) => {
      const i = x.extra.indexOf(Math.max(...x.extra));
      return h("tr", {}, h("td", {}, x.r ? link(x.r, x.label) : x.label), h("td", {}, x.type.label),
        h("td", { class: "nowrap" }, short(dates[i])), h("td", { class: "num" }, fmt(x.extra[i])), h("td", { class: "num" }, fmt(x.total)));
    })));
  const sec = h("section", { class: "stream", "aria-label": "The Month in Comebacks" },
    h("div", { class: "stream-head" }, h("div", {},
      h("h2", {}, "The month in comebacks"),
      h("p", {}, "Each band is an old favorite getting extra interest. The thicker the band, the bigger the comeback; the color says why it's back.",
        best ? [" Biggest so far: ", h("b", {}, best.x.label), `, with ${fmt(best.v)} extra views on ${fmtDate(dates[best.i])}.`] : null))),
    h("div", { class: "legend", role: "list" }, present.map((t) =>
      h("span", { role: "listitem" }, h("i", { style: `background:${t.color}` }), t.label))),
    chart,
    h("p", { class: "stream-note" }, `The ${series.length} biggest comebacks of the last 45 days${omitted ? ` (${omitted} smaller ones not shown)` : ""}. Band thickness = extra daily views above each title's usual level. Hover or tap for numbers; click to read the story.`),
    h("details", {}, h("summary", {}, "View as table"), h("div", { class: "tablewrap" }, table)));
  requestAnimationFrame(() => drawStream(chart, tip, dates, series));
  return sec;
}

function drawStream(chart, tip, dates, series) {
  const W = chart.clientWidth || 800;
  const narrow = W < 600;
  const H = narrow ? 240 : 340, M = { t: 8, r: 4, b: 26, l: 4 };
  const rows = dates.map((d, i) => Object.fromEntries([["date", d], ...series.map((x) => [x.key, x.extra[i]])]));
  const stack = d3.stack().keys(series.map((x) => x.key)).offset(d3.stackOffsetWiggle).order(d3.stackOrderNone)(rows);
  const x = d3.scaleLinear().domain([0, dates.length - 1]).range([M.l, W - M.r]);
  const y = d3.scaleLinear().domain([d3.min(stack, (l) => d3.min(l, (d) => d[0])), d3.max(stack, (l) => d3.max(l, (d) => d[1]))]).range([H - M.b, M.t]);
  const area = d3.area().x((d, i) => x(i)).y0((d) => y(d[0])).y1((d) => y(d[1])).curve(d3.curveBasis);
  chart.querySelector("svg")?.remove();
  const svg = d3.create("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H).attr("role", "img")
    .attr("aria-label", `Streamgraph of extra daily views for the ${series.length} biggest comebacks over the last ${dates.length} days. A table view follows.`);
  // weekly ticks
  const ax = svg.append("g");
  ax.append("line").attr("class", "axis-line").attr("x1", M.l).attr("x2", W - M.r).attr("y1", H - M.b + 0.5).attr("y2", H - M.b + 0.5);
  dates.forEach((d, i) => {
    if ((dates.length - 1 - i) % (narrow ? 14 : 7)) return;
    const g = ax.append("g").attr("class", "tick").attr("transform", `translate(${x(i)},${H - M.b})`);
    g.append("line").attr("y2", 4);
    g.append("text").attr("y", 17).attr("text-anchor", i === dates.length - 1 ? "end" : "middle").text(short(d));
  });
  const bands = svg.append("g").selectAll("path").data(stack).join("path")
    .attr("class", "band").attr("d", area)
    // Each title gets its own tint of its story type's hue (full, then lighter), so neighbours read apart.
    .attr("fill", (l) => {
      const x = series[l.index];
      const k = series.filter((o, j) => j < l.index && o.type === x.type).length;
      const mix = [100, 78, 90, 68, 84, 60][k % 6];
      return mix === 100 ? x.type.color : `color-mix(in oklab, ${x.type.color} ${mix}%, var(--paper))`;
    })
    .on("click", (e, l) => { const r = series[l.index].r; if (r) focusCard(r.qid); });
  // Direct labels at each band's thickest point, skipping collisions.
  const placed = [];
  // Phones label what's big right now, at the right edge; wider screens label each band at its thickest point.
  const lastI = dates.length - 1;
  const endThick = (i) => y(stack[i][lastI][0]) - y(stack[i][lastI][1]);
  const labelled = series.map((s, i) => ({ s, i })).filter((o) => o.s.r)
    .sort((a, b) => (narrow ? endThick(b.i) - endThick(a.i) : b.s.total - a.s.total)).slice(0, narrow ? 6 : 12);
  const lg = svg.append("g");
  for (const { s, i } of labelled) {
    const layer = stack[i];
    let bi = 0, bt = 0;
    if (narrow) { bi = lastI; bt = endThick(i); }
    else layer.forEach((d, j) => { const t = y(d[0]) - y(d[1]); if (t > bt) { bt = t; bi = j; } });
    if (bt < (narrow ? 10 : 15)) continue;
    const text = s.label.length > 28 ? s.label.slice(0, 26) + "…" : s.label;
    // A label that would run off either edge lines up with that edge, so edge labels form a tidy column.
    const w = text.length * 6.6, right = x(bi) + w / 2 > W - M.r - 4, left = x(bi) - w / 2 < M.l + 4;
    const anchor = right ? "end" : left ? "start" : "middle";
    const tx = right ? W - M.r - 4 : left ? M.l + 4 : x(bi);
    const x0 = anchor === "end" ? tx - w : anchor === "start" ? tx : tx - w / 2;
    const cy = (y(layer[bi][0]) + y(layer[bi][1])) / 2;
    const box = [x0 - 4, cy - 9, x0 + w + 4, cy + 9];
    if (placed.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
    placed.push(box);
    lg.append("text").attr("class", "lbl").attr("x", tx).attr("y", cy + 4).attr("text-anchor", anchor).text(text);
  }
  const xhair = svg.append("line").attr("class", "xhair").attr("y1", M.t).attr("y2", H - M.b).attr("visibility", "hidden");
  const hide = () => { bands.classed("dim", false); xhair.attr("visibility", "hidden"); tip.hidden = true; };
  svg.on("pointermove pointerdown", (e) => {
    const [px, py] = d3.pointer(e);
    const i = Math.max(0, Math.min(dates.length - 1, Math.round(x.invert(px))));
    const v = y.invert(py);
    const li = stack.findIndex((l) => v >= l[i][0] && v <= l[i][1]);
    xhair.attr("x1", x(i)).attr("x2", x(i)).attr("visibility", "visible");
    if (li < 0) { bands.classed("dim", false); tip.hidden = true; return; }
    const s = series[li];
    bands.classed("dim", (l) => l.index !== li);
    tip.replaceChildren(h("b", {}, s.label), ` · ${short(dates[i])}: ${fmt(s.extra[i])} extra views`,
      h("small", {}, s.r ? `${s.type.label} · ${story(s.r).hed}` : "Smaller comebacks, combined"));
    tip.hidden = false;
    // Centered on the pointer; near the right edge it right-aligns to the pointer (opens leftward),
    // near the left edge it left-aligns, so it never gets squeezed into a narrow column.
    const tw = tip.offsetWidth;
    const shift = px + tw / 2 > W - 2 ? "-100%" : px - tw / 2 < 2 ? "0%" : "-50%";
    tip.style.left = `${px}px`;
    tip.style.top = `${py}px`;
    tip.style.transform = `translate(${shift}, calc(-100% - 12px))`;
  }).on("pointerleave", hide);
  chart.append(svg.node());
}

let _resizeT;
window.addEventListener("resize", () => {
  clearTimeout(_resizeT);
  _resizeT = setTimeout(() => { if (state.view === "today" && document.querySelector(".stream-chart")) render(); }, 200);
});

// ---------- Today ----------
// How it works: always open on wide screens. On phones it's one tappable line,
// open only on someone's first visit (remembered in this browser, if it allows).
const PHONE = matchMedia("(max-width: 720px)");
const store = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode: fine */ } } };
function howItWorks() {
  // Decided once per page load, so it stays open while a first-time reader moves between pages.
  if (howItWorks.first == null) { howItWorks.first = !store.get("rb-how-seen"); store.set("rb-how-seen", "1"); }
  const firstVisit = howItWorks.first;
  const box = h("details", { class: "how", "aria-label": "How The Rallyback works", open: !PHONE.matches || firstVisit ? "" : null },
    h("summary", {}, "How it works"),
    h("ol", {},
      h("li", {}, h("b", {}, "We watch."), " Every day we track how much attention older movies, shows, songs, games and books are getting."),
      h("li", {}, h("b", {}, "We spot comebacks."), " When an old favorite suddenly gets far more attention than usual, it's back."),
      h("li", {}, h("b", {}, "We find out why."), " A new release, the news, a death, an anniversary. When we can't tell, it's ", h("i", {}, "Unexplained"), ", and you can tip us off."),
      h("li", {}, h("b", {}, "We score them."), " The number in the yellow circle ", scoreDot(72), " is the Rallyback Score, 0 to 100: the size of the jump, how many people usually care, confirmation elsewhere and staying power.")),
    h("button", { type: "button", class: "how-close", onclick: () => { box.open = false; } }, "Got it ×"));
  // Rotating a tablet or resizing past the phone width shouldn't leave it folded on a wide screen.
  PHONE.addEventListener("change", (e) => { if (!e.matches) box.open = true; });
  return box;
}

// ---------- one row per cause ----------
// Titles that came back for the same known reason (an editor's note, a new release, a death,
// the same creator, an explained "same person" group) read as one story in lists.
// Unexplained coincidences stay separate: grouping them would imply a cause we haven't found.
// Each title belongs to one group at most: editor's note first, then the largest shared trigger, then the largest thread.
function buildCauseGroups() {
  const D = state.data, R = state.byQid, groupOf = new Map(), groups = [];
  const claim = (key, qids, make) => {
    const free = [...new Set(qids)].filter((q) => R[q] && !groupOf.has(q));
    if (free.length < 2) return;
    const g = { key, works: free.map((q) => R[q]) };
    Object.assign(g, make(free));
    groups.push(g); free.forEach((q) => groupOf.set(q, g));
  };
  const notes = new Map();
  for (const r of D.results) if (r.editor_note) notes.set(r.editor_note.id, [...(notes.get(r.editor_note.id) || []), r.qid]);
  for (const t of D.common_threads || []) if (t.editor_note) notes.set(t.editor_note.id, [...(notes.get(t.editor_note.id) || []), ...t.works.map((w) => w.qid)]);
  for (const [id, qids] of notes) {
    const note = (R[qids.find((q) => R[q] && R[q].editor_note)] || {}).editor_note
      || (D.common_threads || []).find((t) => t.editor_note && t.editor_note.id === id).editor_note;
    // A note about a new release takes in the titles the site already linked to that release,
    // so the films and the novels behind one new film are one story.
    const same = note.new_work ? (D.shared_triggers || []).filter((t) => t.qid === note.new_work).flatMap((t) => t.works) : [];
    const release = same.length ? (D.shared_triggers || []).find((t) => t.qid === note.new_work) : null;
    const reason = STREAM_TYPES[NOTE_SECTION[note.cause] ?? 0];
    claim(`note-${id}`, [...qids, ...same], (free) => {
      const ws = free.map((q) => R[q]);
      const nw = release ? release.text.split(": ").slice(1).join(": ").replace(/ \((upcoming|attention rose before release)\)$/, "") : null;
      return { story: { reason, kicker: reason.label,
        hed: note.headline ? note.headline.replace("{n}", ws.length) : nw ? `${oldNames(ws)} are back, thanks to ${nw}` : `${oldNames(ws)} are back`,
        dek: `${note.text} ${ws.length} older titles connected to it started rising together.` }, sources: () => [sourceLine(note)], note };
    });
  }
  const bySize = (xs, n) => [...xs].sort((a, b) => n(b) - n(a));
  // A title goes to the group that tells its own story first: A Christmas Carol (1999) is back because
  // Patrick Stewart died, so that group claims it before the one about a new Ebenezer film.
  const own = (t) => t.works.filter((q) => R[q] && R[q].verdict === t.type).length;
  [...(D.shared_triggers || [])].sort((a, b) => own(b) - own(a) || b.works.length - a.works.length).forEach((t, i) =>
    claim(`shared-${i}`, t.works, (free) => ({ story: sharedStory({ ...t, works: free }), sources: () => [] })));
  bySize((D.common_threads || []).filter(threadExplained), (t) => t.works.length).forEach((t, i) =>
    claim(`thread-${i}`, t.works.map((w) => w.qid), (free) => {
      const tt = { ...t, works: t.works.filter((w) => free.includes(w.qid)) };
      return { story: threadStory(tt), sources: () => threadSources(tt), t: tt };
    }));
  for (const g of groups) {
    g.works.sort((a, b) => b.score - a.score);
    g.id = `g-${g.key.replace(/[^\w-]/g, "_")}`;
  }
  state.groupOf = groupOf;
}

// A whole group as one list row. The titles are inside, each with its own numbers and sources.
function groupCard(g, members) {
  const top = topPictured(members) || null, best = members[0];
  const photo = top ? pic(null, top.image, top.label, 240, top.image_of) : null;
  const scores = members.map((r) => r.rally_score).filter((x) => x != null);
  const inside = h("details", { class: "more-info group-members" },
    h("summary", {}, `The ${members.length} titles`), ...members.map((r) => card(r, false, true)), sourcesBox(g.sources()));
  return h("article", { class: `card group${photo ? " has-media" : ""}`, id: g.id },
    photo,
    h("div", {},
      kickerEl(g.story.reason, g.story.kicker),
      h("h3", { class: "hed" }, h("a", { href: `#${g.id}`, onclick: (e) => { e.preventDefault(); inside.open = !inside.open; } }, g.story.hed)),
      h("p", { class: "dek" }, g.story.dek),
      h("div", { class: "tags" },
        h("span", { class: "tagx" }, `${members.length} titles`),
        scores.length ? scoreDot(Math.max(...scores), false, "Top Rallyback Score in this group") : null,
        best.stage === "emerging" ? h("span", { class: "tagx hot" }, "Just starting") : null),
      inside));
}

// Collapse a sorted list of titles into rows: a group sits where its best-placed member would.
// A group with only one member left after filters shows as that title alone.
function toRows(list) {
  const members = new Map();
  for (const r of list) { const g = state.groupOf && state.groupOf.get(r.qid); if (g) members.set(g, [...(members.get(g) || []), r]); }
  const rows = [], done = new Set();
  for (const r of list) {
    const g = state.groupOf && state.groupOf.get(r.qid);
    if (!g || members.get(g).length < 2) { rows.push({ r }); continue; }
    if (done.has(g)) continue;
    done.add(g); rows.push({ g, members: members.get(g) });
  }
  return rows;
}

// Title chips for a group, capped so long groups stay readable.
function workChips(works, cap = 12) {
  const ws = [...works].sort((a, b) => (b.score || 0) - (a.score || 0));
  return h("div", { class: "chips" }, ws.slice(0, cap).map((w) =>
    h("a", { class: "chip", href: `#w-${w.qid}`, onclick: (e) => { e.preventDefault(); focusCard(w.qid); } }, `${w.label} (${w.release_year})`)),
    ws.length > cap ? h("span", { class: "chip more-chip" }, `+${ws.length - cap} more`) : null);
}

function todayPage() {
  const L = live();
  if (!L.length) return [howItWorks(), h("p", { class: "status" }, "A quiet day: no comebacks in this edition.")];
  // Lead with a story people will recognise: a real everyday audience, ideally a picture.
  const known = L.slice(0, 25).filter((r) => r.baseline >= 100);
  // Prefer a story we can actually tell (a named cause) over a mystery.
  const told = (r) => ["editor", "editor-release", "editor-death", "death", "derivative", "ripple", "same-creator", "anniversary"].includes(r.verdict);
  const lead = known.find((r) => told(r) && r.image) || known.find((r) => r.image) || known[0] ||
    L.find((r) => r.image) || L[0];
  const rest = L.filter((r) => r !== lead);
  const st = story(lead);
  const is = (key) => (r) => reasonOf(r).key === key;
  const threads = state.data.common_threads || [];
  const newsThreads = threads.filter((t) => t.editor_note || t.person_jump || t.cause);
  const openThreads = threads.filter((t) => !newsThreads.includes(t));
  const out = [
    howItWorks(),
    streamSection(),
    h("section", { class: "front" },
      withPic("article", "lead", pic(null, lead.image, lead.label, 1200, lead.image_of),
        kickerEl(st.reason, st.kicker),
        h("h2", { class: "hed" }, link(lead, st.hed)),
        h("p", { class: "dek" }, dekWithLink(st.dek, lead.cause, lead.cause_link, lead.editor_note)),
        bigstat(lead),
        sourcesBox(sourcesFor(lead))),
      h("aside", { class: "index" },
        h("h2", {}, "Top 10 comebacks"),
        h("p", {}, "Ranked by Rallyback Score, the number in the yellow circle."),
        h("ol", {}, topStories(lead, rest, 10).map(({ r, g }) => h("li", {}, h("div", {},
          h("div", { class: "t" }, g ? h("a", { href: `#${g.id}`, onclick: (e) => { e.preventDefault(); focusGroup(g); } }, oldNames(g.works))
            : link(r, r.label)),
          h("div", { class: "s" }, scoreDot(r.rally_score), " ",
            g ? `${g.works.length} titles · ${g.story.kicker}` : `${mult(r)} usual interest · ${story(r).kicker}`))))))),
  ];
  // Each section is one grid of same-shaped cards: stories about several titles (one per cause)
  // and stories about one title, biggest first. The lead's own story isn't repeated.
  const leadGroup = state.groupOf && state.groupOf.get(lead.qid);
  const causeGroups = [...new Set(state.groupOf ? state.groupOf.values() : [])].filter((g) => g !== leadGroup);
  // Unexplained "same person" groups aren't causes, so they're shown here as their own stories.
  const openGroups = openThreads.map((t) => {
    const ws = t.works.map((w) => state.byQid[w.qid]).filter((w) => w && !(state.groupOf && state.groupOf.has(w.qid)));
    return ws.length >= MIN_LINKED ? { works: ws.sort((a, b) => b.score - a.score), story: threadStory({ ...t, works: t.works.filter((w) => ws.includes(state.byQid[w.qid])) }), sources: () => threadSources(t), t } : null;
  }).filter(Boolean);
  const inOpen = new Set(openGroups.flatMap((g) => g.works.map((w) => w.qid)));
  const best = (x) => (x.works ? x.works[0].score : x.score);
  const section = (key, title, sub, more, cap = 6) => {
    const groups = (key === "unexplained" ? openGroups : causeGroups.filter((g) => g.story.reason && g.story.reason.key === key));
    const singles = rest.filter(is(key)).filter((r) => !(state.groupOf && state.groupOf.has(r.qid)) && !inOpen.has(r.qid));
    const items = [...groups, ...singles].sort((a, b) => best(b) - best(a)).slice(0, cap)
      .map((x) => (x.works ? groupStoryCard(x) : storyCard(x)));
    if (!items.length) return;
    // The section title already says why they're back; the label on each story would repeat it.
    items.forEach((el) => el.querySelector(".kicker")?.remove());
    out.push(sectionHead(title, sub, more && more[0], more && more[1]));
    out.push(h("div", { class: "grid", style: SECTION_COLOR[title] ? `--sec:${SECTION_COLOR[title]}` : null }, items));
  };
  section("news", "In the news", "Old favorites riding news about a star, a story or a franchise.");
  section("release", "New releases", "A sequel, remake or new work sends fans back to the original.");
  section("memoriam", "In memoriam", "A death sends people back to the work.");
  section("unexplained", "Unexplained", "Big comebacks we can't explain yet. Know why? Tell us.", ["All unexplained", "mysteries"]);
  const cu = state.data.coming_up || {};
  if (soonReleases(cu).length || soonBirthdays(cu).length) {
    out.push(sectionHead("Coming up", "Comebacks we expect: originals with a sequel or remake on the way, and big anniversaries.", "Full calendar", "coming"));
    if (soonReleases(cu).length) out.push(h("h3", { class: "rail-head" }, "New releases on the way"), h("div", { class: "rail" }, pictured(soonReleases(cu)).slice(0, 10).map(derivMini)));
    if (soonBirthdays(cu).length) out.push(h("h3", { class: "rail-head" }, "Big anniversaries"), h("div", { class: "rail" }, bigAnniversaries(soonBirthdays(cu), 10).map(annMini)));
  }
  out.push(newsletterBox());
  out.push(sectionHead(`All comebacks (${state.data.results.length})`, "Search, filter by reason, and dig into the numbers."));
  out.push(listSection());
  return out.filter(Boolean);
}

// Top N distinct stories: one entry per cause, never the lead's own story again.
function topStories(lead, rest, n) {
  const seen = new Set([state.groupOf && state.groupOf.get(lead.qid)].filter(Boolean)), out = [];
  for (const r of rest) {
    const g = state.groupOf && state.groupOf.get(r.qid);
    if (g && seen.has(g)) continue;
    if (g) seen.add(g);
    out.push({ r, g });
    if (out.length === n) break;
  }
  return out;
}

function threadFeature(t) {
  const st = threadStory(t), top = topPictured(t.works.map((w) => state.byQid[w.qid]).filter(Boolean));
  return withPic("article", "feature", top ? pic(null, top.image, top.label, 300, top.image_of)
      : pic(null, t.image, t.name, 300, t.name),
    h("div", {}, kickerEl(st.reason, st.kicker),
      h("h3", { class: "hed" }, hedLink(topOf(t.works.map((w) => state.byQid[w.qid]).filter(Boolean)), st.hed)), h("p", { class: "dek" }, st.dek),
      workChips(t.works.map((w) => state.byQid[w.qid]).filter(Boolean)),
      !threadExplained(t) && topOf(t.works.map((w) => state.byQid[w.qid]).filter(Boolean))
        ? h("div", {}, tipLink(topOf(t.works.map((w) => state.byQid[w.qid]).filter(Boolean)))) : null,
      sourcesBox(threadSources(t))));
}

// Every story card has the same shape: picture slot, headline, short text, then a footer
// (score, numbers, sources) pinned to the bottom so footers line up across a row.
// No photo, or one that fails to load → a plain panel with the year, so the slot is never empty.
function photoOrPanel(image, alt, of, year, kind) {
  const panel = () => h("div", { class: "media panel", "aria-hidden": "true" }, h("b", {}, year || ""), h("span", {}, kind || ""));
  return pic(null, image, alt, 640, of, panel) || panel();
}
function storyCard(r) {
  const st = story(r);
  return withPic("article", "story", photoOrPanel(r.image, r.label, r.image_of, r.release_year, noun(r.kind)),
    kickerEl(st.reason, st.kicker),
    h("h3", { class: "hed" }, link(r, st.hed)),
    h("p", { class: "dek" }, dekWithLink(st.dek, r.cause, r.cause_link, r.editor_note)),
    h("div", { class: "story-foot" },
      bigstat(r),
      h("div", { class: "foot-row" }, confidenceTag(r), followBtn(r.qid, plain(r.label))),
      sourcesBox(sourcesFor(r)),
      isOpen(r) ? h("div", {}, tipLink(r)) : null));
}

// Several titles back for one reason, in the same card shape as a single title.
// Its chart is their combined interest; the titles are one tap away.
function combinedSpark(ws) {
  const n = ws[0].spark.length;
  if (!ws.every((w) => w.spark && w.spark.length === n && w.spark_start === ws[0].spark_start)) return null;
  const vals = ws[0].spark.map((_, i) => ws.reduce((t, w) => t + w.spark[i], 0));
  const peak = Math.max(...vals), pi = vals.indexOf(peak);
  const start = ws.map((w) => w.spike_start).sort()[0];
  return sparkline({ spark: vals, baseline: ws.reduce((t, w) => t + w.baseline, 0), spark_start: ws[0].spark_start,
    spike_start: start, peak, peak_day: addDays(ws[0].spark_start, pi), label: `these ${ws.length} titles combined` }, true);
}
function groupStoryCard(g) {
  const ws = g.works, top = topPictured(ws) || null, best = topOf(ws);
  const scores = ws.map((w) => w.rally_score).filter((x) => x != null);
  const years = ws.map((w) => +w.release_year).filter(Boolean);
  const span = years.length ? (Math.min(...years) === Math.max(...years) ? `${years[0]}` : `${Math.min(...years)}–${Math.max(...years)}`) : "";
  const headLink = g.id
    ? h("a", { href: `#${g.id}`, onclick: (e) => { e.preventDefault(); focusGroup(g); } }, g.story.hed) : hedLink(best, g.story.hed);
  const open = g.story.reason && g.story.reason.key === "unexplained";
  return withPic("article", "story", photoOrPanel(top && top.image, top && top.label, top && top.image_of, span, `${ws.length} titles`),
    kickerEl(g.story.reason, g.story.kicker),
    h("h3", { class: "hed" }, headLink),
    h("p", { class: "dek" }, dekWithLink(g.story.dek, g.t && g.t.cause, g.t && g.t.cause_link, g.note || (g.t && g.t.editor_note))),
    h("div", { class: "story-foot" },
      h("div", { class: "bigstat" }, scoreDot(scores.length ? Math.max(...scores) : null, true, "Top Rallyback Score in this group"),
        h("b", {}, String(ws.length)), h("span", {}, `titles back at once · biggest ${mult(best)}`), combinedSpark(ws)),
      h("details", { class: "more-info sources" }, h("summary", {}, `The ${ws.length} titles`), workChips(ws), ...(g.sources() || []).filter(Boolean)),
      open ? h("div", {}, tipLink(best)) : null));
}

const NEWREL = { "adaptation of": "a new adaptation", "sequel to": "the sequel", "new entry in the series of": "a new entry in the series",
  "remake of": "the remake", "spin-off of": "a spin-off" };
// Drop Wikipedia's disambiguation tag: "Prince of Persia (1989 video game)" → "Prince of Persia".
// Rails show pictured items first (stable, so date order holds within each group).
const pictured = (cs) => [...cs].sort((a, b) => !(a.old_image || a.new_image) - !(b.old_image || b.new_image));
// Anniversaries in date order. Rails keep the biggest n (by everyday audience), then show them by date.
const byDate = (xs) => [...xs].sort((a, b) => a.date.localeCompare(b.date));
const bigAnniversaries = (xs, n) => byDate([...xs].sort((a, b) => (b.audience || 0) - (a.audience || 0)).slice(0, n));
const plain = (label) => label.replace(/ \((?:\d{4} )?(?:video game|film|album|song|novel|book|TV series|game|musical|play|manga|comics?)\)$/i, "");
function derivMini(c) {
  return withPic("article", "mini", c.old_image ? pic(null, c.old_image, c.old_label, 480, c.old_image_of)
    : c.new_image ? pic(null, c.new_image, c.new_label, 480, c.new_label) : null,
    h("div", { class: "when" }, `Comeback due ${short(c.date)}`),
    h("h3", { class: "hed" }, hedLink(state.byQid[c.old], plain(c.old_label)), ` (${c.old_release.slice(0, 4)})`),
    h("p", { class: "dek" }, `${NEWREL[c.rel] ? NEWREL[c.rel][0].toUpperCase() + NEWREL[c.rel].slice(1) : "A new release"}, ${c.new_label}, arrives ${fmtDate(c.date)}.`),
    outlookEl(c.prediction));
}
function annMini(a) {
  return withPic("article", "mini", pic(null, a.image, a.label, 480, a.image_of),
    h("div", { class: "when" }, short(a.date)),
    h("h3", { class: "hed" }, hedLink(state.byQid[a.qid], `${plain(a.label)} turns ${a.years}`)),
    h("p", { class: "dek" }, `${noun(a.kind)[0].toUpperCase()}${noun(a.kind).slice(1)}, ${a.release.slice(0, 4)}${a.audience ? ` · ${fmt(a.audience)} views on a normal day` : ""}`),
    outlookEl(a.prediction));
}

// ---------- section pages (Unexplained, Coming up) ----------
// One template: an intro, a contents line with counts, then each section as a heading band,
// the top 6 as cards, and the rest in a table showing 12 rows with Show all / Show fewer.
const secId = (t) => `sec-${t.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
// A part with `toggle` opens and closes a hidden panel (by id) instead of jumping to a section.
function contentsLine(parts) {
  return h("p", { class: "contents" }, parts.filter((x) => x.n).map((x, i) => [i ? h("span", { class: "sep" }, " · ") : null,
    x.toggle
      ? h("a", { href: `#${x.toggle}`, class: "toggle", "aria-expanded": "false", "aria-controls": x.toggle, onclick: (e) => {
          e.preventDefault(); const a = e.currentTarget, panel = $(x.toggle); if (!panel) return;
          const open = a.getAttribute("aria-expanded") !== "true";
          panel.hidden = !open; a.setAttribute("aria-expanded", String(open)); } },
        h("b", {}, fmt(x.n)), ` ${x.label}`)
      : h("a", { href: `#${secId(x.title)}`, onclick: (e) => { e.preventDefault(); $(secId(x.title))?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }); } },
        h("b", {}, fmt(x.n)), ` ${x.label}`)]));
}
// A table row whose title opens that item's card right under it (and closes it again).
// One card open at a time per list. The card stays on this page: its headline isn't a link away.
function openableRow(item, row, card, span) {
  const tr = row(item), t = tr.querySelector("b.t");
  if (!t) return tr;
  const a = h("a", { href: "#", class: "row-open", "aria-expanded": "false" }, t.textContent);
  a.addEventListener("click", (e) => {
    e.preventDefault();
    const body = tr.parentNode, wasOpen = a.getAttribute("aria-expanded") === "true";
    body.querySelectorAll("tr.card-row").forEach((x) => x.remove());
    body.querySelectorAll('a.row-open[aria-expanded="true"]').forEach((x) => x.setAttribute("aria-expanded", "false"));
    if (wasOpen) return;
    const c = noKicker(card(item));
    c.querySelectorAll(".hed a").forEach((x) => x.replaceWith(x.textContent));
    const detail = h("tr", { class: "card-row" }, h("td", { colspan: String(span) }, c));
    tr.after(detail);
    a.setAttribute("aria-expanded", "true");
    if (detail.getBoundingClientRect().bottom > innerHeight) detail.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  t.replaceChildren(a);
  return tr;
}

// Wide screens: the top items as cards, the rest in a table. Phones: no cards, just the full list.
function pageSection(title, sub, { cards, rest, all, card, row: plainRow }, columns, noun) {
  if (!all.length) return [];
  const row = (item) => openableRow(item, plainRow, card, columns.length);
  const head = sectionHead(title, sub);
  head.id = secId(title);
  const sec = SECTION_COLOR[title] ? `--sec:${SECTION_COLOR[title]}` : null;
  return [head,
    h("div", { class: "wide-only", style: sec },
      h("div", { class: "grid", style: SECTION_COLOR[title] ? `--sec:${SECTION_COLOR[title]}` : null }, cards.map(card).map(noKicker)),
      rest.length ? h("h3", { class: "rail-head table-head" }, `More ${noun}`) : null,
      rest.length ? table(columns, rest.map(row), 12, noun) : null),
    h("div", { class: "narrow-only", style: sec }, table(columns, all.map(row), 12, noun))];
}
const workCell = (r, label, sub) => h("td", {}, h("b", { class: "t" }, label), h("div", { class: "small muted" }, sub));
const scoreCell = (n) => h("td", { class: "num" }, scoreDot(n));

// Outlook: how big a comeback to expect and how likely it is, learned from past cases like it.
const fmtX = (x) => `${x >= 10 ? Math.round(x) : Math.round(x * 10) / 10}×`;
const OUTLOOK_HELP = "Chance = how often similar past cases reached at least 2× their usual interest within a week of the date.";
const outlookEl = (p) => (p ? h("p", { class: "outlook", title: `${p.basis}. ${OUTLOOK_HELP}` },
  h("b", {}, `Expect about ${fmtX(p.expected)}`), ` its usual interest${p.chance != null ? ` · ${Math.round(p.chance * 100)}% chance` : p.record ? ` · back ${p.record}` : ""}`) : null);
const outlookCell = (p) => h("td", { class: "num nowrap", title: p ? `${p.basis}. ${OUTLOOK_HELP}` : null },
  p ? `${fmtX(p.expected)}${p.chance != null ? ` · ${Math.round(p.chance * 100)}%` : p.record ? ` · ${p.record}` : ""}` : "–");

function derivCard(c) {
  const old = state.byQid[c.old];
  return withPic("article", "story", photoOrPanel(c.old_image || c.new_image, c.old_label, c.old_image ? c.old_image_of : c.new_label, c.old_release.slice(0, 4), c.old_kind),
    h("div", { class: "when" }, `Comeback due ${short(c.date)}`),
    h("h3", { class: "hed" }, hedLink(old, plain(c.old_label)), ` (${c.old_release.slice(0, 4)})`),
    h("p", { class: "dek" }, `${NEWREL[c.rel] ? NEWREL[c.rel][0].toUpperCase() + NEWREL[c.rel].slice(1) : "A new release"}, ${c.new_label}, arrives ${fmtDate(c.date)}.`),
    outlookEl(c.prediction));
}
function annCard(a) {
  return withPic("article", "story", photoOrPanel(a.image, a.label, a.image_of, a.release.slice(0, 4), a.kind),
    h("div", { class: "when" }, short(a.date)),
    h("h3", { class: "hed" }, hedLink(state.byQid[a.qid], `${plain(a.label)} turns ${a.years}`)),
    h("p", { class: "dek" }, `${noun(a.kind)[0].toUpperCase()}${noun(a.kind).slice(1)}, ${a.release.slice(0, 4)}${a.audience ? ` · ${fmt(a.audience)} views on a normal day` : ""}`),
    outlookEl(a.prediction));
}
function subjectCard(sj) {
  const top = sj.works[0];
  return withPic("article", "story", photoOrPanel(sj.image || (top && top.image), sj.who_label, sj.image ? sj.who_label : null,
    sj.date.slice(0, 4), "documentary or biopic"),
    h("div", { class: "when" }, `Arrives ${short(sj.date)}`),
    h("h3", { class: "hed" }, `${sj.who_label}'s work is due for a comeback`),
    h("p", { class: "dek" }, `${sj.new_label}, a new film or series about ${sj.who_label}, arrives ${fmtDate(sj.date)}. Their best-known older work: `,
      ...sj.works.flatMap((w, i) => [i ? ", " : "", titleLink(w.qid, plain(w.label))]), sj.more ? ` and ${sj.more} more.` : "."));
}
function warmCard(w) {
  const r = { spark: w.trend, baseline: w.usual, spark_start: addDays(w.date, -20), spike_start: addDays(w.date, -6),
    peak: Math.max(...w.trend), peak_day: w.date, label: w.label };
  return withPic("article", "story", photoOrPanel(w.image, w.label, w.image_of, w.release.slice(0, 4), w.kind),
    h("div", { class: "when" }, "Climbing"),
    h("h3", { class: "hed" }, titleLink(w.qid, plain(w.label)), ` (${w.release.slice(0, 4)})`),
    h("p", { class: "dek" }, `The ${noun(w.kind)} is at ${fmtX(w.ratio)} its usual interest this week, up every day, and higher than the week before. Not a comeback yet.`),
    h("div", { class: "story-foot" }, sparkline(r, true)));
}
function seasonCard(a) {
  return withPic("article", "story", photoOrPanel(a.image, a.label, a.image_of, a.release.slice(0, 4), a.kind),
    h("div", { class: "when" }, `Back around ${short(a.date)}`),
    h("h3", { class: "hed" }, hedLink(state.byQid[a.qid], plain(a.label)), ` (${a.release.slice(0, 4)})`),
    h("p", { class: "dek" }, `${a.holiday ? `A ${a.holiday} favorite: ` : ""}people come back to this ${noun(a.kind)} around the same time every year.`),
    outlookEl(a.prediction));
}

// ---------- Case closed ----------
// Mysteries from the past week that the nightly run (or an editor, often thanks to a reader tip) has now explained.
function causeLine(r) {
  if (r.editor_note) return r.editor_note.text;
  const st = story(r);
  const keep = st.dek.split(/(?<=\.)\s+/).filter((x) => !/^They all started rising|its usual interest|far more interest than usual/.test(x));
  return keep.length ? keep.join(" ") : st.hed;
}
function caseClosed() {
  const solved = (state.data.solved || []).map((x) => ({ ...x, r: state.byQid[x.qid] })).filter((x) => x.r);
  if (!solved.length) return null;
  const items = solved.map(({ r, via }) => {
    const li = h("li", {});
    const a = h("a", { href: "#", class: "row-open", "aria-expanded": "false" }, plain(r.label));
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const open = a.getAttribute("aria-expanded") === "true";
      li.parentNode.querySelectorAll(".closed-card").forEach((x) => x.remove());
      li.parentNode.querySelectorAll('a.row-open[aria-expanded="true"]').forEach((x) => x.setAttribute("aria-expanded", "false"));
      if (open) return;
      const c = noKicker(storyCard(r));
      c.querySelectorAll(".hed a").forEach((x) => x.replaceWith(x.textContent));
      li.append(h("div", { class: "closed-card" }, c));
      a.setAttribute("aria-expanded", "true");
    });
    const reason = reasonOf(r);
    li.append(h("b", {}, a), ` (${r.release_year}) `,
      h("span", { class: "closed-reason" }, h("i", { class: "sw", style: `background:${reason.color}`, "aria-hidden": "true" }), reason.label),
      h("div", { class: "closed-why" }, causeLine(r), via ? h("span", { class: "closed-via" }, ` Solved thanks to a ${via}.`) : null));
    return li;
  });
  // Hidden until opened from the "solved this week" link in the contents line.
  return h("section", { class: "case-closed", id: "case-closed", hidden: "", "aria-label": "Mysteries solved this week" },
    h("h2", {}, "Case closed"),
    h("p", { class: "small muted" }, "Mysteries from the past week that we've now explained. They've moved to their sections on Today."),
    h("ul", { class: "closed-list" }, items));
}

// ---------- Mysteries ----------
// On a page that is all one reason, the reason label on each card would only repeat the page title.
const noKicker = (el) => { el.querySelector(".kicker")?.remove(); return el; };
function mysteriesPage() {
  // Only what we can't explain: no named cause, no likely cause, no explained group.
  const threads = (state.data.common_threads || []).filter((t) => !threadExplained(t) && t.works.length >= MIN_LINKED);
  const inThreads = new Set(threads.flatMap((t) => t.works.map((w) => w.qid)));
  const L = live().filter((r) => reasonOf(r).key === "unexplained" && !inThreads.has(r.qid))
    .sort((a, b) => b.spike_start.localeCompare(a.spike_start) || b.score - a.score);
  const groups = threads.map((t) => {
    const ws = t.works.map((w) => state.byQid[w.qid]).filter(Boolean).sort((a, b) => b.score - a.score);
    return ws.length >= MIN_LINKED ? { t, works: ws, story: threadStory(t), sources: () => threadSources(t) } : null;
  }).filter(Boolean).sort((a, b) => b.works[0].score - a.works[0].score);
  const caseRow = (r) => h("tr", {},
    h("td", { class: "nowrap" }, short(r.spike_start)),
    // On phones the tip link sits under the title instead of in its own column, so the table fits.
    h("td", {}, h("b", { class: "t" }, plain(r.label)), h("div", { class: "small muted" }, `${r.kind}, ${r.release_year}`),
      h("div", { class: "tip-inline" }, tipLink(r, "Tell us →"))),
    h("td", { class: "num" }, mult(r)),
    scoreCell(r.rally_score),
    h("td", { class: "nowrap tipcol" }, tipLink(r, "Tell us →")));
  const groupRow = (g) => h("tr", {},
    h("td", { class: "nowrap" }, short(g.t.around)),
    workCell(null, g.t.name, oldNames(g.works)),
    h("td", { class: "num" }, String(g.works.length)),
    scoreCell(Math.max(...g.works.map((w) => w.rally_score || 0))));
  return [
    h("p", { class: "intro" }, "Old favorites that are suddenly back, and we can't tell why yet. Know why? Tell us."),
    contentsLine([{ n: L.length, label: "open cases", title: "Open cases" }, { n: groups.length, label: "linked by one person", title: "Linked by one person" },
      { n: (state.data.solved || []).filter((x) => state.byQid[x.qid]).length, label: "solved this week", toggle: "case-closed" }]),
    caseClosed(),
    scoreKey(),
    mysteryMap(L),
    ...pageSection("Open cases", "Comebacks we can't explain yet, newest first.",
      { cards: L.slice(0, 6), rest: L.slice(6), all: L, card: storyCard, row: caseRow }, ["Started", "Work", "× usual", "Score", ""], "open cases"),
    ...pageSection("Linked by one person", "Several titles with the same person, all rising at the same time, for no reason we can find.",
      { cards: groups.slice(0, 6), rest: groups.slice(6), all: groups, card: groupStoryCard, row: groupRow }, ["Started", "Person", "Titles", "Score"], "groups"),
  ].filter(Boolean);
}

// ---------- pro views ----------
function proPage(v) {
  const panels = (v.panels || []).map(panel).filter(Boolean);
  const pros = Object.keys(VIEWS).filter((k) => VIEWS[k].pro);
  return [
    h("div", { class: "pro-head" }, h("span", { class: "kicker" }, "For professionals"),
      h("div", { class: "chips", role: "group", "aria-label": "Professional views" }, pros.map((k) =>
        h("button", { type: "button", class: "chip", "aria-pressed": String(k === state.view), onclick: () => goto(k) }, VIEWS[k].label)))),
    h("p", { class: "intro" }, v.intro),
    v.feeds ? feedStrip(v.feeds) : null,
    ...panels,
    sectionHead("Comebacks", null),
    listSection(),
  ].filter(Boolean);
}

function panel(name) {
  const cu = state.data.coming_up || {};
  if (name === "threads") {
    const t = state.data.common_threads || [];
    return t.length ? h("div", {}, sectionHead("Linked by one person", "Several titles with the same person, all rising at the same time."), t.map(threadFeature)) : null;
  }
  if (name === "coming-mini" && soonReleases(cu).length)
    return h("div", {}, sectionHead("Coming Soon", "Sequels, adaptations and remakes of older works due soon.", "Full calendar", "coming"),
      h("div", { class: "rail" }, pictured(soonReleases(cu)).slice(0, 10).map(derivMini)));
  if (name === "anniversaries-mini" && soonBirthdays(cu).length)
    return h("div", {}, sectionHead("Anniversaries Ahead", "Round-number birthdays in the next 60 days, biggest audiences first.", "Full calendar", "coming"),
      h("div", { class: "rail" }, bigAnniversaries(soonBirthdays(cu), 10).map(annMini)));
  if (name === "downloads") {
    const run = $("run").value;
    return h("div", { class: "block" }, sectionHead("Downloads", "Data is derived from CC0 sources. Please cite as “The Rallyback (open data from Wikimedia and Wikidata)”."),
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
    " · ", h("button", { type: "button", class: "linkish", onclick: () => goto("about") }, "all feeds"));
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
    [["score", "Biggest comeback"], ["lift", "Biggest jump"], ["recent", "Most interest now"], ["start", "Newest"], ["age", "Oldest work"]]
      .map(([k, l]) => h("option", { value: k, selected: state.sort === k ? "" : null }, `Sort: ${l}`)));
  sortSel.addEventListener("change", (e) => { state.sort = e.target.value; renderList(); });
  const q = h("input", { id: "q", type: "search", placeholder: "Search titles, people, causes…", "aria-label": "Search" });
  q.addEventListener("input", (e) => { state.q = e.target.value.trim().toLowerCase(); renderList(); });
  return h("section", { id: "list-section" },
    h("div", { class: "filters" }, q, kindSel, stageSel, sortSel),
    scoreKey(),
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
  const order = [...STREAM_TYPES.map((t) => t.label), ...Object.values(SET_ASIDE)];
  $("chips").replaceChildren(...Object.entries(counts).sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0])).map(([k, n]) => {
    const vs = byKicker[k];
    const on = [...vs].every((v) => state.verdicts.has(v));
    const t = STREAM_TYPES.find((x) => x.label === k) || OTHER;
    const b = h("button", { class: "chip", type: "button", "aria-pressed": String(on) },
      h("i", { class: "sw", style: `background:${t.color}`, "aria-hidden": "true" }), k, h("span", { class: "n" }, n));
    b.addEventListener("click", () => { vs.forEach((v) => (on ? state.verdicts.delete(v) : state.verdicts.add(v))); renderList(); });
    return b;
  }));
  const list = all.filter(matches).sort((a, b) => {
    if (!state.verdicts.size) { const fa = FILTERED.has(a.verdict), fb = FILTERED.has(b.verdict); if (fa !== fb) return fa ? 1 : -1; }
    return SORTS[state.sort](a, b);
  });
  const open = !!VIEWS[state.view].pro;
  // Pro views list every title on its own; everyone else gets one row per cause.
  const rows = open ? list.map((r) => ({ r })) : toRows(list);
  const of = list.length === all.length ? `${all.length} comebacks` : `${list.length} of ${all.length} comebacks`;
  $("count").textContent = rows.length < list.length ? `${of}, from ${rows.length} stories` : of;
  const filtering = state.q || state.verdicts.size || state.kinds.size || state.stages.size;
  const cap = state.view === "today" && !state.showAll && !filtering ? 12 : Infinity;
  const shown = rows.slice(0, cap);
  const more = rows.length > shown.length
    ? h("button", { type: "button", class: "btn ghost show-all", onclick: () => { state.showAll = true; renderList(); } }, `Show all ${rows.length} stories`) : null;
  $("cards").replaceChildren(...(rows.length ? shown.map((x) => (x.g ? groupCard(x.g, x.members) : card(x.r, open))) : [h("p", { class: "status" }, "Nothing matches these filters.")]), ...(more ? [more] : []));
}

// Corrections use the same form as tips (marked "CORRECTION"), so readers never need a GitHub account.
function correctionLink(r, label = "Report a correction", cls) {
  if (TIPS_FORM.action) return h("a", { href: "#", class: cls || null, onclick: (e) => { e.preventDefault(); openTip(r, "correction"); } }, label);
  const top = r.triggers[0];
  const body = [`**Work:** ${r.label} (${r.release_year}) ${wikidata(r.qid)}`, `**Edition:** ${$("run").value}`,
    `**The Rallyback said:** ${story(r).hed}${top ? ` (${top.text})` : ""}${r.cause ? `; likely cause: ${r.cause}` : ""}`,
    "", "**What actually happened (with a link if you have one):**", ""].join("\n");
  const url = `https://github.com/${REPO}/issues/new?labels=feedback&title=${encodeURIComponent(`About ${r.label}`)}&body=${encodeURIComponent(body)}`;
  return h("a", { href: url, target: "_blank", rel: "noopener", class: cls || null }, label);
}

// A tip about a mystery: opens the tip form, pre-filled with the work.
// Every unexplained comeback asks readers for the reason.
const isOpen = (r) => reasonOf(r).key === "unexplained";

function tipLink(r, label = "Know why? Tell us →") {
  if (!TIPS_FORM.action) return correctionLink(r, label, "ask");
  return h("a", { href: "#", class: "ask", onclick: (e) => { e.preventDefault(); openTip(r); } }, label);
}

function openTip(r, mode = "tip") {
  let dlg = $("tipform");
  if (dlg) dlg.remove();
  const fix = mode === "correction";
  const top = r.triggers && r.triggers[0];
  const work = `${fix ? "CORRECTION · " : ""}${r.label} (${r.release_year}) · ${wikipedia(r.title)} · edition ${$("run").value} · The Rallyback said: ${story(r).hed}` +
    (fix && top ? ` (${top.text})` : "") + (fix && r.cause ? `; likely cause: ${r.cause}` : "");
  const status = h("p", { class: "form-status", role: "status" });
  const why = h("textarea", { name: "why", required: "", rows: "4",
    placeholder: fix ? "What did we get wrong, and what's right?" : "A trailer, a TikTok trend, a TV placement, news about someone involved…" });
  const link = h("input", { name: "link", type: "url", placeholder: "https://" });
  const email = h("input", { name: "email", type: "email", placeholder: "you@example.com", autocomplete: "email" });
  const send = h("button", { type: "submit", class: "btn" }, fix ? "Send correction" : "Send tip");
  const form = h("form", { method: "dialog" },
    h("span", { class: "kicker" }, fix ? "Report a correction" : "Tip the desk"),
    h("h2", { class: "hed" }, fix ? `Something wrong about ${r.label}?` : `Why is ${r.label} back?`),
    h("p", { class: "small muted" }, fix ? `We said: “${story(r).hed}”.`
      : `The ${r.release_year} ${noun(r.kind)} is drawing ${mult(r)} its usual interest and we can't find the reason.`),
    h("label", {}, h("span", {}, fix ? "What should it say?" : "What's bringing it back?"), why),
    h("label", {}, h("span", {}, "A link, if you have one ", h("i", { class: "muted" }, "(optional)")), link),
    h("label", {}, h("span", {}, "Your email, if we may follow up ", h("i", { class: "muted" }, "(optional)")), email,
      h("small", { class: "muted" }, `We'll only use it to follow up on this ${fix ? "correction" : "tip"}.`)),
    h("div", { class: "form-actions" }, send,
      h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Cancel")),
    status);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!why.value.trim()) { why.focus(); return; }
    send.disabled = true; status.textContent = "Sending…";
    try {
      await sendToForm({ work, why: why.value.trim(), link: link.value.trim(), email: email.value.trim() });
      form.replaceChildren(h("span", { class: "kicker" }, "Thank you"), h("h2", { class: "hed" }, fix ? "Correction received" : "Tip received"),
        h("p", {}, fix ? "We read every report. If we got it wrong, we'll fix it and list it under Corrections on Track record."
          : "We read every tip. If it checks out, it'll show up as an editor's note on the story."),
        h("div", { class: "form-actions" }, h("button", { type: "button", class: "btn", onclick: () => dlg.close() }, "Close")));
    } catch (err) {
      send.disabled = false;
      status.textContent = "That didn't go through. Please try again in a moment.";
    }
  });
  dlg = h("dialog", { id: "tipform", class: "tipform", "aria-label": `Tip: why is ${r.label} back?` }, form);
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });   // click outside to close
  document.body.append(dlg);
  dlg.showModal();
  why.focus();
}

// A short contact form on About us. It goes to the same Google Form as tips, marked "CONTACT ·"
// in the "Which title?" answer so messages are easy to tell apart in the Responses tab.
async function sendToForm(fields) {
  const F = TIPS_FORM.fields, data = new URLSearchParams();
  for (const [k, v] of Object.entries(fields)) if (v) data.append(F[k] || k, v);
  const google = /docs\.google\.com\/forms/.test(TIPS_FORM.action);
  // Google Forms doesn't allow reading its reply from another site, so a sent request counts as success.
  const res = await fetch(TIPS_FORM.action, google ? { method: "POST", mode: "no-cors", body: data }
    : { method: "POST", body: data, headers: { Accept: "application/json" } });
  if (!google && !res.ok) throw new Error(res.status);
}
function contactForm() {
  const name = h("input", { name: "name", autocomplete: "name", placeholder: "Your name" });
  const email = h("input", { name: "email", type: "email", required: "", autocomplete: "email", placeholder: "you@example.com" });
  const msg = h("textarea", { name: "message", required: "", rows: "5", placeholder: "What's on your mind?" });
  const status = h("p", { class: "form-status", role: "status" });
  const send = h("button", { type: "submit", class: "btn" }, "Send message");
  const form = h("form", { class: "tipform contact-form" },
    h("label", {}, h("span", {}, "Name ", h("i", { class: "muted" }, "(optional)")), name),
    h("label", {}, h("span", {}, "Email ", h("i", { class: "muted" }, "(so we can reply)")), email),
    h("label", {}, h("span", {}, "Message"), msg),
    h("div", { class: "form-actions" }, send), status);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!email.value.trim() || !email.checkValidity()) { email.focus(); return; }
    if (!msg.value.trim()) { msg.focus(); return; }
    send.disabled = true; status.textContent = "Sending…";
    try {
      await sendToForm({ work: `CONTACT · ${name.value.trim() || "(no name)"}`, why: msg.value.trim(), email: email.value.trim() });
      form.replaceChildren(h("p", { class: "contact-sent" }, h("b", {}, "Thanks, your message is on its way. "),
        "We read everything and reply to the email you gave."));
    } catch (err) {
      send.disabled = false;
      status.textContent = "That didn't go through. Please try again in a moment, or email us.";
    }
  });
  return form;
}

function evidenceList(ev, limit = 4) {
  if (!ev || !ev.length) return null;
  return h("ul", { class: "evidence" }, ev.slice(0, limit).map((e) =>
    h("li", {}, h("span", { class: "src" }, e.source), e.url ? ext(e.url, e.text) : e.text, h("span", { class: "d" }, short(e.date)))));
}

function card(r, open, inGroup) {
  const st = story(r);
  const checks = [];
  const add = (node) => { if (checks.length) checks.push(" · "); checks.push(node); };
  if (r.last_year_lift != null) add(h("span", { class: r.last_year_lift >= 2.5 ? "warn" : "" }, `Same weeks last year: ${r.last_year_lift}×`));
  if (r.desktop_share != null) add(h("span", { class: r.desktop_share >= 0.85 ? "warn" : "" }, `${Math.round(r.desktop_share * 100)}% desktop`));
  if (r.corroborated === true) add(h("span", { class: "ok" }, "✓ backed by news/edits"));
  if (r.corroborated === false) add(h("span", { class: "warn" }, "Evidence doesn't mention this trigger"));
  if (r.edit_burst && r.edit_burst.burst) add(`${r.edit_burst.edits} Wikipedia edits around the spike (usually ~${r.edit_burst.usual_per_5_days})`);
  add(correctionLink(r));
  const photo = pic(null, r.image, r.label, 240, r.image_of);
  return h("article", { class: `card${photo ? " has-media" : ""}`, id: `w-${r.qid}` },
    photo,
    h("div", {},
      // Inside a group the reason is already said once above, so each title just names itself.
      inGroup ? null : kickerEl(st.reason, st.kicker),
      h("h3", { class: "hed" }, h("a", { href: `#w-${r.qid}`, onclick: (e) => {
        e.preventDefault(); const d = e.target.closest(".card").querySelector("details"); d.open = !d.open; } },
        inGroup ? `${plain(r.label)} (${r.release_year})` : st.hed)),
      h("p", { class: "dek" }, inGroup ? `The ${noun(r.kind)} is drawing ${mult(r)} its usual interest.` : dekWithLink(st.dek, r.cause, r.cause_link, r.editor_note)),
      h("div", { class: "tags" },
        inGroup ? null : h("span", { class: "tagx" }, `${r.label} · ${r.release_year}`),
        r.stage === "emerging" ? h("span", { class: "tagx hot" }, "Just starting") : r.stage ? h("span", { class: "tagx" }, STAGES[r.stage]) : null,
        r.early ? h("span", { class: "tagx", title: "Spotted by our watchlist before it reached Wikipedia's top 1,000" }, "Caught early") : null,
        scoreDot(r.rally_score), confidenceTag(r), followBtn(r.qid, plain(r.label))),
      isOpen(r) ? h("div", { class: "card-ask" }, tipLink(r)) : null,
      h("details", { class: "more-info", open: open ? "" : null }, h("summary", {}, "Numbers & sources"),
        sparkline(r),
        h("dl", { class: "nums" },
          h("div", {}, h("dt", {}, "14-day lift"), h("dd", {}, `${r.lift}×`)),
          h("div", {}, h("dt", {}, "Last 3 days"), h("dd", {}, `${r.lift3 ?? "–"}×`)),
          h("div", {}, h("dt", {}, "Usual"), h("dd", {}, `${fmt(r.baseline)}/day`)),
          h("div", {}, h("dt", {}, "Began"), h("dd", {}, short(r.spike_start)))),
        r.triggers.length ? h("ul", { class: "triggers" }, r.triggers.map((t) =>
          h("li", {}, t.qid ? ext(wikidata(t.qid), t.text) : t.text, h("span", { class: "d" }, short(t.date))))) : null,
        h("p", { class: "small" }, ext(wikipedia(r.title), `${r.label} on Wikipedia →`)),
        r.editor_note ? sourceLine(r.editor_note) : null,
        elsewhere(r),
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
    "aria-label": `Daily views over 12 months for ${r.label}. Usually ${fmt(r.baseline)} a day, peak ${fmt(r.peak)} on ${fmtDate(r.peak_day)}.` });
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
    tip.textContent = `${fmtDate(addDays(r.spark_start, i))} · ${fmt(vals[i])} views`;
    tip.style.left = `${box.left + (i / W) * box.width}px`; tip.style.top = `${box.top}px`; tip.hidden = false;
  };
  const leave = () => { cursor.setAttribute("visibility", "hidden"); tip.hidden = true; };
  svg.addEventListener("pointermove", move); svg.addEventListener("pointerdown", move); svg.addEventListener("pointerleave", leave);
  return h("div", { class: "spark" }, svg, compact ? null : h("div", { class: "spark-legend" }, h("span", {}, "Daily views, last 12 months"), h("span", {}, "dashed line = usual")));
}

function focusGroup(g) {
  focusCard(g.works[0].qid);
  const el = $(g.id);
  if (!el) return;
  el.querySelector(".group-members").open = false;
  el.scrollIntoView({ block: "start" });
  for (const ms of [700, 1400]) setTimeout(() => { if (Math.abs(el.getBoundingClientRect().top) > 40) el.scrollIntoView({ block: "start" }); }, ms);
}

function focusCard(qid) {
  let el = $(`w-${qid}`);
  if (!el && $("cards") && !state.showAll) { state.showAll = true; renderList(); el = $(`w-${qid}`); }
  if (!el && !$("cards")) { goto("today"); el = $(`w-${qid}`); }
  if (!el) {
    state.verdicts.clear(); state.kinds.clear(); state.stages.clear(); state.hideFiltered = false; state.q = "";
    state.showAll = true;
    if ($("q")) $("q").value = "";
    renderList();
    el = $(`w-${qid}`);
  }
  if (!el) return;
  const grp = el.closest(".group-members");
  if (grp) grp.open = true;
  const d = el.querySelector("details");
  if (d) d.open = true;
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  // Cards rendered just now (and photos loading) can shift the layout mid-scroll; settle on the card.
  for (const ms of [700, 1400]) setTimeout(() => { if (Math.abs(el.getBoundingClientRect().top) > 40) el.scrollIntoView({ block: "start" }); }, ms);
  el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800);
}

// ---------- Coming Soon ----------
// The data now looks six months ahead for the Coming up page. The home page and the
// quick panels keep their shorter windows: releases in the next 5 months, birthdays in the next 60 days.
const within = (xs, days) => { const end = addDays(new Date().toISOString().slice(0, 10), days); return (xs || []).filter((x) => x.date <= end); };
const soonReleases = (cu) => within(cu.derivatives, 150);
const soonBirthdays = (cu) => within(cu.anniversaries, 60);

function comingPage() {
  const cu = state.data.coming_up || { derivatives: [], anniversaries: [] };
  // Cards: the best-known, pictured first. Tables: everything else, in date order.
  const dCards = pictured([...(cu.derivatives || [])].sort((a, b) => (b.old_sitelinks || 0) - (a.old_sitelinks || 0))).slice(0, 6);
  const aCards = bigAnniversaries(cu.anniversaries || [], 6);
  const dRow = (c) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(c.date)),
    workCell(state.byQid[c.old], plain(c.old_label), `${c.old_kind}, ${c.old_release.slice(0, 4)}`),
    h("td", {}, c.new_label, h("div", { class: "small muted" }, NEWREL[c.rel] || c.rel)),
    outlookCell(c.prediction));
  const aRow = (a) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(a.date)),
    workCell(state.byQid[a.qid], plain(a.label), `${a.kind}, ${a.release.slice(0, 4)}`),
    h("td", { class: "num" }, `${a.years}th`),
    h("td", { class: "num" }, a.audience ? fmt(a.audience) : "–"),
    outlookCell(a.prediction));
  const sRow = (a) => h("tr", {},
    h("td", { class: "nowrap" }, `Around ${short(a.date)}`),
    workCell(state.byQid[a.qid], plain(a.label), `${a.kind}, ${a.release.slice(0, 4)}${a.holiday ? ` · ${a.holiday}` : ""}`),
    outlookCell(a.prediction));
  const dAll = byDate(cu.derivatives || []), aAll = byDate(cu.anniversaries || []), sAll = byDate(cu.seasonal || []);
  const jAll = byDate(cu.subjects || []), wAll = cu.warming || [];
  const jRow = (sj) => h("tr", {}, h("td", { class: "nowrap" }, fmtDate(sj.date)),
    h("td", {}, h("b", {}, sj.who_label), h("div", { class: "small muted" }, sj.new_label)),
    h("td", {}, ...sj.works.flatMap((w, i) => [i ? ", " : "", titleLink(w.qid, plain(w.label))]), sj.more ? ` +${sj.more}` : ""));
  const wRow = (w) => h("tr", {}, workCell(null, plain(w.label), `${w.kind}, ${w.release.slice(0, 4)}`),
    h("td", { class: "num nowrap" }, fmtX(w.ratio)), h("td", { class: "num nowrap" }, `+${Math.round((w.week_ratio - 1) * 100)}%`),
    h("td", { class: "num" }, fmt(w.usual)));
  const sCards = [...sAll].sort((a, b) => (b.audience || 0) - (a.audience || 0)).slice(0, 6);
  // How the last few weeks' predictions turned out (checked about a week after each date).
  const since = addDays(new Date().toISOString().slice(0, 10), -45);
  const due = (((state.accuracy || {}).forecasts || {}).recent || []).filter((x) => x.date >= since);
  const dueRow = (x) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(x.date)),
    h("td", {}, h("b", {}, x.label), h("div", { class: "small muted" }, x.detail)),
    h("td", { class: "num nowrap" }, x.predicted && x.predicted.expected != null ? `${fmtX(x.predicted.expected)}${x.predicted.chance != null ? ` · ${Math.round(x.predicted.chance * 100)}%` : ""}` : "–"),
    h("td", { class: "num nowrap" }, fmtX(x.ratio)),
    h("td", { class: "nowrap" }, x.hit ? h("span", { class: "ok" }, "✓ Came true") : h("span", { class: "muted" }, "No bump")));
  return [
    h("p", { class: "intro" }, "What's about to bring old favorites back over the next six months: sequels, remakes and adaptations on the way, plus the big birthdays. We check later whether we were right."),
    contentsLine([{ n: (cu.derivatives || []).length, label: "due for a comeback", title: "Due for a comeback" },
      { n: (cu.anniversaries || []).length, label: "big anniversaries", title: "Big anniversaries" },
      { n: sAll.length, label: "back every year", title: "Back every year" },
      { n: jAll.length, label: "documentaries and biopics", title: "Documentaries and biopics" },
      { n: wAll.length, label: "warming up", title: "Warming up" },
      { n: due.length, label: "recently due", title: "Recently due" }]),
    [...dAll, ...aAll].some((x) => x.prediction) ? h("p", { class: "small muted outlook-key" }, h("b", {}, "Expect about 3× · 70% chance"),
      " is our prediction, learned from over 10,000 past sequels, adaptations, series entries and anniversaries since 2016: the usual size of the comeback, and how often similar cases reached at least 2× their usual interest.") : null,
    ...pageSection("Due for a comeback", "A sequel, remake or adaptation is on the way. Release dates can slip.",
      { cards: dCards, rest: dAll.filter((c) => !dCards.includes(c)), all: dAll, card: derivCard, row: dRow }, ["Due", "The original", "What's bringing it back", "Outlook"], "comebacks due"),
    ...pageSection("Big anniversaries", "Round-number birthdays of well-known older works.",
      { cards: aCards, rest: aAll.filter((a) => !aCards.includes(a)), all: aAll, card: annCard, row: aRow }, ["Date", "Work", "Turns", "Views on a normal day", "Outlook"], "anniversaries"),
    ...pageSection("Back every year", "Old favorites that come back around the same date every year: holidays, seasons, school terms.",
      { cards: sCards, rest: sAll.filter((a) => !sCards.includes(a)), all: sAll, card: seasonCard, row: sRow }, ["When", "Work", "Outlook"], "regulars"),
    ...pageSection("Documentaries and biopics", "A new film or series about someone sends people back to their own work.",
      { cards: jAll.slice(0, 6), rest: jAll.slice(6), all: jAll, card: subjectCard, row: jRow }, ["Arrives", "About", "Their older work"], "on the way"),
    ...pageSection("Warming up", "Climbing steadily but not a comeback yet: these may break next. We check two weeks later whether they did.",
      { cards: wAll.slice(0, 6), rest: wAll.slice(6), all: wAll, card: warmCard, row: wRow }, ["Title", "Now", "Vs. last week", "Usual views a day"], "climbing"),
    ...(due.length ? [Object.assign(sectionHead("Recently due", "How our predictions turned out, checked about a week after each date."), { id: secId("Recently due") }),
      table(["Date", "Prediction", "Predicted", "What happened", ""], due.map(dueRow), 12, "results")] : []),
    (cu.derivatives || []).length || (cu.anniversaries || []).length ? null : table([], []),
  ].filter(Boolean);
}
// `cap` shows the first rows, with a link that shows the rest and one that folds them away again.
function table(head, rows, cap = Infinity, noun = "rows") {
  if (!rows.length) return h("p", { class: "muted" }, "Nothing here yet. This fills in once the daily run has built its watchlist.");
  if (rows.length > cap) {
    const full = table(head, rows);
    const extra = rows.slice(cap);
    const box = h("div", {}, full);
    const toggle = h("button", { type: "button", class: "btn ghost show-all", "aria-expanded": "false" });
    const set = (open) => {
      extra.forEach((tr) => { tr.hidden = !open; });
      if (!open) {   // a card opened under a row that's now folded away goes too
        box.querySelectorAll("tr.card-row").forEach((x) => { if (x.previousElementSibling && x.previousElementSibling.hidden) x.remove(); });
      }
      toggle.setAttribute("aria-expanded", String(open));
      toggle.textContent = open ? `Show fewer ${noun}` : `Show all ${rows.length} ${noun}`;
    };
    toggle.addEventListener("click", () => {
      const open = toggle.getAttribute("aria-expanded") !== "true";
      set(open);
      // Folding a long list back up keeps the reader at the list, not far below it.
      if (!open) box.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    });
    set(false);
    box.append(toggle);
    return box;
  }
  // A heading lines up with its column: numeric columns (every cell .num) get right-aligned headings.
  const numeric = head.map((_, i) => rows.length && rows.every((tr) => tr.children[i] && tr.children[i].classList.contains("num")));
  return h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, head.map((x, i) => h("th", { class: numeric[i] ? "num" : null }, x)))), h("tbody", {}, rows)));
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
    sectionHead("Did the Prediction Come True?", "A prediction counts if the older work hit 2× its usual interest within a week of the date."),
    table(["Date", "Work", "We predicted", "Peak vs usual", "Result"], recent),
    sectionHead("Do Our Explanations Hold Up?", "For explained spikes: did news or Wikipedia edits from the same days mention the same cause?"),
    table(["Story type", "Checked", "Backed by evidence"], corrRows),
    sectionHead("Help Us Check", null),
    h("p", {}, "Every story has a ", h("b", {}, "Report a correction"), " link in its numbers and sources. We read every report, ",
      "and when we got something wrong we fix it and list it under Corrections below."),
    sectionHead("What we're learning", "Measures only our record can answer. Each one appears here by itself once it has enough examples."),
    measuresBox(),
    sectionHead("Corrections", "When we get something wrong, we fix it and say so here."),
    correctionsList(),
  ];
}

// ---------- Alerts ----------
// About us: the mission, how we work, and the feeds (formerly the Alerts page).
function aboutPage() {
  const base = new URL(".", location.href).href;
  const feeds = [
    ["all", "Everything new: every comeback, plus what's coming up"],
    ["unexplained", "Unexplained comebacks, the ones nobody can account for yet"],
    ["coming-up", "Coming up: originals with a sequel, remake or adaptation on the way"],
    ["film-tv", "Film & TV"], ["music", "Songs, albums and musicals"], ["games", "Video games"], ["books", "Books, manga and comics"],
  ];
  const go = (view, label) => h("button", { type: "button", class: "linkish", onclick: () => goto(view) }, label);
  return [
    h("div", { class: "about" },
      h("p", { class: "intro" }, "We notice when the past comes back, and find out why."),
      h("h3", { class: "about-first" }, "Our mission"),
      h("p", { class: "mission" }, "Old favorites don't stop mattering when they leave the charts. Every day, a film, show, song, game or book from years ago suddenly finds a new audience, because of a sequel, a death, an anniversary, a meme or a story in the news. The Rallyback's mission is to spot those comebacks as they happen, explain them honestly, and keep a permanent public record of what came back and why."),
      h("h3", {}, "Why it matters"),
      h("p", { class: "mission" }, "What people return to says as much about culture as what's new. A comeback is a window. It's a reason to rewatch, relisten or finally read something, and a chance for the people behind the work, from studios and labels to publishers, estates and the stores that sell it, to bring it back to audiences while the interest lasts. Those windows often close in weeks, and until now nobody has tracked them in one place. Over time, The Rallyback's record also answers questions no one else can: how long a comeback lasts, what kind of news sets one off, and which old favorites keep coming back."),
      h("h3", {}, "How we work"),
      h("ul", { class: "about-list" },
        h("li", {}, h("b", {}, "Every morning. "), "A new edition is built automatically each night from what millions of people read, play, stream and buy."),
        h("li", {}, h("b", {}, "Open data only. "), "Wikipedia and Wikidata, public charts, Steam, Open Library, Project Gutenberg, news archives and public Bluesky posts. Every story links to its sources."),
        h("li", {}, h("b", {}, "Honest about what we don't know. "), "When we can't find the reason, a comeback goes on the ", go("mysteries", "Unexplained"), " page, and we say so."),
        h("li", {}, h("b", {}, "Keeping score in public. "), "We predict comebacks before they happen and check afterwards whether we were right. See the ", go("accuracy", "Track record"), "."),
        h("li", {}, h("b", {}, "Readers help. "), "Know why something is back, or spotted a mistake? Use ", h("i", {}, "Know why? Tell us"), " on any story. Tips that check out become editor's notes.")),
      h("h3", {}, "Contact us"),
      h("p", { class: "mission" }, "Questions, ideas, press or partnerships: send us a note below or write to ", contactLink(), ". For a tip or a correction about a story, the links on the story itself are fastest."),
      TIPS_FORM.action ? contactForm() : null),
    newsletterBox(),
    sectionHead("Embed the chart", "Put today's top comebacks on your own site. It updates itself every morning."),
    embedBox(base),
    sectionHead("Feeds", "Get new comebacks every morning. Copy a link into any feed reader: Feedly, Inoreader, NetNewsWire, Outlook, Slack and others."),
    h("ul", { class: "plain" }, feeds.map(([n, d]) => h("li", {},
      h("a", { href: `feeds/${n}.xml` }, h("b", {}, `${n}.xml`)),
      h("button", { type: "button", class: "copy", onclick: (e) => copy(`${base}feeds/${n}.xml`, e.target) }, "Copy link"),
      h("div", { class: "small muted" }, d)))),
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
      h("li", {}, h("b", {}, "Confirm elsewhere."), " Record Steam players and reviews, iTunes and Deezer charts, Open Library trending and Project Gutenberg downloads every day (kept forever as open data), and check Wikipedia in 12 other languages and Bluesky posts for each comeback."),
      h("li", {}, h("b", {}, "Score."), " The Rallyback Score (0–100) weighs the size of the jump (40%), the everyday audience (25%), confirmation in other places (20%) and staying power (15%)."),
      h("li", {}, h("b", {}, "Explain."), " Look in Wikidata near the spike for deaths of credited people, sequels, adaptations, remakes, new series entries, new work by the same creator, and anniversaries. For spikes it can't explain, read Wikipedia edit summaries, edit bursts and GDELT news headlines from the same days."),
      h("li", {}, h("b", {}, "Connect."), " Group spikes by a shared event, and unexplained spikes by a shared person with the same timing."),
      h("li", {}, h("b", {}, "Filter."), " Set aside seasonal items (also up this time last year), spikes that are almost all desktop traffic (likely bots), and one-day surges from a feature on Wikipedia's front page."),
      h("li", {}, h("b", {}, "Predict and check."), " List upcoming sequels, adaptations and anniversaries, then check later whether attention rose.")),
    h("p", { class: "muted" }, h("b", {}, "Limits. "), "Wikipedia attention isn't sales or streams. Wikidata is volunteer-edited. News and edit lookups are best-effort and sometimes rate-limited. Two-title threads can be coincidence. Headlines are generated from the data. Verify before publishing or acting."));
}


// ================= the archive: title pages, search, follow, this week =================
const titleHref = (qid) => `?work=${encodeURIComponent(qid)}`;
function openWork(qid) { state.workId = qid; goto("work"); }
const titleLink = (qid, label) => h("a", { href: titleHref(qid), onclick: (e) => { e.preventDefault(); openWork(qid); } }, label);
const cached = {};
const loadOnce = (url) => (cached[url] = cached[url] || getJSON(url).catch((e) => { delete cached[url]; throw e; }));

// How sure we are about the reason, in one word.
const CONFIDENCE = {
  Confirmed: "An editor checked the reason against a published source.",
  Likely: "A matching event is on record: a new release, a death or an anniversary, at the right time.",
  Possible: "Inferred from news headlines, Wikipedia edits or a related page jumping. Not yet confirmed.",
};
function confidenceOf(r) {
  if (r.editor_note) return "Confirmed";
  const k = reasonOf(r).key;
  if (k === "unexplained" || FILTERED.has(r.verdict)) return null;
  return ["death", "derivative", "same-creator", "anniversary"].includes(r.verdict) ? "Likely" : "Possible";
}
const confidenceTag = (r) => { const c = confidenceOf(r); return c ? h("span", { class: `conf conf-${c.toLowerCase()}`, title: CONFIDENCE[c] }, c) : null; };

// ---------- follow (kept in this browser only) ----------
const FOLLOW_KEY = "rb-follow";
const following = () => { try { return JSON.parse(localStorage.getItem(FOLLOW_KEY) || "[]"); } catch (e) { return []; } };
const isFollowing = (qid) => following().some((x) => x.qid === qid);
function setFollow(qid, label, on) {
  const list = following().filter((x) => x.qid !== qid);
  if (on) list.unshift({ qid, label, since: new Date().toISOString().slice(0, 10) });
  try { localStorage.setItem(FOLLOW_KEY, JSON.stringify(list)); } catch (e) { /* private mode: not saved */ }
  updateFollowLink();
}
function followBtn(qid, label) {
  const b = h("button", { type: "button", class: "follow", "aria-pressed": String(isFollowing(qid)) });
  const paint = () => { const on = isFollowing(qid); b.setAttribute("aria-pressed", String(on)); b.textContent = on ? "★ Following" : "☆ Follow"; b.title = on ? "Stop following" : "Follow: we'll flag it on the site when it comes back or something is coming for it"; };
  b.addEventListener("click", () => { setFollow(qid, label, !isFollowing(qid)); paint(); });
  paint();
  return b;
}
function updateFollowLink() {
  const a = $("follow-link");
  if (!a) return;
  const n = following().length;
  a.hidden = !n;
  a.textContent = `★ Following (${n})`;
  a.onclick = (e) => { e.preventDefault(); goto("following"); };
}

// ---------- a title's page ----------
function workPage() {
  const qid = state.workId;
  const box = h("div", { class: "workpage" }, h("p", { class: "status" }, "Loading…"));
  loadOnce(`data/works/${encodeURIComponent(qid)}.json`).then((w) => box.replaceChildren(...workView(w)))
    .catch(() => box.replaceChildren(h("p", { class: "status" }, "We haven't tracked a comeback for this title yet."), searchBox()));
  return [box];
}
function workView(w) {
  document.title = `${plain(w.label)} (${w.year}) · The Rallyback`;
  const eps = [...w.episodes].reverse();
  const last = eps[0], r = state.byQid[w.qid];
  const times = w.episodes.length === 1 ? "once" : `${w.episodes.length} times`;
  const peakI = w.spark ? w.spark.indexOf(Math.max(...w.spark)) : -1;
  const chart = w.spark ? sparkline({ spark: w.spark, baseline: w.baseline || 1, spark_start: w.spark_start, spike_start: last.start,
    peak: Math.max(...w.spark), peak_day: addDays(w.spark_start, peakI), label: w.label }) : null;
  const epRow = (e) => h("tr", {},
    h("td", { class: "nowrap" }, fmtDate(e.start)),
    h("td", {}, e.causes.length ? e.causes.join(" · ") : h("span", { class: "muted" }, "Reason unknown")),
    h("td", { class: "num nowrap" }, `${fmtX(e.peak_lift)}`),
    h("td", { class: "num" }, scoreDot(e.score)),
    h("td", { class: "num nowrap" }, `${e.days} day${e.days === 1 ? "" : "s"}`));
  const comeRow = (c) => h("tr", {}, h("td", { class: "nowrap" }, fmtDate(c.date)), h("td", {}, c.text), outlookCell(c.prediction));
  const shareUrl = new URL(`w/${w.qid}`, location.href.split("?")[0]).href;
  return [
    h("div", { class: "work-head" },
      w.image ? pic(null, w.image, w.label, 480, w.image_of) : null,
      h("div", {},
        h("div", { class: "when" }, `${w.kind}, ${w.year}`),
        h("h2", { class: "work-title" }, plain(w.label)),
        h("p", { class: "dek" }, `Back ${times} since we started tracking in ${fmtDate(state.index.runs.at(-1).id).replace(/ \d+,/, "")}. ` +
          `Most recently from ${fmtDate(last.start)}, at ${fmtX(last.peak_lift)} its usual interest.`),
        h("div", { class: "foot-row" }, followBtn(w.qid, plain(w.label)),
          h("button", { type: "button", class: "copy", onclick: (e) => copy(shareUrl, e.target) }, "Copy link"),
          w.on_today && r ? h("button", { type: "button", class: "linkish", onclick: () => { goto("today"); setTimeout(() => focusCard(w.qid), 60); } }, "On today's list →") : null),
        w.franchises.length ? h("p", { class: "small muted" }, "Part of ", w.franchises.map((f) => f.name).join(", "), ".") : null)),
    chart ? h("div", { class: "work-chart" }, chart) : null,
    (w.read || []).length ? sectionHead("Read it free", "Free ebooks are public domain; Open Library lends copies when one is available.") : null,
    (w.read || []).length ? h("ul", { class: "plain related" }, w.read.map((x) => h("li", {}, ext(x.url, x.label)))) : null,
    sectionHead("Every comeback", "Each time it came back since we started keeping the record, newest first."),
    table(["Started", "Why", "Peak", "Score", "On our list"], eps.map(epRow), 12, "comebacks"),
    w.coming.length ? sectionHead("Coming up", "What could bring it back next.") : null,
    w.coming.length ? table(["When", "What", "Outlook"], w.coming.map(comeRow)) : null,
    w.related.length ? sectionHead("Related", "Back around the same time, or part of the same series.") : null,
    w.related.length ? h("ul", { class: "plain related" }, w.related.map((x) => h("li", {}, titleLink(x.qid, `${plain(x.label)} (${x.year})`), h("span", { class: "small muted" }, ` · ${x.why}`)))) : null,
    h("p", { class: "small muted work-src" }, w.title ? ext(wikipedia(w.title), "Wikipedia →") : null, w.title ? " · " : null, ext(wikidata(w.qid), "Wikidata →")),
  ].filter(Boolean);
}

// ---------- search the archive ----------
function searchBox(value = state.searchQ || "") {
  const q = h("input", { type: "search", value, placeholder: "Search every title we've tracked", "aria-label": "Search every title we've tracked" });
  return h("form", { class: "archive-search", role: "search", onsubmit: (e) => { e.preventDefault(); state.searchQ = q.value.trim(); goto("search"); } },
    q, h("button", { type: "submit", class: "btn" }, "Search"));
}
function searchPage() {
  const results = h("div", {}, h("p", { class: "status" }, "Loading…"));
  loadOnce("data/works/index.json").then((ix) => {
    const F = Object.fromEntries(ix.fields.map((f, i) => [f, i]));
    const q = (state.searchQ || "").toLowerCase();
    const norm = (t) => t.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const hits = q ? ix.works.filter((w) => norm(w[F.label]).includes(norm(q))) : ix.works.slice(0, 30);
    const row = (w) => h("tr", {},
      h("td", {}, h("b", {}, titleLink(w[F.qid], plain(w[F.label]))), h("div", { class: "small muted" }, `${w[F.kind]}, ${w[F.year]}`)),
      h("td", { class: "num" }, String(w[F.comebacks])),
      h("td", { class: "nowrap" }, fmtDate(w[F.last_seen])),
      h("td", { class: "num" }, scoreDot(w[F.best_score])));
    results.replaceChildren(
      h("p", { class: "small muted" }, q ? `${hits.length} title${hits.length === 1 ? "" : "s"} matching “${state.searchQ}”, out of ${fmt(ix.works.length)} we've tracked.`
        : `The titles that have come back most, out of ${fmt(ix.works.length)} we've tracked.`),
      hits.length ? table(["Title", "Comebacks", "Last back", "Best score"], hits.slice(0, 200).map(row), 25, "titles")
        : h("p", {}, "No comeback on record for that yet. We only list titles once they come back, so check again later."));
  }).catch(() => results.replaceChildren(h("p", { class: "status" }, "The archive isn't available yet.")));
  return [h("p", { class: "intro" }, "Has it come back before?"), searchBox(), results];
}

// ---------- following ----------
function followingPage() {
  const list = following();
  if (!list.length) return [h("p", { class: "intro" }, "Follow titles to keep an eye on them."),
    h("p", {}, "Tap ", h("b", {}, "☆ Follow"), " on any story or title page. We'll show here when it comes back or something is coming for it. It's kept in this browser only, no account needed.")];
  const rows = h("tbody", {});
  for (const f of list) {
    const tr = h("tr", {}, h("td", {}, h("b", {}, titleLink(f.qid, f.label))), h("td", { class: "muted" }, "…"), h("td", {}, followBtn(f.qid, f.label)));
    rows.append(tr);
    loadOnce(`data/works/${encodeURIComponent(f.qid)}.json`).then((w) => {
      const r = state.byQid[f.qid], next = (w.coming || [])[0], last = w.episodes.at(-1);
      tr.children[1].replaceChildren(r ? h("span", { class: "ok" }, `Back now: ${mult(r)} its usual interest`)
        : next ? `Coming up ${short(next.date)}: ${next.text}` : `Last back ${fmtDate(last.last_seen)}`);
      tr.children[1].className = "";
    }).catch(() => { tr.children[1].textContent = "Not back since you followed it."; });
  }
  return [h("p", { class: "intro" }, "Titles you follow."),
    h("p", { class: "small muted" }, "Kept in this browser only. Titles that are back right now say so."),
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Title"), h("th", {}, "Status"), h("th", {}, ""))), rows))];
}

// ---------- this week ----------
function weekPage() {
  const box = h("div", {}, h("p", { class: "status" }, "Loading…"));
  Promise.all([loadOnce("data/weekly/index.json"), loadOnce("data/leaders.json")]).then(async ([weeks, L]) => {
    const key = state.weekId && weeks.includes(state.weekId) ? state.weekId : weeks[0];
    const W = await loadOnce(`data/weekly/${key}.json`);
    const pickWeek = h("select", { "aria-label": "Choose a week" }, weeks.map((k) => h("option", { value: k, selected: k === key ? "" : null }, k === weeks[0] ? `This week` : `Week of ${k}`)));
    pickWeek.addEventListener("change", () => { state.weekId = pickWeek.value; render(); });
    // Each of the 5 biggest gets a small chart of its last three weeks: still climbing, or fading?
    const trend = (x) => {
      if (!x.trend || !x.trend.length) return null;
      const vals = x.trend, peak = Math.max(...vals), pi = vals.indexOf(peak);
      const start = addDays(x.trend_end, -(vals.length - 1));
      const last = vals.at(-1), now = last >= peak * 0.8 ? "still near its peak" : last >= (x.baseline || 1) * 2 ? "cooling off" : "back toward usual";
      return h("div", { class: "rank-trend" }, sparkline({ spark: vals, baseline: x.baseline || 1, spark_start: start, spike_start: x.start >= start ? x.start : start,
        peak, peak_day: addDays(start, pi), label: x.label }, true),
        h("div", { class: "rank-trend-cap" }, `Last 3 weeks · ${now}`));
    };
    const rank = (x, i) => h("li", {}, h("span", { class: "rank" }, String(i + 1)), h("div", {},
      h("b", {}, titleLink(x.qid, `${plain(x.label)} (${x.year})`)), x.more ? h("span", { class: "small muted" }, ` and ${x.more} more`) : null,
      h("div", { class: "small muted" }, scoreDot(x.score), " ", `${fmtX(x.lift || x.peak_lift)} usual interest`, x.why ? ` · ${x.why}` : "")), trend(x));
    const leadRow = (x) => h("tr", {}, h("td", {}, h("b", {}, titleLink(x.qid, plain(x.label))), x.more ? h("span", { class: "small muted" }, ` +${x.more} more`) : null,
      h("div", { class: "small muted" }, `${x.kind}, ${x.year}`)), h("td", { class: "nowrap" }, fmtDate(x.start)),
      h("td", { class: "num nowrap" }, fmtX(x.peak_lift)), h("td", { class: "num" }, scoreDot(x.score)));
    const maxShare = Math.max(...L.decades.map((d) => d.share), 0.01);
    box.replaceChildren(...[
      h("p", { class: "intro" }, `This week in comebacks: ${fmtDate(W.from).replace(/, \d{4}/, "")} to ${fmtDate(W.to)}.`),
      h("p", { class: "contents" }, h("b", {}, fmt(W.comebacks)), " comebacks so far this week · ", pickWeek),
      sectionHead("The 5 biggest", "One per story, by Rallyback Score."),
      h("ol", { class: "ranked" }, W.top.map(rank)),
      newsletterBox(),
      W.mystery ? sectionHead("Best mystery", "The biggest comeback we still can't explain. Know why?") : null,
      W.mystery ? h("div", { class: "mystery" }, h("b", {}, titleLink(W.mystery.qid, `${plain(W.mystery.label)} (${W.mystery.year})`)),
        ` · ${fmtX(W.mystery.lift)} its usual interest since ${fmtDate(W.mystery.start)}. `,
        state.byQid[W.mystery.qid] ? tipLink(state.byQid[W.mystery.qid]) : null) : null,
      W.coming.length ? sectionHead("Coming up next week", "Due in the next 8 days, biggest expected comebacks first.") : null,
      W.coming.length ? table(["When", "Title", "What", "Outlook"], W.coming.map((c) => h("tr", {}, h("td", { class: "nowrap" }, fmtDate(c.date)),
        h("td", {}, h("b", {}, titleLink(c.qid, plain(c.label)))), h("td", {}, c.what), outlookCell(c.prediction)))) : null,
      sectionHead("How our predictions did", "Checked about a week after each date."),
      W.results.length ? table(["Date", "Prediction", "Predicted", "What happened", ""], W.results.map((x) => h("tr", {},
        h("td", { class: "nowrap" }, fmtDate(x.date)), h("td", {}, h("b", {}, x.label), h("div", { class: "small muted" }, x.detail)),
        h("td", { class: "num nowrap" }, x.predicted && x.predicted.expected != null ? fmtX(x.predicted.expected) : "–"),
        h("td", { class: "num nowrap" }, fmtX(x.ratio)), h("td", {}, x.hit ? h("span", { class: "ok" }, "✓ Came true") : h("span", { class: "muted" }, "No bump")))))
        : h("p", { class: "muted" }, "The first predictions are checked about a week after their dates. Results start appearing here in late November."),
      sectionHead("Biggest this month", "One per story."),
      table(["Title", "Started", "Peak", "Score"], L.month.map(leadRow), 10, "comebacks"),
      // Shown once the year holds more than this month (the record starts in November 2026).
      L.covers_from < L.updated.slice(0, 8) + "01" ? sectionHead("Biggest this year", "One per story.") : null,
      L.covers_from < L.updated.slice(0, 8) + "01" ? table(["Title", "Started", "Peak", "Score"], L.year.map(leadRow), 10, "comebacks") : null,
      sectionHead("Decades this week", "Which eras people are going back to: comebacks this week by when the work came out."),
      h("div", { class: "bars" }, L.decades.slice(0, 10).map((d) => h("div", { class: "bar-row" },
        h("span", { class: "bar-label" }, d.decade), h("span", { class: "bar" }, h("i", { style: `width:${(100 * d.share / maxShare).toFixed(1)}%` })),
        h("span", { class: "bar-val" }, `${Math.round(d.share * 100)}%${d.usual_share != null ? ` (usually ${Math.round(d.usual_share * 100)}%)` : ""}`)))),
      L.franchises.length ? sectionHead("Franchises this week", "Series with more than one title back at once.") : null,
      L.franchises.length ? h("ul", { class: "plain related" }, L.franchises.map((f) => h("li", {}, h("b", {}, f.name), ` · ${f.titles} titles: `,
        ...f.top.flatMap((x, i) => [i ? ", " : "", titleLink(x.qid, plain(x.label))])))) : null,
      // Each week also has a permanent page of its own (plain HTML, good for sharing and search).
      h("p", { class: "week-links small muted" }, "Share this roundup: ", h("a", { href: `week/${key}` }, "this week’s page"),
        ". Looking for an earlier week? ", h("a", { href: "week/" }, "See every week"), ".")].filter(Boolean));
  }).catch(() => box.replaceChildren(h("p", { class: "status" }, "This week's roundup isn't ready yet. It's built with each morning's edition.")));
  return [box];
}

// ---------- measures that publish themselves when ready (site/data/measures.json) ----------
function measuresBox() {
  const box = h("div", {}, h("p", { class: "muted" }, "Loading…"));
  loadOnce("data/measures.json").then((M) => {
    const parts = [];
    for (const key of ["staying", "lead", "star", "calibration"]) {
      const m = M[key];
      if (!m) continue;
      if (!m.ready) {
        parts.push(h("div", { class: "measure-soon" }, h("b", {}, m.title), h("span", { class: "small muted" }, `Coming soon: ${fmt(m.have)} of ${fmt(m.need)} ${m.unit} so far.`),
          h("span", { class: "bar" }, h("i", { style: `width:${Math.min(100, 100 * m.have / m.need).toFixed(1)}%` }))));
        continue;
      }
      parts.push(h("h3", { class: "rail-head" }, m.title));
      if (key === "staying") parts.push(table(["Cause", "Typical comeback lasts", "Long ones last", "Comebacks"], m.result.map((x) => h("tr", {},
        h("td", {}, x.cause), h("td", { class: "num" }, `${x.median_days} days`), h("td", { class: "num" }, `${x.long} days`), h("td", { class: "num" }, fmt(x.n))))));
      if (key === "lead") parts.push(h("p", {}, `Of ${m.result.n} comebacks that also reached a chart, Wikipedia moved first ${Math.round(m.result.wiki_first * 100)}% of the time, typically by ${Math.abs(m.result.median_days)} days.`));
      if (key === "star") parts.push(table(["Person", "Separate comebacks", "Typical size", "Titles"], m.result.map((x) => h("tr", {},
        h("td", {}, h("b", {}, x.name || x.qid)), h("td", { class: "num" }, String(x.moments)), h("td", { class: "num" }, fmtX(x.median_lift)), h("td", { class: "num" }, String(x.titles)))), 10, "people"));
      if (key === "calibration") parts.push(table(["We said", "Forecasts", "It happened"], m.result.map((x) => h("tr", {},
        h("td", {}, x.said), h("td", { class: "num" }, fmt(x.n)), h("td", { class: "num" }, `${Math.round(x.happened * 100)}%`)))));
    }
    box.replaceChildren(...parts);
  }).catch(() => box.replaceChildren(h("p", { class: "muted" }, "These start building with each morning's edition.")));
  return box;
}


// ================= page charts: the week, the mystery map, the next six months =================
// Same look as the streamgraph: house colors, thin marks, hover for numbers, a table view.
function chartShell(label, title, sub, legend, note, tableRows, tableHead, draw) {
  if (typeof d3 === "undefined") return null;
  const chart = h("div", { class: "stream-chart" });
  const tip = h("div", { class: "tip2", hidden: "" });
  chart.append(tip);
  const sec = h("section", { class: "stream page-chart", "aria-label": label },
    h("div", { class: "stream-head" }, h("div", {}, h("h2", {}, title), sub ? h("p", {}, sub) : null)),
    legend && legend.length ? h("div", { class: "legend", role: "list" }, legend.map(([c, t]) => h("span", { role: "listitem" }, h("i", { style: `background:${c}` }), t))) : null,
    chart,
    note ? h("p", { class: "stream-note" }, note) : null,
    h("details", {}, h("summary", {}, "View as table"),
      h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, tableHead.map((x) => h("th", {}, x)))), h("tbody", {}, tableRows)))));
  const go = () => draw(chart, tip);
  requestAnimationFrame(go);
  return sec;
}
function placeTip(tip, px, py, W) {
  tip.hidden = false;
  const tw = tip.offsetWidth;
  const shift = px + tw / 2 > W - 2 ? "-100%" : px - tw / 2 < 2 ? "0%" : "-50%";
  tip.style.left = `${px}px`; tip.style.top = `${py}px`;
  tip.style.transform = `translate(${shift}, calc(-100% - 12px))`;
}

// ---------- Unexplained: the mystery map ----------
function mysteryMap(L) {
  const pts = L.filter((r) => r.baseline > 0).map((r) => ({ r, lift: Math.max(r.lift, r.lift3 || 0), base: r.baseline }));
  if (pts.length < 5) return null;
  const solved = (state.data.solved || []).map((x) => state.byQid[x.qid]).filter(Boolean)
    .map((r) => ({ r, lift: Math.max(r.lift, r.lift3 || 0), base: r.baseline }));
  const big = [...pts].sort((a, b) => b.lift * Math.log10(b.base + 1) - a.lift * Math.log10(a.base + 1));
  const rows = big.slice(0, 50).map((p) => h("tr", {}, h("td", {}, titleLink(p.r.qid, plain(p.r.label))),
    h("td", { class: "num" }, fmtX(p.lift)), h("td", { class: "num" }, fmt(p.base)), h("td", { class: "nowrap" }, short(p.r.spike_start))));
  return chartShell("The mystery map", "The mystery map",
    "Every open case: how big the jump is, and how many people usually care. The ones to solve are top right: well-known works having a big comeback nobody can explain.",
    [["var(--s3)", "Open case"], ["var(--muted)", "Solved this week"]], "Both scales grow by multiples. Hover or tap a dot for the title; click to open it.",
    rows, ["Title", "Jump", "Usual views a day", "Since"],
    (chart, tip) => {
      const Wd = chart.clientWidth || 800, narrow = Wd < 600;
      const H = narrow ? 300 : 380, M = { t: 12, r: 12, b: 34, l: narrow ? 40 : 52 };
      const all = [...pts, ...solved];
      const x = d3.scaleLog().domain([Math.max(1.5, d3.min(all, (p) => p.lift) / 1.2), d3.max(all, (p) => p.lift) * 1.2]).range([M.l, Wd - M.r]);
      const y = d3.scaleLog().domain([Math.max(1, d3.min(all, (p) => p.base) / 1.5), d3.max(all, (p) => p.base) * 1.5]).range([H - M.b, M.t]);
      const svg = d3.create("svg").attr("viewBox", `0 0 ${Wd} ${H}`).attr("height", H).attr("role", "img")
        .attr("aria-label", `Scatter of ${pts.length} unexplained comebacks: size of the jump against usual daily views. A table view follows.`);
      const xt = (narrow ? [3, 10, 30, 100, 300] : [2, 3, 5, 10, 20, 50, 100, 200, 500]).filter((v) => v >= x.domain()[0] && v <= x.domain()[1]);
      const yt = [1, 10, 100, 1000, 10000, 100000].filter((v) => v >= y.domain()[0] && v <= y.domain()[1]);
      const grid = svg.append("g").attr("class", "grid");
      xt.forEach((v) => { grid.append("line").attr("x1", x(v)).attr("x2", x(v)).attr("y1", M.t).attr("y2", H - M.b);
        grid.append("text").attr("class", "ax").attr("x", x(v)).attr("y", H - M.b + 15).attr("text-anchor", "middle").text(`${v}×`); });
      yt.forEach((v) => { grid.append("line").attr("x1", M.l).attr("x2", Wd - M.r).attr("y1", y(v)).attr("y2", y(v));
        grid.append("text").attr("class", "ax").attr("x", M.l - 6).attr("y", y(v) + 4).attr("text-anchor", "end").text(v >= 1000 ? `${v / 1000}k` : v); });
      svg.append("text").attr("class", "ax-title").attr("x", Wd - M.r).attr("y", H - 4).attr("text-anchor", "end").text("How big the jump is →");
      svg.append("text").attr("class", "ax-title").attr("x", M.l).attr("y", M.t + 2).attr("dy", "0.7em").attr("dx", 6).text("↑ Usual views a day");
      const show = (p, e) => { const [px, py] = d3.pointer(e, chart);
        tip.replaceChildren(h("b", {}, plain(p.r.label)), ` (${p.r.release_year}) · ${fmtX(p.lift)} its usual interest`,
          h("small", {}, `${fmt(p.base)} views on a normal day · ${solved.includes(p) ? "solved: " + reasonOf(p.r).label : "since " + short(p.r.spike_start)}`));
        placeTip(tip, px, py, Wd); };
      svg.append("g").selectAll("circle").data(pts).join("circle").attr("class", "mm-dot")
        .attr("cx", (p) => x(p.lift)).attr("cy", (p) => y(p.base)).attr("r", 5)
        .on("pointermove pointerdown", function (e, p) { d3.select(this).attr("r", 7); show(p, e); })
        .on("pointerleave", function () { d3.select(this).attr("r", 5); tip.hidden = true; })
        .on("click", (e, p) => openWork(p.r.qid));
      svg.append("g").selectAll("circle").data(solved).join("circle").attr("class", "mm-solved")
        .attr("cx", (p) => x(p.lift)).attr("cy", (p) => y(p.base)).attr("r", 6)
        .on("pointermove pointerdown", function (e, p) { show(p, e); }).on("pointerleave", () => { tip.hidden = true; })
        .on("click", (e, p) => openWork(p.r.qid));
      // Name the three biggest, if there's room.
      const placed = [];
      // Automatic labels skip titles with slurs in them (the dot, hover and table still show them).
      const unfit = /nigg|fag|tranny|retard|kike|spic\b|chink|wetback/i;
      for (const p of big.filter((p) => !unfit.test(p.r.label)).slice(0, narrow ? 2 : 4)) {
        const t = plain(p.r.label).slice(0, 22), w = t.length * 6.4, right = x(p.lift) + 8 + w > Wd - M.r;
        const tx = right ? x(p.lift) - 8 : x(p.lift) + 8, ty = y(p.base) + 4, x0 = right ? tx - w : tx;
        const box = [x0, ty - 11, x0 + w, ty + 3];
        if (placed.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
        placed.push(box);
        svg.append("text").attr("class", "lbl").attr("x", tx).attr("y", ty).attr("text-anchor", right ? "end" : "start").text(t);
      }
      chart.querySelector("svg")?.remove();
      chart.append(svg.node());
    });
}

// ---------- corrections log (site/data/corrections.json, edited by hand) ----------
function correctionsList() {
  const box = h("div", {}, h("p", { class: "muted" }, "No corrections yet."));
  loadOnce("data/corrections.json").then((xs) => {
    if (!xs.length) return;
    box.replaceChildren(table(["Date", "What we said", "What's right"], xs.map((x) => h("tr", {},
      h("td", { class: "nowrap" }, fmtDate(x.date)), h("td", {}, x.said), h("td", {}, x.fixed))), 12, "corrections"));
  }).catch(() => {});
  return box;
}

// ---------- embed ----------
function embedBox(base) {
  const code = `<iframe src="${base}embed.html?n=10" title="The Rallyback: today's top comebacks" width="100%" height="460" style="border:0;max-width:480px"></iframe>`;
  return h("div", { class: "embed-box" },
    h("p", {}, "Copy this into any web page. It shows the 10 biggest comebacks of the day, with credit and a link back."),
    h("pre", { class: "code" }, code),
    h("button", { type: "button", class: "copy", onclick: (e) => copy(code, e.target) }, "Copy code"),
    " ", h("a", { href: "embed.html?n=10", target: "_blank", rel: "noopener" }, "Preview →"));
}

// Floating "back to top": shows once the reader is well down the page.
const toTop = h("button", { type: "button", class: "to-top", "aria-label": "Back to top", title: "Back to top", hidden: "",
  onclick: () => window.scrollTo({ top: 0, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }) }, "↑");
document.body.append(toTop);
window.addEventListener("scroll", () => {
  $("tip").hidden = true;
  toTop.hidden = window.scrollY < window.innerHeight * 1.5;
}, { passive: true });
init();
