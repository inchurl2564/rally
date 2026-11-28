"""
The archive: a permanent page for every title The Rallyback has ever caught coming back,
plus the searchable index, leaderboards and the weekly roundup. Built each night from the
permanent record (site/data/history), today's edition and the forecast checks.

  site/data/works/<n>.json     titles bundled 256 ways (n = the Wikidata number mod 256, see
                               shard_of), each {qid: title}: every comeback (dates, size, causes),
                               its chart, what's coming for it, related titles. Bundled so the
                               file count stays fixed as titles pile up (Cloudflare caps a deploy
                               at 20,000 files)
  site/data/works/index.json   every title, compact, for "Has it come back before?" search
  site/w/<qid>.html            a readable page per title, written out in plain HTML so search
                               engines and link previews see it: why it's back, every comeback,
                               a chart, free ways to read it (books), related titles
  site/sitemap.xml, robots.txt the list of those pages, for search engines
  site/index.html              today's top 10 written into the homepage (between markers), so
                               the page has real text before the app loads
  site/data/leaders.json       biggest comebacks this month and year; decades and franchises
                               that are hot this week
  site/data/weekly/<week>.json "This week in comebacks", one file per ISO week
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse

import reading

EPISODE_GAP = 7          # days off the list before a return counts as a new comeback
UNEXPLAINED = {"unexplained", "weak link", "lookup failed", "common thread"}
SET_ASIDE = {"seasonal", "automated?", "front page"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


SHARDS = 256            # site/app.js has the same number (WORK_SHARDS); change both together


def shard_of(qid: str) -> int:
    return int(qid[1:]) % SHARDS


class Works:
    """Every title's data, read from and written back to the bundle files (site/data/works/<n>.json).
    Also reads the old one-file-per-title layout (works/Q123.json) and removes it on save."""

    def __init__(self, site: str):
        self.dir = os.path.join(site, "data", "works")
        self.docs: dict[str, dict] = {}
        self.dirty: set[int] = set()
        self.legacy: list[str] = []
        names = sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []
        for f in names:
            if re.fullmatch(r"Q\d+\.json", f):
                d = _load(os.path.join(self.dir, f), None)
                if isinstance(d, dict):
                    self.docs[f[:-5]] = d
                    self.dirty.add(shard_of(f[:-5]))
                self.legacy.append(f)
        for f in names:
            if re.fullmatch(r"\d+\.json", f):
                for q, d in (_load(os.path.join(self.dir, f), {}) or {}).items():
                    self.docs.setdefault(q, d)

    def get(self, qid: str, default=None):
        return self.docs.get(qid, default)

    def put(self, qid: str, doc: dict) -> None:
        self.docs[qid] = doc
        self.dirty.add(shard_of(qid))

    def save(self) -> None:
        for n in sorted(self.dirty):
            part = {q: self.docs[q] for q in sorted(self.docs, key=lambda q: int(q[1:])) if shard_of(q) == n}
            _save(os.path.join(self.dir, f"{n}.json"), part)
        for f in self.legacy:
            os.remove(os.path.join(self.dir, f))
        self.dirty, self.legacy = set(), []


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def load_history(site: str) -> dict:
    """All months of the permanent record merged: works, names, and every day's rows (as dicts)."""
    hdir = os.path.join(site, "data", "history")
    works, names, days = {}, {}, {}
    for f in sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []:
        m = _load(os.path.join(hdir, f), {})
        fields = m.get("fields", [])
        works.update(m.get("works", {}))
        names.update(m.get("names", {}))
        for run, rows in m.get("days", {}).items():
            days[run] = {q: dict(zip(fields, row)) for q, row in rows.items()}
    return {"works": works, "names": names, "days": days}


def episodes_of(qid: str, days: dict, runs: list[str]) -> list[dict]:
    """Group the days a title was on the list into separate comebacks."""
    seen = [(r, days[r][qid]) for r in runs if qid in days[r]]
    out, cur = [], None
    for run, row in seen:
        if cur and (_d(run) - _d(cur["last_seen"])).days <= EPISODE_GAP:
            cur["rows"].append((run, row))
            cur["last_seen"] = run
        else:
            cur = {"first_seen": run, "last_seen": run, "rows": [(run, row)]}
            out.append(cur)
    eps = []
    for e in out:
        rows = [r for _, r in e["rows"]]
        best = max(rows, key=lambda r: (r.get("rally_score") or 0, r.get("lift") or 0))
        # The reason comes from the latest day that found one: research later in a comeback
        # (a new source, an editor's note) knows more than its biggest day did.
        found = [r for r in rows if r.get("verdict") not in UNEXPLAINED | SET_ASIDE]
        why = found[-1] if found else best
        eps.append({"start": min(str(r.get("spike_start") or e["first_seen"]) for r in rows)[:10],
                    "first_seen": e["first_seen"], "last_seen": e["last_seen"], "days": len(rows),
                    "peak_lift": max(r.get("lift") or 0 for r in rows), "score": best.get("rally_score"),
                    "verdict": why.get("verdict"), "causes": why.get("causes") or []})
    return eps


def _cause_text(c: list, names: dict, notes: dict) -> str | None:
    kind, qid, detail, date = (c + [None] * 4)[:4]
    who = names.get(qid) if qid else None
    when = f" ({dt.date.fromisoformat(date):%b %-d, %Y})" if date else ""
    if kind == "death" and who:
        return f"{who}{f', {detail},' if detail else ''} died{when}"
    if kind in ("derivative", "same-creator") and who:
        return f"{(detail or 'New release')[0].upper()}{(detail or 'new release')[1:]}: {who}{when}"
    if kind == "anniversary":
        return f"{(detail or 'Anniversary')[0].upper()}{(detail or 'anniversary')[1:]}{when}"
    if kind == "public domain":
        return f"Entered the public domain{when}"
    if kind == "honor" and detail:
        yr = f" ({date[:4]})" if date else ""
        if who and who != detail:                      # someone credited was honored
            return f"{who} received the {detail}{yr}"
        return f"Honored: {detail}{yr}"
    if kind == "ripple" and who:
        return f"News about {who}{f' ({detail})' if detail else ''}{when}"
    if kind == "common thread" and who:            # a shared person, not a known reason
        return f"Other work with {who} came back at the same time{when}"
    if kind == "note":
        return notes.get(detail)
    if kind == "coverage" and detail:
        return f"Likely cause from news and edits: {detail}"
    return None


def _causes(eps_causes: list, names: dict, notes: dict) -> list[str]:
    seen, out = set(), []
    order = {"note": 0, "death": 1, "derivative": 2, "same-creator": 3, "ripple": 4, "coverage": 5, "anniversary": 6, "public domain": 6, "honor": 4, "common thread": 7}
    for c in sorted(eps_causes, key=lambda c: order.get(c[0], 9)):
        t = _cause_text(c, names, notes)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:4]


def build(site: str, site_url: str = "") -> None:
    hist = load_history(site)
    runs = sorted(hist["days"])
    if not runs:
        return
    latest = _load(os.path.join(site, "data", "latest.json"), {})
    R = {r["qid"]: r for r in latest.get("results", [])}
    names, works = hist["names"], hist["works"]
    notes = {n["id"]: n.get("note") for n in _load("annotations.json", []) if isinstance(n, dict) and n.get("id")}
    wdir = os.path.join(site, "data", "works")
    store = Works(site)
    today_run = runs[-1]
    cu = latest.get("coming_up", {})
    coming: dict[str, list] = {}
    for c in cu.get("derivatives", []):
        coming.setdefault(c["old"], []).append({"type": "release", "date": c["date"], "text": f"{c['rel']} {c['new_label']}",
                                                 "prediction": c.get("prediction")})
    for a in cu.get("anniversaries", []):
        coming.setdefault(a["qid"], []).append({"type": "anniversary", "date": a["date"], "text": f"{a['years']}th anniversary",
                                                "prediction": a.get("prediction")})
    for a in cu.get("seasonal", []):
        coming.setdefault(a["qid"], []).append({"type": "seasonal", "date": a["date"],
                                                "text": "back every year" + (f" ({a['holiday']})" if a.get("holiday") else ""),
                                                "prediction": a.get("prediction")})
    # Who is related to whom: same franchise, or the same person / release behind a comeback.
    by_franchise: dict[str, set] = {}
    by_cause: dict[str, set] = {}
    for q, w in works.items():
        for f in (w[3] if len(w) > 3 else []) or []:
            by_franchise.setdefault(f, set()).add(q)
    for run in runs[-120:]:
        for q, row in hist["days"][run].items():
            for c in row.get("causes") or []:
                if c[1] and c[0] != "anniversary":
                    by_cause.setdefault(c[1], set()).add(q)

    index, written = [], 0
    for q, w in works.items():
        label, kind, year = w[0], w[1], w[2]
        fr = (w[3] if len(w) > 3 else []) or []
        eps = episodes_of(q, hist["days"], runs)
        if not eps:
            continue
        best = max((e["score"] or 0) for e in eps)
        index.append([q, label, str(year), kind, len(eps), eps[-1]["last_seen"], best])
        on_today = q in R
        if not on_today and q not in coming and store.get(q):
            continue                                  # nothing new for this title tonight
        old = store.get(q, {})
        r = R.get(q, {})
        rel: dict[str, str] = {}
        for f in fr:
            for o in by_franchise.get(f, ()):
                if o != q:
                    rel.setdefault(o, f"Also in {names.get(f, 'the same series')}")
        for e in eps[-2:]:
            for c in e["causes"]:
                if c[1] and c[0] != "anniversary":
                    for o in by_cause.get(c[1], ()):
                        if o != q:
                            rel.setdefault(o, f"Also back with {names.get(c[1], 'the same story')}")
        # Titles back right now first, then a fixed order (sets have no order; this keeps files from churning).
        related = sorted(rel.items(), key=lambda kv: (kv[0] not in R, -(R.get(kv[0], {}).get("score") or 0), kv[0]))[:8]
        doc = {
            "qid": q, "label": label, "kind": kind, "year": str(year),
            "title": r.get("title") or old.get("title"),
            "image": r.get("image") or old.get("image"), "image_of": r.get("image_of") if r else old.get("image_of"),
            "franchises": [{"qid": f, "name": names.get(f)} for f in fr if names.get(f)],
            "episodes": [{**{k: e[k] for k in ("start", "first_seen", "last_seen", "days", "peak_lift", "score", "verdict")},
                          "causes": _causes(e["causes"], names, notes)} for e in eps],
            "on_today": on_today,
            "spark": r.get("spark") or old.get("spark"), "spark_start": r.get("spark_start") or old.get("spark_start"),
            "baseline": r.get("baseline") or old.get("baseline"),
            "coming": sorted(coming.get(q, []), key=lambda x: x["date"]),
            "related": [{"qid": o, "label": works[o][0], "year": str(works[o][2]), "why": why} for o, why in related if o in works],
            "updated": today_run,
        }
        store.put(q, doc)
        written += 1
    index.sort(key=lambda x: (-x[4], -(x[6] or 0)))
    _save(os.path.join(wdir, "index.json"), {"fields": ["qid", "label", "year", "kind", "comebacks", "last_seen", "best_score"],
                                            "works": index, "updated": today_run})
    leaders(site, hist, runs)
    weekly(site, hist, runs, latest)
    pages(site, site_url, [q for q, *_ in index], hist, store)
    privacy_page(site, site_url)
    store.save()
    homepage(site, latest, hist)
    log(f"      archive: {len(index)} titles ({written} pages updated)")


# ---------- readable title pages (plain HTML, no script needed) ----------

REASON = {**{v: "In the news" for v in ("ripple", "editor", "coverage")},
          **{v: "New release" for v in ("derivative", "same-creator", "editor-release")},
          **{v: "In memoriam" for v in ("death", "editor-death")}, "anniversary": "Anniversary", "public domain": "Anniversary", "honor": "In the news",
          **{v: "Unexplained" for v in UNEXPLAINED}, **{v: "Set aside" for v in SET_ASIDE}}
CONFIDENCE = {**{v: ("Confirmed", "an editor checked the reason against a published source") for v in ("editor", "editor-release", "editor-death")},
              **{v: ("Likely", "a matching event is on record at the right time") for v in ("death", "derivative", "same-creator", "anniversary", "public domain", "honor")},
              **{v: ("Possible", "inferred from news headlines, Wikipedia edits or a related page jumping") for v in ("ripple", "coverage")}}
NOUN = {"manga/comic": "comic"}
SCHEMA_TYPE = {"film": "Movie", "TV series": "TVSeries", "song": "MusicRecording", "album": "MusicAlbum",
               "video game": "VideoGame", "book": "Book", "manga/comic": "Book"}


def _day(s: str) -> str:
    return f"{dt.date.fromisoformat(s[:10]):%b %-d, %Y}"


def _sentence(s: str) -> str:
    """A cause as a sentence: exactly one full stop at the end."""
    return s.rstrip(". ") + "."


def _times(n: int) -> str:
    return "once" if n == 1 else "twice" if n == 2 else f"{n} times"


def _chart(spark: list, baseline: float, label: str) -> str:
    """The last 12 months of daily views, as a small inline picture (same log scale as the site)."""
    import math
    vals = [v or 0 for v in (spark or [])][-365:]
    if len(vals) < 30:
        return ""
    n, H = len(vals), 60
    top = max(max(vals), (baseline or 1) * 2, 1)
    y = lambda x: H - (math.log10(1 + x) / math.log10(1 + top)) * (H - 4)
    pts = " ".join(f"{i},{y(v):.1f}" for i, v in enumerate(vals))
    peak = max(vals)
    return (f'<figure class="chart"><svg viewBox="0 0 {n - 1} {H}" preserveAspectRatio="none" role="img" '
            f'aria-label="Daily Wikipedia views over the last 12 months for {html.escape(label)}: usually about {round(baseline or 0):,} a day, peak {peak:,}.">'
            f'<polygon class="area" points="0,{H} {pts} {n - 1},{H}"/>'
            f'<line class="base" x1="0" x2="{n - 1}" y1="{y(baseline or 0):.1f}" y2="{y(baseline or 0):.1f}"/>'
            f'<polyline class="line" points="{pts}"/></svg>'
            f'<figcaption>Daily views, last 12 months. Dashed line: its usual level (about {round(baseline or 0):,} a day).</figcaption></figure>')


PAGE_CSS = """
:root{--paper:#faf8f4;--paper-2:#f2eee7;--ink:#1b1a1f;--muted:#6e6a64;--hair:#e5e0d7;--red:#c2401e;--red-ink:#fff;--tint:rgba(194,64,30,.07)}
@media (prefers-color-scheme:dark){:root{--paper:#141317;--paper-2:#1d1c21;--ink:#efece6;--muted:#a29d96;--hair:#2e2c32;--red:#ff7a52;--red-ink:#141317;--tint:rgba(255,122,82,.12)}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 "Libre Franklin",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:820px;margin:0 auto;padding:0 16px}a{color:inherit;text-underline-offset:3px}
.mast{border-bottom:3px solid var(--ink);padding:18px 0 12px}.brand{display:inline-block;text-decoration:none}.brand img{display:block;height:30px;width:auto}

.tag{margin:4px 0 0;color:var(--muted);font-size:14px}
.kicker{font:800 12px/1.2 "Libre Franklin",sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--red);margin:28px 0 6px}
h1{font:900 clamp(30px,6vw,46px)/1.05 "Playfair Display",Georgia,serif;letter-spacing:-.02em;margin:0 0 10px}
h2{font:800 22px/1.2 "Playfair Display",Georgia,serif;margin:32px 0 8px;padding-top:12px;border-top:1px solid var(--hair)}
.dek{font-size:19px;line-height:1.45;margin:0 0 14px}.muted,figcaption,.small{color:var(--muted);font-size:14px}
.photo{margin:16px 0;max-width:480px}.photo img{width:100%;height:auto;display:block;background:var(--paper-2)}
.chart{margin:16px 0}.chart svg{width:100%;height:90px;display:block;background:var(--paper-2)}
.chart .area{fill:var(--tint)}.chart .line{fill:none;stroke:var(--red);stroke-width:2;vector-effect:non-scaling-stroke}
.chart .base{stroke:var(--muted);stroke-dasharray:4 4;stroke-width:1;vector-effect:non-scaling-stroke}
.conf{display:inline-block;font:700 12px/1 "Libre Franklin",sans-serif;text-transform:uppercase;letter-spacing:.06em;padding:5px 8px;border:1px solid var(--hair);margin-right:6px}
table{width:100%;border-collapse:collapse;font-size:15px}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--hair);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}.num{text-align:right;white-space:nowrap}
ul{padding-left:20px}li{margin:4px 0}
.ranked{padding-left:24px}.ranked li{margin:0 0 18px}.ranked h3{font:800 20px/1.25 "Playfair Display",Georgia,serif;margin:0 0 4px}.ranked p{margin:0 0 6px}
svg.mini{width:100%;max-width:320px;height:36px;display:block;background:var(--paper-2)}
svg.mini .area{fill:var(--tint)}svg.mini .line{fill:none;stroke:var(--red);stroke-width:2;vector-effect:non-scaling-stroke}
svg.mini .base{stroke:var(--muted);stroke-dasharray:3 3;stroke-width:1;vector-effect:non-scaling-stroke}
.bars{list-style:none;padding:0}.bars li{display:flex;align-items:center;gap:10px;margin:0 0 8px;flex-wrap:wrap}
.bar-label{flex:0 0 120px}.bar{display:inline-block;height:14px;background:var(--red);border-radius:0 4px 4px 0;min-width:4px}
.btn{display:inline-block;background:var(--red);color:var(--red-ink);font:700 13px/1 "Libre Franklin",sans-serif;text-transform:uppercase;letter-spacing:.06em;padding:13px 18px;text-decoration:none;margin:24px 0 8px}
footer{margin-top:48px;padding:20px 0 40px;border-top:3px solid var(--ink);background:var(--paper-2);font-size:14px;color:var(--muted)}
.mast,footer{background:#f3c716;color:#1b1a1f}.mast{border-bottom-color:#1b1a1f;padding:18px 0 14px}footer{border-top-color:#1b1a1f;color:#4a4540}
.mast .tag{color:#4a4540}.brand img{filter:none!important}footer a{color:#1b1a1f}footer .small{color:#4a4540}
"""


def thin(doc: dict) -> bool:
    """Too little to say yet for a search result: one short comeback (2 days or less on our list)
    with no known reason. Kept out of Google until it has more; still on the site and shareable."""
    eps = doc.get("episodes") or []
    return (len(eps) == 1 and sum(x["days"] for x in eps) <= 2
            and (not eps[-1]["causes"] or eps[-1]["verdict"] in UNEXPLAINED))


def _page(site_url: str, doc: dict) -> str:
    e = html.escape
    base = site_url.rstrip("/")
    q, label, year, kind = doc["qid"], doc["label"], doc["year"], doc["kind"]
    eps = doc["episodes"]
    last = eps[-1]
    noun = NOUN.get(kind, kind)
    reason = REASON.get(last["verdict"], "")
    why = last["causes"]
    app = f"{base}/?work={q}"
    if doc.get("on_today"):
        lead = f"{label}, the {year} {noun}, is back: {last['peak_lift']}× its usual interest since {_day(last['start'])}."
        title = f"Why is {label} ({year}) trending again? | The Rallyback"
    else:
        lead = f"{label}, the {year} {noun}, last came back on {_day(last['start'])}, reaching {last['peak_lift']}× its usual interest."
        title = f"Why {label} ({year}) was trending again | The Rallyback"
    if len(eps) > 1:
        lead += f" It has come back {_times(len(eps))} since we started tracking in November 2026."
    desc = lead + (f" Why: {_sentence(why[0])}" if why and last["verdict"] not in UNEXPLAINED else " The reason isn't known yet.")
    conf = CONFIDENCE.get(last["verdict"])
    img = (f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(doc['image'])}?width=1200"
           if doc.get("image") else "")
    share_img = img or f"{base}/og.png"            # the branded card when there's no picture
    wiki = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(doc['title'])}" if doc.get("title") else ""
    canon = f"{base}/w/{q}"
    ld = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": canon, "description": desc,
          "dateModified": doc.get("updated"), "inLanguage": "en",
          "publisher": {"@type": "Organization", "name": "The Rallyback", "url": base + "/"},
          "about": {"@type": SCHEMA_TYPE.get(kind, "CreativeWork"), "name": label, "dateCreated": str(year),
                    "sameAs": [f"https://www.wikidata.org/wiki/{q}"] + ([wiki] if wiki else [])}}
    if img:
        ld["image"] = img
    parts = [f'<p class="kicker">{e(reason + " · " if reason and reason != "Set aside" else "")}{e(kind[0].upper() + kind[1:])}, {e(str(year))}</p>',
             f"<h1>{e(label)} ({e(str(year))})</h1>", f'<p class="dek">{e(lead)}</p>']
    if img:
        alt = f"{doc['image_of']}, connected to {label}" if doc.get("image_of") else label
        cap = f"<figcaption>Pictured: {e(doc['image_of'])}</figcaption>" if doc.get("image_of") else ""
        parts.append(f'<figure class="photo"><img src="{e(img.replace("width=1200", "width=800"))}" alt="{e(alt)}" loading="lazy">{cap}</figure>')
    parts.append(f"<h2>{'Why it’s back' if doc.get('on_today') else 'Why it came back'}</h2>")
    if why and last["verdict"] in UNEXPLAINED:
        parts.append("<p>We don’t know for sure yet. What we do know:</p><ul>" + "".join(f"<li>{e(c)}</li>" for c in why) + "</ul>"
                     f'<p><a href="{e(app)}">Know why? Tell us on The Rallyback</a>.</p>')
    elif why:
        parts.append("<ul>" + "".join(f"<li>{e(c)}</li>" for c in why) + "</ul>")
        if conf:
            parts.append(f'<p class="small"><span class="conf">{conf[0]}</span>How sure we are: {e(conf[1])}.</p>')
    else:
        parts.append(f'<p>We don’t know yet. Nothing on record explains it: no new release, death or anniversary at the right time. '
                     f'<a href="{e(app)}">Know why? Tell us on The Rallyback</a>.</p>')
    parts.append(_chart(doc.get("spark") or [], doc.get("baseline") or 0, label))
    if doc.get("read"):
        parts.append("<h2>Read it free</h2><ul>" + "".join(
            f'<li><a href="{e(x["url"])}" rel="noopener">{e(x["label"])}</a></li>' for x in doc["read"]) + "</ul>")
    rows = "".join(f'<tr><td>{_day(x["start"])}</td><td>{e(" · ".join(x["causes"]) or "Reason unknown")}</td>'
                   f'<td class="num">{x["peak_lift"]}×</td><td class="num">{x["days"]} day{"" if x["days"] == 1 else "s"}</td></tr>'
                   for x in reversed(eps))
    parts.append(f"<h2>Every comeback</h2><table><thead><tr><th>Started</th><th>Why</th><th class='num'>Peak</th><th class='num'>On our list</th></tr></thead><tbody>{rows}</tbody></table>"
                 '<p class="small">Peak: how many times its usual daily interest it reached.</p>')
    if doc.get("coming"):
        parts.append("<h2>Coming up</h2><ul>" + "".join(f"<li>{_day(c['date'])}: {e(c['text'])}</li>" for c in doc["coming"]) + "</ul>")
    if doc.get("related"):
        parts.append("<h2>Related</h2><ul>" + "".join(
            f'<li><a href="{e(base)}/w/{e(r["qid"])}">{e(r["label"])} ({e(r["year"])})</a> <span class="small">· {e(r["why"])}</span></li>'
            for r in doc["related"]) + "</ul>")
    parts.append(f'<a class="btn" href="{e(app)}">Open on The Rallyback</a>'
                 '<p class="small">Follow this title, see today’s other comebacks and tell us what we got wrong.</p>')
    parts.append('<p class="small">Interest is measured from daily views of '
                 + (f'<a href="{e(wiki)}" rel="noopener">its Wikipedia article</a>' if wiki else "its Wikipedia article")
                 + f', against its usual level over the previous year. Updated {_day(doc.get("updated") or last["last_seen"])}.</p>')
    return _shell(base, title, desc, canon, share_img, ld, parts, noindex=thin(doc))


def _shell(base: str, title: str, desc: str, canon: str, img: str, ld: dict, parts: list, noindex: bool = False,
           og_type: str = "article") -> str:
    """The plain-HTML page around a title page or a weekly roundup."""
    e = html.escape
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canon)}">
<link rel="icon" type="image/png" sizes="32x32" href="{e(base)}/logo/favicon-32.png"><link rel="apple-touch-icon" href="{e(base)}/logo/apple-touch-icon.png">
<meta property="og:type" content="{og_type}"><meta property="og:site_name" content="The Rallyback"><meta property="og:url" content="{e(canon)}">
<meta property="og:title" content="{e(title.replace(" | The Rallyback", ""))}"><meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(img)}"><meta name="twitter:card" content="summary_large_image">
{'<meta name="robots" content="noindex, follow">' if noindex else ''}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Franklin:wght@400;700;800&family=Playfair+Display:wght@800;900&display=swap">
<style>{PAGE_CSS}</style>
<script type="application/ld+json">{ld_json}</script>
</head><body>
<header class="mast"><div class="wrap"><a class="brand" href="{e(base)}/"><img src="{e(base)}/logo/wordmark.webp" alt="The Rallyback" width="2000" height="287"></a>
<p class="tag">Old movies, shows, songs, games and books people are suddenly into again, and why.</p></div></header>
<main class="wrap">
{chr(10).join(p for p in parts if p)}
</main>
<footer><div class="wrap">Every morning, The Rallyback finds older movies, shows, songs, games and books that people are suddenly into again, and tells you why.
<a href="{e(base)}/">Today’s comebacks</a> · <a href="{e(base)}/week/">Every week</a> · <a href="{e(base)}/?tab=about">About us</a> · <a href="{e(base)}/?tab=subscribe">Weekly newsletter</a> · <a href="{e(base)}/privacy">Privacy</a>
<p class="small copy">© {dt.date.today().year} Castle Bridge Media</p></div></footer>
</body></html>
"""


PRIVACY_UPDATED = "2026-11-28"      # change when the policy's substance changes


def privacy_page(site: str, site_url: str) -> None:
    """site/privacy.html: what the site and the newsletter collect, in plain words.
    Keep it true: update it when the site adds analytics, ads, affiliate links or a new outside service."""
    base = site_url.rstrip("/")
    upd = dt.date.fromisoformat(PRIVACY_UPDATED).strftime("%B %-d, %Y")
    sections = [
        ("The short version",
         "<p>We collect as little as we can. Reading The Rallyback needs no account, sets no cookies and has no ads or "
         "tracking. The only personal information we get is what you choose to send us: your email address if you "
         "subscribe to the newsletter, and whatever you write in a tip, correction or message. We don't sell or rent "
         "anyone's personal information, and we don't use it for targeted advertising.</p>"),
        ("Reading the site",
         "<ul><li><b>No cookies, no analytics, no ads.</b> We don't track what you read.</li>"
         "<li><b>Saved in your own browser only:</b> the titles you follow (the ☆ Follow button) and whether you've "
         "seen the \u201cHow it works\u201d box. This stays on your device; we never receive it. Clearing your browser's "
         "site data removes it.</li>"
         "<li><b>Services that load parts of the page:</b> the site is hosted by Cloudflare; fonts come from Google "
         "Fonts; pictures come from Wikimedia Commons; the chart library comes from Cloudflare's code library "
         "(cdnjs); the newsletter sign-up box comes from Beehiiv. Like any website, these services receive your "
         "IP address and browser details when your browser asks them for a file. Their own privacy policies apply.</li>"
         "<li><b>Do Not Track:</b> because we don't track you, there's nothing for Do Not Track or Global Privacy "
         "Control signals to turn off. The site works the same whether or not your browser sends them.</li>"
         "<li><b>No other tracking:</b> apart from the services listed above, we don't let any other company collect "
         "information about what you do on our site or follow you across other websites.</li></ul>"),
        ("The newsletter",
         "<p>If you subscribe, your email address is held by <a href=\"https://www.beehiiv.com/privacy\">Beehiiv</a>, "
         "which sends the newsletter for us. Beehiiv may record whether emails are opened and links clicked, which "
         "helps us see what readers find useful. Every issue has a one-click unsubscribe link. We don't sell, rent or "
         "share subscriber addresses.</p>"),
        ("Tips, corrections and messages",
         "<p>The \u201cKnow why? Tell us\u201d, \u201cReport a correction\u201d and contact forms send what you write to a "
         "Google Form we manage (<a href=\"https://policies.google.com/privacy\">Google's privacy policy</a>). Your name "
         "and email are optional except where you want a reply. We use them only to check the tip and answer you. "
         "If a tip becomes an editor's note, we credit it as \u201ca reader tip\u201d, never by name. Email to "
         "hello@therallyback.com reaches our inbox and is kept only as long as we need it.</p>"),
        ("Our data about titles",
         "<p>The comebacks we report are built from public, aggregate data (for example, Wikipedia page views, which "
         "count visits without saying who made them). We don't collect information about individual readers to make it.</p>"),
        ("Your choices",
         "<p>You can unsubscribe at any time from any issue, and ask us to see or delete anything you've sent us by "
         "writing to hello@therallyback.com. The site isn't aimed at children under 13, and we don't knowingly collect "
         "their information.</p>"),
        ("Who we are",
         "<p>The Rallyback is made by Castle Bridge Media, PO Box 57, Littleton, CO 80160. Questions: hello@therallyback.com.</p>"),
        ("Changes",
         f"<p>If we change how we handle information, we'll update this page and the date below. Last updated {upd}.</p>"),
    ]
    parts = ['<p class="kicker">About us</p><h1 class="hed">Privacy</h1>']
    for head, body in sections:
        parts.append(f"<h2>{html.escape(head)}</h2>{body}")
    page = _shell(base, "Privacy | The Rallyback", "What The Rallyback collects (very little) and how the newsletter and "
                  "reader tips are handled.", f"{base}/privacy", f"{base}/og.png",
                  {"@context": "https://schema.org", "@type": "WebPage", "name": "Privacy", "url": f"{base}/privacy",
                   "dateModified": PRIVACY_UPDATED}, parts, og_type="website")
    _write_if_changed(os.path.join(site, "privacy.html"), page)


def _spark(vals: list, baseline: float) -> str:
    """A tiny three-week trend line for the weekly roundup."""
    import math
    vals = [v or 0 for v in vals or []]
    if len(vals) < 5:
        return ""
    n, H = len(vals), 30
    top = max(max(vals), (baseline or 1) * 2, 1)
    y = lambda x: H - (math.log10(1 + x) / math.log10(1 + top)) * (H - 3)
    pts = " ".join(f"{i},{y(v):.1f}" for i, v in enumerate(vals))
    return (f'<svg class="mini" viewBox="0 0 {n - 1} {H}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polygon class="area" points="0,{H} {pts} {n - 1},{H}"/>'
            f'<line class="base" x1="0" x2="{n - 1}" y1="{y(baseline or 0):.1f}" y2="{y(baseline or 0):.1f}"/>'
            f'<polyline class="line" points="{pts}"/></svg>')


def _span(a: str, b: str) -> str:
    """'Nov 16–22, 2026' or 'Nov 30 – Dec 6, 2026'."""
    d1, d2 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    if d1.month == d2.month:
        return f"{d1:%b %-d}–{d2:%-d, %Y}"
    return f"{d1:%b %-d} – {d2:%b %-d, %Y}" if d1.year == d2.year else f"{d1:%b %-d, %Y} – {d2:%b %-d, %Y}"


MONTH_CAUSE = {"death": "a death in the news", "legal": "legal headlines", "streaming": "a streaming debut",
               "broadcast": "a TV or radio airing", "viral": "a viral moment online", "sync placement": "a placement in a show, ad or trailer",
               "award": "awards buzz", "re-release": "a re-release or restoration", "remake/sequel news": "remake or sequel news",
               "new season": "a new season or special", "anniversary": "an anniversary", "auction/sale": "a big auction or sale",
               "sports/event": "a big live event", "politics": "politics"}
MONTH_REASON = {"ripple": "In the news", "editor": "In the news", "coverage": "In the news", "honor": "In the news",
                "derivative": "New release", "same-creator": "New release", "editor-release": "New release",
                "death": "In memoriam", "editor-death": "In memoriam",
                "anniversary": "Anniversary", "public domain": "Anniversary"}


def month_pages(site: str, site_url: str, titles: set[str], hist: dict, store: Works) -> list[tuple[str, str]]:
    """The monthly Comeback Report (site/report/<2026-11>.html) and a list of every month: the month's
    biggest comebacks, why things came back, by kind, and the biggest mysteries. Written for readers and
    for journalists, who are free to cite it with a link. Returns (address, last updated) for the sitemap."""
    e = html.escape
    base = site_url.rstrip("/")
    out_dir = os.path.join(site, "report")
    os.makedirs(out_dir, exist_ok=True)
    days, works, names = hist.get("days") or {}, hist.get("works") or {}, hist.get("names") or {}
    runs = sorted(days)
    if not runs:
        return []
    notes = {n.get("id"): n.get("note") or n.get("text") for n in _load(os.path.join(site, "..", "annotations.json"), [])} \
        if os.path.exists(os.path.join(site, "..", "annotations.json")) else {}
    months = sorted({r[:7] for r in runs})
    link = lambda q, text: f'<a href="{e(base)}/w/{e(q)}">{e(text)}</a>' if q in titles else e(text)
    # Groups of titles sharing a person, with the reason found for the group (as the site shows them).
    group_why: dict[tuple[str, str], str] = {}
    for r in runs:
        run = _load(os.path.join(site, "data", "runs", f"{r}.json"), {}) or {}
        for t in run.get("common_threads") or []:
            if t.get("editor_note"):
                why = t["editor_note"]["text"]
            elif t.get("cause"):
                why = f"{t['name']} is in the news ({MONTH_CAUSE.get(t['cause'], t['cause'])})"
            elif t.get("person_jump"):
                why = f"Interest in {t['name']} jumped {t['person_jump']['ratio']}× at the same time"
            else:
                continue
            for w in t.get("works") or []:
                group_why[(r, w.get("qid"))] = why

    def reason_of(q, ep, rows_runs):
        """(category, why) for an episode, counting a group's reason for its titles."""
        if ep["verdict"] == "common thread":
            why = next((group_why[(r, q)] for r in reversed(rows_runs) if (r, q) in group_why), None)
            return ("In the news", why) if why else ("Unexplained", None)
        why = None
        for c in ep.get("causes") or []:
            if c[0] == "coverage" and c[2]:
                why = f"It looks like {MONTH_CAUSE.get(c[2], c[2])}"
            elif c[0] in ("derivative", "same-creator") and names.get(c[1]) == works[q][0]:
                when = f" ({dt.date.fromisoformat(c[3]):%b %-d, %Y})" if c[3] else ""
                why = f"A new version with the same name{when}"      # a remake that reuses the title
            elif c[0] != "common thread":
                why = _cause_text(c, names, notes)
            if why:
                break
        return MONTH_REASON.get(ep["verdict"], "Unexplained"), why

    done = []
    for i, month in enumerate(months):
        mruns = [r for r in runs if r[:7] == month]
        qids = {q for r in mruns for q in days[r]}
        eps = []
        for q in qids:
            for ep in episodes_of(q, days, runs):
                if ep["first_seen"][:7] == month or (ep["last_seen"][:7] == month and ep["first_seen"] < month):
                    eps.append((q, ep))
        eps = [(q, ep) for q, ep in eps if ep["verdict"] not in SET_ASIDE and q in works]
        span_runs = lambda ep: [r for r in runs if ep["first_seen"] <= r <= ep["last_seen"]]
        why_of = {q: reason_of(q, ep, span_runs(ep)) for q, ep in eps}
        if not eps:
            continue
        label = lambda q: works[q][0]
        year = lambda q: works[q][2]
        kind = lambda q: works[q][1]
        # Biggest: one line per reason, so one sequel lifting a whole series counts once ("and 9 more").
        groups: dict[str, list] = {}
        for q, ep in sorted(eps, key=lambda x: (-(x[1].get("score") or 0), -x[1]["peak_lift"])):
            c = (ep.get("causes") or [[None, None]])[0]
            key = f"{c[0]}:{c[1]}" if c[0] in ("derivative", "same-creator", "death", "honor", "common thread") and c[1] else q
            groups.setdefault(key, []).append((q, ep))
        top = sorted(groups.values(), key=lambda g: -(g[0][1].get("score") or 0))[:10]
        items = []
        for g in top:
            q, ep = g[0]
            why = why_of[q][1]
            more = f" and {len(g) - 1} more title{'s' if len(g) > 2 else ''}" if len(g) > 1 else ""
            doc = store.get(q) or {}
            items.append(f'<li><h3>{link(q, f"{label(q)} ({year(q)})")}{e(more)}</h3>'
                         f'<p>The {e(str(year(q)))} {e(NOUN.get(kind(q), kind(q)))} reached {ep["peak_lift"]}× its usual interest'
                         f' from {_day(ep["start"])}. {e("Why: " + _sentence(why)) if why else "Why: we don’t know yet."}</p>'
                         f'{_spark((doc.get("spark") or [])[-45:], doc.get("baseline"))}</li>')
        # Why things came back
        tally: dict[str, int] = {}
        for q, ep in eps:
            tally[why_of[q][0]] = tally.get(why_of[q][0], 0) + 1
        total = sum(tally.values())
        order = ["New release", "In the news", "In memoriam", "Anniversary", "Unexplained"]
        bars = "".join(f'<li><span class="bar-label">{e(k)}</span><span class="bar" style="width:{max(2, round(60 * tally[k] / total))}%"></span>'
                       f' <span class="small">{tally[k]:,} ({round(100 * tally[k] / total)}%)</span></li>'
                       for k in order if tally.get(k))
        by_kind: dict[str, int] = {}
        for q, ep in eps:
            by_kind[kind(q)] = by_kind.get(kind(q), 0) + 1
        plural = lambda w, n: w if n == 1 or w.endswith("series") else w + "s"
        kinds = ", ".join(f"{n:,} {plural(NOUN.get(k, k), n)}" for k, n in sorted(by_kind.items(), key=lambda x: -x[1]))
        myst = sorted([(q, ep) for q, ep in eps if why_of[q][0] == "Unexplained"], key=lambda x: -x[1]["peak_lift"])[:5]
        first, last = dt.date.fromisoformat(month + "-01"), dt.date.fromisoformat(mruns[-1])
        mname = f"{first:%B %Y}"
        open_month = (last + dt.timedelta(days=1)).month == last.month
        canon = f"{base}/report/{month}"
        title = f"{mname} in comebacks: the Comeback Report | The Rallyback"
        lead = ", ".join(label(g[0][0]) for g in top[:3])
        desc = f"The old movies, shows, songs, games and books people went back to in {mname}, and why. Led by {lead}."
        parts = ['<p class="kicker">The Comeback Report</p>', f"<h1>{e(mname)} in comebacks</h1>",
                 f'<p class="dek">{total:,} older titles drew unusual interest {"so far this month" if open_month else "this month"}: '
                 f'{e(kinds)}. Here’s what came back, and why.</p>']
        if open_month:
            parts.append(f'<p class="small">This month isn’t over: updated {_day(mruns[-1])}, every morning until the end of {first:%B}.</p>')
        parts.append("<h2>The 10 biggest comebacks</h2><ol class='ranked'>" + "".join(items) + "</ol>")
        parts.append("<h2>Why things came back</h2><ul class='bars'>" + bars + "</ul>"
                     "<p class='small'>New release: a sequel, remake, adaptation or new work by the same people. In the news: a news story, "
                     "award or event. Unexplained: nothing on record explains it yet.</p>")
        if myst:
            parts.append("<h2>The biggest mysteries</h2><ul>" + "".join(
                f"<li>{link(q, f'{label(q)} ({year(q)})')}: {ep['peak_lift']}× its usual interest from {_day(ep['start'])}</li>" for q, ep in myst)
                + f'</ul><p><a href="{e(base)}/?tab=mysteries">Know why? Tell us</a>.</p>')
        parts.append('<h2>About these numbers</h2><p class="small">Interest is measured from daily Wikipedia page views against each '
                     'title’s usual level; reasons come from Wikidata, Wikipedia, news data and charts (see the sources on each title’s page). '
                     'Journalists and writers are welcome to quote this report with a link to The Rallyback.</p>')
        nav = []
        if i > 0:
            nav.append(f'<a href="{e(base)}/report/{months[i - 1]}">← {dt.date.fromisoformat(months[i - 1] + "-01"):%B %Y}</a>')
        nav.append(f'<a href="{e(base)}/report/">Every month</a>')
        if i < len(months) - 1:
            nav.append(f'<a href="{e(base)}/report/{months[i + 1]}">{dt.date.fromisoformat(months[i + 1] + "-01"):%B %Y} →</a>')
        parts.append(f'<a class="btn" href="{e(base)}/?tab=subscribe">Get the comebacks every Friday, free</a>'
                     f'<p class="small">{" · ".join(nav)}</p>')
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": title.replace(" | The Rallyback", ""),
              "url": canon, "description": desc, "datePublished": month + "-01", "dateModified": mruns[-1], "inLanguage": "en",
              "image": f"{base}/og.png", "author": {"@type": "Organization", "name": "The Rallyback", "url": base + "/"},
              "publisher": {"@type": "Organization", "name": "The Rallyback", "url": base + "/"}}
        _write_if_changed(os.path.join(out_dir, f"{month}.html"), _shell(base, title, desc, canon, f"{base}/og.png", ld, parts))
        done.append((canon, mruns[-1], mname, total, lead))
    rows = "".join(f'<li><a href="{e(c)}">{e(n)}</a> <span class="small">· {t:,} titles: {e(l)}</span></li>' for c, _, n, t, l in reversed(done))
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "The Comeback Report, every month", "url": f"{base}/report/"}
    _write_if_changed(os.path.join(out_dir, "index.html"), _shell(
        base, "The Comeback Report, every month | The Rallyback",
        "Each month's biggest comebacks of older movies, shows, songs, games and books, and why they came back.",
        f"{base}/report/", f"{base}/og.png", ld,
        ['<p class="kicker">The Comeback Report</p>', "<h1>Every month in comebacks</h1>",
         '<p class="dek">The biggest comebacks each month, and why, newest first.</p>', f"<ul>{rows}</ul>"], og_type="website"))
    return [(f"{base}/report/", done[-1][1] if done else "")] + [(c, d) for c, d, *_ in reversed(done)]


def week_pages(site: str, site_url: str, titles: set[str]) -> list[tuple[str, str]]:
    """A permanent, readable page per week (site/week/<2026-W47>.html) and a list of every week.
    Returns (address, last updated) pairs for the sitemap."""
    e = html.escape
    base = site_url.rstrip("/")
    wdir, out_dir = os.path.join(site, "data", "weekly"), os.path.join(site, "week")
    os.makedirs(out_dir, exist_ok=True)
    keys = sorted(_load(os.path.join(wdir, "index.json"), []))
    link = lambda q, text: f'<a href="{e(base)}/w/{e(q)}">{e(text)}</a>' if q in titles else e(text)
    done = []
    for i, key in enumerate(keys):
        W = _load(os.path.join(wdir, f"{key}.json"), None)
        if not W:
            continue
        span = _span(W["from"], W["to"])
        open_week = W["updated"] < W["to"]
        canon = f"{base}/week/{key}"
        title = f"The week’s biggest comebacks, {span} | The Rallyback"
        top = W.get("top") or []
        names = ", ".join(t["label"] for t in top[:3])
        desc = (f"The biggest comebacks of older movies, shows, songs, games and books, the week of {span}."
                + (f" Led by {names}." if names else ""))
        parts = [f'<p class="kicker">This week in comebacks</p>', f"<h1>{e(span)}</h1>",
                 f'<p class="dek">{W["comebacks"]:,} older titles drew unusual interest {"so far this week" if open_week else "this week"}. '
                 f'Here are the biggest stories, the best mystery and what’s coming next.</p>']
        if open_week:
            parts.append(f'<p class="small">This week isn’t over: updated {_day(W["updated"])}, every morning until {_day(W["to"])}.</p>')
        if top:
            items = []
            for t in top:
                more = f" and {t['more']} more title{'s' if t['more'] > 1 else ''}" if t.get("more") else ""
                kind = NOUN.get(t["kind"], t["kind"])
                items.append(f'<li><h3>{link(t["qid"], t["label"] + " (" + str(t["year"]) + ")")}{e(more)}</h3>'
                             f'<p>The {e(str(t["year"]))} {e(kind)} reached {t["lift"]}× its usual interest. '
                             f'{e("Why: " + _sentence(t["why"]) if t.get("why") else "")}</p>'
                             f'{_spark(t.get("trend"), t.get("baseline"))}</li>')
            parts.append("<h2>The 5 biggest</h2><ol class='ranked'>" + "".join(items) + "</ol>")
        m = W.get("mystery")
        if m:
            parts.append(f"<h2>Best mystery</h2><p>{link(m['qid'], m['label'] + ' (' + str(m['year']) + ')')}: "
                         f"{m['lift']}× its usual interest since {_day(m['start'])}, and we can’t find out why. "
                         f'<a href="{e(base)}/?tab=mysteries">Know why? Tell us</a>.</p>')
        if W.get("coming"):
            parts.append("<h2>Coming up next week</h2><ul>" + "".join(
                f"<li>{_day(c['date'])}: {link(c['qid'], re.sub(r' [(][^)]*[)]$', '', c['label']))}, {e(c['what'])}"
                + (f" <span class='small'>(expect about {c['prediction']['expected']}× its usual interest)</span>"
                   if (c.get('prediction') or {}).get('expected') else "") + "</li>" for c in sorted(W["coming"], key=lambda c: c["date"])) + "</ul>")
        if W.get("results"):
            parts.append("<h2>How our predictions did</h2><ul>" + "".join(
                f"<li>{e(x['label'])}: {'came true' if x.get('hit') else 'no bump'}"
                f" ({x['ratio']}× its usual interest)</li>" for x in W["results"] if x.get("ratio") is not None) + "</ul>")
        nav = []
        if i > 0:
            nav.append(f'<a href="{e(base)}/week/{keys[i - 1]}">← Week of {_span(*_week_dates(keys[i - 1]))}</a>')
        nav.append(f'<a href="{e(base)}/week/">Every week</a>')
        nav.append(f'<a href="{e(base)}/report/{W["to"][:7]}">The month’s Comeback Report</a>')
        if i < len(keys) - 1:
            nav.append(f'<a href="{e(base)}/week/{keys[i + 1]}">Week of {_span(*_week_dates(keys[i + 1]))} →</a>')
        parts.append(f'<a class="btn" href="{e(base)}/?tab=subscribe">Get this every Friday, free</a>'
                     f'<p class="small">{" · ".join(nav)}</p>')
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": title.replace(" | The Rallyback", ""),
              "url": canon, "description": desc, "datePublished": W["from"], "dateModified": W["updated"], "inLanguage": "en",
              "image": f"{base}/og.png", "author": {"@type": "Organization", "name": "The Rallyback", "url": base + "/"},
              "publisher": {"@type": "Organization", "name": "The Rallyback", "url": base + "/"}}
        page = _shell(base, title, desc, canon, f"{base}/og.png", ld, parts)
        _write_if_changed(os.path.join(out_dir, f"{key}.html"), page)
        done.append((canon, W["updated"]))
    # The list of every week.
    rows = []
    for key in reversed(keys):
        W = _load(os.path.join(wdir, f"{key}.json"), None)
        if W:
            top = W.get("top") or []
            rows.append(f'<li><a href="{e(base)}/week/{key}">{_span(W["from"], W["to"])}</a> '
                        f'<span class="small">· {W["comebacks"]:,} titles{": " + e(", ".join(t["label"] for t in top[:3])) if top else ""}</span></li>')
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Every week in comebacks", "url": f"{base}/week/"}
    page = _shell(base, "Every week in comebacks | The Rallyback", "The biggest comebacks of older movies, shows, songs, games and books, week by week.",
                  f"{base}/week/", f"{base}/og.png", ld,
                  ['<p class="kicker">The archive</p>', "<h1>Every week in comebacks</h1>",
                   '<p class="dek">The biggest stories each week, newest first.</p>', "<ul>" + "".join(rows) + "</ul>"], og_type="website")
    _write_if_changed(os.path.join(out_dir, "index.html"), page)
    return [(f"{base}/week/", keys and _load(os.path.join(wdir, f"{keys[-1]}.json"), {}).get("updated", ""))] + list(reversed(done))


def _week_dates(key: str) -> tuple[str, str]:
    y, w = key.split("-W")
    mon = dt.date.fromisocalendar(int(y), int(w), 1)
    return mon.isoformat(), (mon + dt.timedelta(days=6)).isoformat()


def _write_if_changed(path: str, text: str) -> None:
    try:
        with open(path) as f:
            if f.read() == text:
                return
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(text)


def pages(site: str, site_url: str, qids: list[str], hist: dict, store: Works) -> None:
    """Write every title's page (cheap: plain text from files already on disk), the sitemap and robots.txt."""
    pdir = os.path.join(site, "w")
    os.makedirs(pdir, exist_ok=True)
    docs = {}
    for q in qids:
        d = store.get(q)
        if d and d.get("episodes"):
            docs[q] = d
    books = [q for q, d in docs.items() if d.get("kind") in reading.BOOK_KINDS]
    free = reading.lookup(site, books, max(hist["days"]) if hist.get("days") else None)
    for q, d in docs.items():
        if d.get("kind") in reading.BOOK_KINDS and d.get("read", []) != free.get(q, []):
            d["read"] = free.get(q, [])
            store.put(q, d)
        page = _page(site_url, d)
        path = os.path.join(pdir, f"{q}.html")
        try:
            with open(path) as f:
                if f.read() == page:
                    continue
        except OSError:
            pass
        with open(path, "w") as f:
            f.write(page)
    base = site_url.rstrip("/")
    if base:
        weeks = week_pages(site, site_url, set(docs)) + month_pages(site, site_url, set(docs), hist, store)
        urls = [f"  <url><loc>{base}/</loc></url>"] + [
            f"  <url><loc>{u}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>" for u, d in weeks] + [
            f"  <url><loc>{base}/w/{q}</loc><lastmod>{d.get('updated') or d['episodes'][-1]['last_seen']}</lastmod></url>"
            for q, d in sorted(docs.items(), key=lambda kv: kv[1].get("updated") or "", reverse=True) if not thin(d)]
        with open(os.path.join(site, "sitemap.xml"), "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                    + "\n".join(urls) + "\n</urlset>\n")
        with open(os.path.join(site, "robots.txt"), "w") as f:
            f.write(f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")
    log(f"      title pages: {len(docs)} ({sum(1 for d in docs.values() if thin(d))} kept out of search for now; "
        f"{len(free)} books with a free copy)")


HOME_START, HOME_END = "<!-- today:start -->", "<!-- today:end -->"


def homepage(site: str, latest: dict, hist: dict) -> None:
    """Today's top 10 written straight into index.html, so the homepage has real text before the
    app loads (search engines, link previews, slow connections). The app replaces it on load."""
    path = os.path.join(site, "index.html")
    try:
        with open(path) as f:
            page = f.read()
    except OSError:
        return
    if HOME_START not in page or HOME_END not in page:
        return
    run = (latest.get("meta") or {}).get("window_end")
    rows = hist["days"].get(run, {}) if run else {}
    notes = {n["id"]: n.get("note") for n in _load("annotations.json", []) if isinstance(n, dict) and n.get("id")}
    live = sorted((r for r in latest.get("results", []) if r.get("verdict") not in SET_ASIDE),
                  key=lambda r: -(r.get("score") or 0))[:60]
    e = html.escape
    # One line per story: seven Grand Theft Auto games back for one new release is one story.
    stories: dict[str, list] = {}
    for r in live:
        why = _causes((rows.get(r["qid"]) or {}).get("causes") or [], hist["names"], notes)
        stories.setdefault(why[0] if why else r["qid"], []).append((r, why))
    items = []
    for group in list(stories.values())[:10]:
        r, why = group[0]
        more = f" and {len(group) - 1} more title{'s' if len(group) > 2 else ''}" if len(group) > 1 else ""
        items.append(f'<li><a href="w/{e(r["qid"])}">{e(r["label"])} ({e(str(r.get("release_year", "")))})</a>{more}: '
                     f'{r["lift"]}× its usual interest. {e("Why: " + _sentence(why[0]) if why else "Reason unknown yet.")}</li>')
    block = (f'{HOME_START}\n    <section class="static-today"><h2>Today’s top comebacks{f", {_day(run)}" if run else ""}</h2>\n'
             f'    <ol>{"".join(items)}</ol>\n    <p><a href="week/">The biggest comebacks, week by week</a></p></section>\n    {HOME_END}')
    new = page[:page.index(HOME_START)] + block + page[page.index(HOME_END) + len(HOME_END):]
    if new != page:
        with open(path, "w") as f:
            f.write(new)


def _cause_key(causes: list) -> str | None:
    """The person or release behind a comeback, so one story isn't listed once per title."""
    for c in causes or []:                      # an editor's note groups a story first (e.g. all the Bond titles)
        if c[0] == "note":
            return f"note:{c[2]}"
    for c in causes or []:
        if c[1] and c[0] not in ("anniversary",):
            return c[1]
    return None


def _one_per_story(items: list[dict], n: int) -> list[dict]:
    """Keep the best title per cause; the rest are counted on it ('and 11 more')."""
    out, by_key = [], {}
    for it in items:
        k = it.pop("_key", None)
        if k and k in by_key:
            by_key[k]["more"] = by_key[k].get("more", 0) + 1
            continue
        if k:
            by_key[k] = it
        if len(out) < n:
            out.append(it)
    return out


def leaders(site: str, hist: dict, runs: list[str]) -> None:
    """Biggest comebacks this month and this year; decades and franchises hot this week."""
    works, names, days = hist["works"], hist["names"], hist["days"]
    end = _d(runs[-1])
    eps_all = []
    for q in works:
        for e in episodes_of(q, days, runs):
            eps_all.append((q, e))

    def top(since: dt.date, n=20):
        xs = [(q, e) for q, e in eps_all if _d(e["first_seen"]) >= since]
        xs.sort(key=lambda qe: (-(qe[1]["score"] or 0), -qe[1]["peak_lift"]))
        return _one_per_story([{"qid": q, "label": works[q][0], "year": str(works[q][2]), "kind": works[q][1], "score": e["score"],
                                "peak_lift": e["peak_lift"], "start": e["start"], "verdict": e["verdict"],
                                "_key": _cause_key(e["causes"])} for q, e in xs], n)

    week = [r for r in runs if (end - _d(r)).days < 7]
    before = [r for r in runs if 7 <= (end - _d(r)).days < 35]

    def decade_counts(rs):
        seen, c = set(), {}
        for r in rs:
            for q in days[r]:
                if q in works and q not in seen and str(works[q][2])[:3].isdigit():
                    seen.add(q)
                    d = f"{str(works[q][2])[:3]}0s"
                    c[d] = c.get(d, 0) + 1
        return c

    cw, cb = decade_counts(week), decade_counts(before)
    tw, tb = sum(cw.values()) or 1, sum(cb.values()) or 1
    decades = sorted([{"decade": d, "this_week": n, "share": round(n / tw, 3),
                       "usual_share": round(cb.get(d, 0) / tb, 3) if before else None} for d, n in cw.items()],
                     key=lambda x: (-x["this_week"], x["decade"]))
    fr: dict[str, set] = {}
    for r in week:
        for q in days[r]:
            for f in ((works.get(q) or [None] * 4)[3] if len(works.get(q) or []) > 3 else []) or []:
                fr.setdefault(f, set()).add(q)
    by_name: dict[str, set] = {}        # Wikidata sometimes has two items for one franchise: merge by name
    for f, qs in fr.items():
        if names.get(f):
            by_name.setdefault(names[f], set()).update(qs)
    franchises = sorted([{"name": n, "titles": len(qs),
                          "top": sorted(({"qid": q, "label": works[q][0]} for q in qs), key=lambda x: (x["label"], x["qid"]))[:5]}
                         for n, qs in by_name.items() if len(qs) >= 2], key=lambda x: (-x["titles"], x["name"]))[:12]
    _save(os.path.join(site, "data", "leaders.json"), {
        "month": top(end.replace(day=1)), "year": top(end.replace(month=1, day=1)),
        "decades": decades, "franchises": franchises, "updated": runs[-1],
        "covers_from": runs[0]})


def weekly(site: str, hist: dict, runs: list[str], latest: dict) -> None:
    """'This week in comebacks' for the ISO week of the latest edition."""
    works, days = hist["works"], hist["days"]
    end = _d(runs[-1])
    y, w, _ = end.isocalendar()
    monday = end - dt.timedelta(days=end.weekday())
    wk_runs = [r for r in runs if monday <= _d(r) <= end]
    best: dict[str, dict] = {}
    for r in wk_runs:
        for q, row in days[r].items():
            if q in works and row.get("verdict") not in SET_ASIDE:
                if (row.get("rally_score") or 0) > (best.get(q, {}).get("rally_score") or -1):
                    best[q] = {**row, "run": r}
    ranked = sorted(best.items(), key=lambda kv: -(kv[1].get("rally_score") or 0))
    pick = lambda q, row: {"qid": q, "label": works[q][0], "year": str(works[q][2]), "kind": works[q][1],
                           "score": row.get("rally_score"), "lift": row.get("lift"), "verdict": row.get("verdict"),
                           "start": str(row.get("spike_start"))[:10], "_key": _cause_key(row.get("causes")),
                           "why": (_causes(row.get("causes") or [], hist["names"], notes) or [None])[0]}
    notes = {n["id"]: n.get("note") for n in _load("annotations.json", []) if isinstance(n, dict) and n.get("id")}
    top5 = _one_per_story([pick(q, row) for q, row in ranked if row.get("verdict") not in UNEXPLAINED], 5)
    # The last three weeks of each one's daily interest, for the small charts on This week.
    R = {r["qid"]: r for r in latest.get("results", [])}
    for t in top5:
        r = R.get(t["qid"])
        if r and r.get("spark"):
            t["trend"] = r["spark"][-21:]
            t["trend_end"] = (dt.date.fromisoformat(r["spark_start"]) + dt.timedelta(days=len(r["spark"]) - 1)).isoformat()
            t["baseline"] = r.get("baseline")
    mystery = next((pick(q, row) for q, row in ranked if row.get("verdict") in UNEXPLAINED), None)
    if mystery:
        mystery.pop("_key", None)
    cu = latest.get("coming_up", {})
    nxt = (end + dt.timedelta(days=8)).isoformat()
    soon = []
    for c in cu.get("derivatives", []):
        if end.isoformat() < c["date"] <= nxt:
            soon.append({"qid": c["old"], "label": c["old_label"], "date": c["date"], "what": f"{c['rel']} {c['new_label']}",
                         "prediction": c.get("prediction")})
    for a in cu.get("anniversaries", []) + cu.get("seasonal", []):
        if end.isoformat() < a["date"] <= nxt:
            soon.append({"qid": a["qid"], "label": a["label"], "date": a["date"],
                         "what": f"{a['years']}th anniversary" if a.get("years") else "back every year",
                         "prediction": a.get("prediction")})
    soon.sort(key=lambda x: -((x.get("prediction") or {}).get("expected") or 0))
    checks = _load(os.path.join(site, "data", "forecast_checks.json"), {})
    results = sorted([x for x in checks.values() if (end - dt.timedelta(days=14)).isoformat() <= x["date"] <= end.isoformat()],
                     key=lambda x: x["date"], reverse=True)[:8]
    # New comebacks each day of the week, by reason (for the week chart). The record's first
    # day has nothing to compare with, so it isn't counted as "new".
    reason = {"ripple": "news", "editor": "news", "coverage": "news", "derivative": "release", "same-creator": "release",
              "editor-release": "release", "editor-death": "memoriam",
              "unexplained": "unexplained", "weak link": "unexplained", "lookup failed": "unexplained",
              "common thread": "unexplained", "death": "memoriam", "anniversary": "anniversary",
              "public domain": "anniversary", "honor": "news"}
    per_day = []
    for i in range(7):
        day = (monday + dt.timedelta(days=i)).isoformat()
        prev = [r for r in runs if r < day]
        if day not in days:
            per_day.append({"date": day, "edition": False})
            continue
        if not prev:
            per_day.append({"date": day, "edition": True, "first": True})
            continue
        before = set(days[prev[-1]])
        groups: dict[str, list] = {}
        for q, row in days[day].items():
            k = reason.get(row.get("verdict"))
            if k and q not in before and q in works:
                groups.setdefault(k, []).append((row.get("rally_score") or 0, works[q][0]))
        per_day.append({"date": day, "edition": True,
                        "counts": {k: len(v) for k, v in groups.items()},
                        "titles": {k: [t for _, t in sorted(v, reverse=True)[:5]] for k, v in groups.items()}})
    key = f"{y}-W{w:02d}"
    doc = {"week": key, "from": monday.isoformat(), "to": (monday + dt.timedelta(days=6)).isoformat(), "updated": runs[-1],
           "editions": len(wk_runs), "comebacks": len(best), "top": top5, "mystery": mystery,
           "coming": soon[:6], "results": results, "days": per_day}
    wdir = os.path.join(site, "data", "weekly")
    _save(os.path.join(wdir, f"{key}.json"), doc)
    idx = sorted({f[:-5] for f in os.listdir(wdir) if f.endswith(".json") and f != "index.json"}, reverse=True)
    _save(os.path.join(wdir, "index.json"), idx)
