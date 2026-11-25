"""
Editor's notes, and automatic corroboration from open sources.

annotations.json (repo root) holds notes like "Robert Pattinson was announced as the
next James Bond". Each note says which works or person it explains, roughly when, and
— before it's published — a source link.

  status "draft"      not shown on the site
  status "published"  shown as an Editor's note on matching spikes; needs `source`

`python annotations.py --check` (also run daily) tries to corroborate drafts from open
sources and fills in `source` when it finds one:

  1. Wikipedia: sentences added to the entity's article around the date, with the
     news reference editors cited (MediaWiki API: revisions + compare)
  2. Wikipedia's Portal:Current_events daily pages (cited news summaries)
  3. GDELT news headlines

A draft is promoted only when the found text contains one of the note's `keywords`
and comes with a source URL.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.parse

import explain
import radar

PATH = os.path.join(radar.HERE, "annotations.json")


def load() -> list[dict]:
    try:
        with open(PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def save(notes: list[dict]) -> None:
    with open(PATH, "w") as f:
        json.dump(notes, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---------- open-source lookups (MediaWiki API; best-effort, rate-limited) ----------

def _mw(params: dict) -> dict | None:
    q = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2, "maxlag": 5})
    return explain.MW.get(f"{explain.MW_API}?{q}", {"Api-User-Agent": radar.UA})


def _rev_at(title: str, when: dt.date) -> int | None:
    d = _mw({"action": "query", "prop": "revisions", "titles": title.replace("_", " "), "rvlimit": 1,
             "rvprop": "ids", "rvstart": f"{when.isoformat()}T00:00:00Z", "rvdir": "older"})
    pages = (d or {}).get("query", {}).get("pages", [])
    revs = pages[0].get("revisions", []) if pages else []
    return revs[0]["revid"] if revs else None


_REF_URL = re.compile(r"\|\s*(?:url|archive-url)\s*=\s*(https?://[^\s|}]+)", re.I)
_BARE_URL = re.compile(r"\[(https?://[^\s\]]+)")


def _clean(wikitext: str) -> str:
    t = re.sub(r"<ref[^>]*/>", "", wikitext)
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"\[https?://\S+ ([^\]]+)\]", r"\1", t)
    t = re.sub(r"'{2,}", "", t)
    return re.sub(r"\s+", " ", t).strip()


def added_text(title: str, around: dt.date) -> list[dict]:
    """Sentences added to an article between 2 days before and 5 days after `around`,
    each with the first reference URL cited alongside it. Infobox and template lines are skipped,
    and when an edit added more than three sentences (a rewrite, a page move, a restored section) only sentences that
    give a date near `around` count: rewrites are full of old facts (reviews, box office)."""
    a, b = _rev_at(title, around - dt.timedelta(days=2)), _rev_at(title, around + dt.timedelta(days=5))
    if not a or not b or a == b:
        return []
    d = _mw({"action": "compare", "fromrev": a, "torev": b, "prop": "diff", "difftype": "table"})
    diff = (d or {}).get("compare", {}).get("body", "")
    added = []
    for cell in re.findall(r'<td class="diff-addedline[^"]*"[^>]*>(.*?)</td>', diff, flags=re.S):
        raw = html.unescape(re.sub(r"<[^>]+>", "", cell))
        if raw.lstrip().startswith(("|", "{{", "!", "[[Category", "[[File", "<!--")):
            continue
        text = _clean(raw)
        if len(text) < 40:
            continue
        url = (_REF_URL.search(raw) or _BARE_URL.search(raw))
        added.append({"source": "Wikipedia (cited)" if url else "Wikipedia edit", "date": around.isoformat(),
                      "text": text[:300], "url": url.group(1) if url else
                      f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&diff={b}&oldid={a}"})
    lo, hi = around - dt.timedelta(days=30), around + dt.timedelta(days=5)

    def recent(e):
        return any(x <= hi and y >= lo for x, y in _dates_in(e["text"]))

    # A sentence that only gives old dates ("released on August 5, 1994", "In 1960 he...") is old news re-added.
    added = [e for e in added if not _old_news(e["text"], around)]
    # Without a reference, a sentence counts only if it dates itself near the comeback: plot
    # summaries and themes ("since Abel died") are rewritten all the time and say nothing about now.
    added = [e for e in added if e["source"] == "Wikipedia (cited)" or recent(e)]
    if len(added) > 3:
        added = [e for e in added if recent(e)]
    # A cited sentence with no date at all is usually background ("After graduation, she held several
    # jobs"): it stays as a source, but isn't read for a reason.
    for e in added:
        if not recent(e) and not _YEAR.search(e["text"]):
            e["background"] = True
    return added


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]
_M = "(" + "|".join(_MONTHS) + ")"
_DMY = re.compile(r"\b(\d{1,2}) " + _M + r",? (\d{4})\b")
_MDY = re.compile(r"\b" + _M + r" (\d{1,2}),? (\d{4})\b")
_MY = re.compile(r"\b(?:early |mid-|late )?" + _M + r" (\d{4})\b")
_DATE_TPL = re.compile(r"\{\{\s*(?:start date|end date|film date|release date|dts|date)[^|}]*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})[^}]*\}\}", re.I)
_SENT_END = re.compile(r"(?<=[.!?])((?:\s*<ref[^>]*/>|\s*<ref[^>]*>.*?</ref>)*)\s+(?=[A-Z\[\'\"])", re.S)
_PAGE_TEXT: dict[str, str] = {}


def _dates_in(text: str) -> list[tuple[dt.date, dt.date]]:
    """Each date in the text as a (first day, last day) range; a bare month covers the month."""
    out = []
    for d, m, y in _DMY.findall(text):
        try:
            x = dt.date(int(y), _MONTHS.index(m) + 1, int(d)); out.append((x, x))
        except ValueError:
            pass
    for m, d, y in _MDY.findall(text):
        try:
            x = dt.date(int(y), _MONTHS.index(m) + 1, int(d)); out.append((x, x))
        except ValueError:
            pass
    if not out:
        for m, y in _MY.findall(text):
            first = dt.date(int(y), _MONTHS.index(m) + 1, 1)
            last = (first + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
            out.append((first, last))
    return out


_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def _old_news(text: str, around: dt.date) -> bool:
    """True when a sentence dates itself, and every date in it is old: full dates all before 30 days
    ahead of the comeback, or (with no full dates) every year before the comeback's year."""
    lo, hi = around - dt.timedelta(days=30), around + dt.timedelta(days=5)
    full = _dates_in(text)
    if full:
        return not any(a <= hi and b >= lo for a, b in full)
    years = {int(y) for y in _YEAR.findall(text)}
    return bool(years) and max(years) < around.year


def dated_sentences(title: str, around: dt.date, before: int = 21, after: int = 5) -> list[dict]:
    """Sentences anywhere in the article that give a date from `before` days before `around` to
    `after` days after ("The series premiered on Netflix on 14 November 2026"), whenever editors
    added them, each with the reference cited for it. Catches news added before the comeback
    began (an announcement, a release date), which added_text's diff window misses."""
    if title not in _PAGE_TEXT:
        r = _mw({"action": "parse", "page": title.replace("_", " "), "prop": "wikitext", "redirects": 1})
        _PAGE_TEXT[title] = (r or {}).get("parse", {}).get("wikitext", "")
    text = _DATE_TPL.sub(lambda m: f"{int(m.group(3))} {_MONTHS[int(m.group(2)) - 1]} {m.group(1)}"
                         if 1 <= int(m.group(2)) <= 12 else "", _PAGE_TEXT[title])
    lo, hi = around - dt.timedelta(days=before), around + dt.timedelta(days=after)
    page_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "{|!=" or line.startswith(("[[Category", "[[File", "[[Image")):
            continue
        parts = _SENT_END.split(line.lstrip("*#:; "))
        # split() alternates sentence, refs-after-it, sentence, ...; put each sentence's refs back on it
        for i in range(0, len(parts), 2):
            raw = parts[i] + (parts[i + 1] or "" if i + 1 < len(parts) else "")
            sent = _clean(raw)
            if len(sent) < 30 or sent in seen:
                continue
            hits = [(a, b) for a, b in _dates_in(sent) if a <= hi and b >= lo]
            if not hits:
                continue
            seen.add(sent)
            url = _REF_URL.search(raw) or _BARE_URL.search(raw)
            day = max(a for a, _ in hits)
            out.append({"source": "Wikipedia (cited)" if url else "Wikipedia article", "date": day.isoformat(),
                        "text": sent[:300], "url": url.group(1) if url else page_url})
    out.sort(key=lambda e: (e["source"] != "Wikipedia (cited)", abs((dt.date.fromisoformat(e["date"]) - around).days)))
    return out[:5]


# ---------- Wikipedia's Top 25 Report ----------
# Each week, editors list the 25 most-read articles with a note on why each was popular
# (CC BY-SA, like the rest of Wikipedia). Published about a week after the week ends.

_TOP25: dict[str, str] = {}


def _week_name(start: dt.date) -> str:
    end = start + dt.timedelta(days=6)
    if start.year != end.year:
        return f"{start:%B} {start.day}, {start.year} to {end:%B} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start:%B} {start.day} to {end:%B} {end.day}, {end.year}"
    return f"{start:%B} {start.day} to {end.day}, {end.year}"


def top25(title: str, around: dt.date) -> list[dict]:
    """The Top 25 Report's note on this article, for weeks (Sunday to Saturday) from the one
    holding `around` up to the latest published."""
    want = title.replace("_", " ").strip().lower()
    start = around - dt.timedelta(days=(around.weekday() + 1) % 7)       # back to Sunday
    out = []
    while start + dt.timedelta(days=6) < dt.date.today() and start <= around + dt.timedelta(days=14):
        page = f"Wikipedia:Top 25 Report/{_week_name(start)}"
        if page not in _TOP25:
            r = _mw({"action": "parse", "page": page, "prop": "wikitext"})
            _TOP25[page] = (r or {}).get("parse", {}).get("wikitext", "")
        for row in _TOP25[page].split("\n|-"):
            lines = [l for l in row.strip().splitlines() if l.strip()]
            if not lines or not re.match(r"\|\s*\d+\s*\|\|", lines[0]):
                continue
            m = re.search(r"\[\[([^\]|#]+)", lines[0])
            if not m or m.group(1).strip().lower() != want:
                continue
            notes = [l for l in lines[1:] if l.startswith("|") and not l.startswith(("|[[File", "| [[File"))]
            text = _clean(notes[-1].lstrip("| ")) if notes else ""
            if len(text) > 30:
                out.append({"source": "Wikipedia Top 25 Report", "date": start.isoformat(), "text": text[:300],
                            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page.replace(' ', '_'))}"})
        start += dt.timedelta(days=7)
    return out


_CE_PAGES: dict[str, str] = {}      # one fetch per day's page per run, however many names are looked up


def current_events(name: str, around: dt.date, days: int = 4, link: str | None = None) -> list[dict]:
    """Lines mentioning `name` on Wikipedia's Portal:Current_events daily pages. With `link` (an
    article title, for works), only lines that link to that article count: a film's name alone
    is too often an everyday phrase."""
    out = []
    for i in range(-1, days):
        d = around + dt.timedelta(days=i)
        if d > dt.date.today():
            continue
        page = f"Portal:Current events/{d.year} {d.strftime('%B')} {d.day}"
        if page not in _CE_PAGES:
            r = _mw({"action": "parse", "page": page, "prop": "wikitext"})
            _CE_PAGES[page] = (r or {}).get("parse", {}).get("wikitext", "")
        text = _CE_PAGES[page]
        target = "[[" + link.replace("_", " ").lower() if link else None
        for line in text.splitlines():
            low = line.lower().replace("_", " ")
            if (target in low and (target + "]]" in low or target + "|" in low)) if target else name.lower() in low:
                url = _BARE_URL.search(line)
                out.append({"source": "Wikipedia Current events", "date": d.isoformat(), "text": _clean(line.lstrip("*# "))[:300],
                            "url": url.group(1) if url else f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page.replace(' ', '_'))}"})
    return out


def corroborate(note: dict) -> dict | None:
    """Look for open evidence of a note. Returns the best evidence item, or None."""
    around = dt.date.fromisoformat(note["from"])
    kws = [k.lower() for k in note.get("keywords", [])]
    found = []
    if note.get("entity_title"):
        found += added_text(note["entity_title"], around)
    if note.get("entity_name"):
        found += current_events(note["entity_name"], around)
        found += explain.news(note["entity_name"], around)
    # Wikipedia diffs can include older facts that were merely re-edited, so cited sentences
    # must also mention the note's month or year (Current events pages are dated already).
    when = {str(around.year), around.strftime("%B").lower()}
    hits = [e for e in found if e.get("url") and any(k in e["text"].lower() for k in kws)
            and (e["source"] == "Wikipedia Current events" or any(t in e["text"].lower() for t in when))]
    hits.sort(key=lambda e: (e["source"] != "Wikipedia (cited)", e["source"] != "Wikipedia Current events"))
    return hits[0] if hits else None


def check_drafts(notes: list[dict]) -> int:
    promoted = 0
    for n in notes:
        if n.get("status") != "draft" or n.get("source"):
            continue
        ev = corroborate(n)
        n["last_checked"] = dt.date.today().isoformat()
        if ev:
            n.update(source=ev["url"], source_text=ev["text"], source_kind=ev["source"], status="published",
                     corroborated=dt.date.today().isoformat())
            promoted += 1
            print(f"  ✓ {n['id']}: {ev['source']}: {ev['text'][:120]}  <{ev['url']}>")
        else:
            print(f"  … {n['id']}: no open evidence found yet")
    return promoted


# ---------- applying notes to a run ----------

EDITOR_VERDICT = {"release": "editor-release", "death": "editor-death", "news": "editor"}


def apply(results: list[dict], threads: list[dict]) -> None:
    """Attach published notes to matching spikes and threads."""
    notes = [n for n in load() if n.get("status") == "published" and n.get("source")]
    for n in notes:
        lo = dt.date.fromisoformat(n["from"]) - dt.timedelta(days=10)
        hi = dt.date.fromisoformat(n.get("to") or n["from"]) + dt.timedelta(days=21)
        works = {w.lower() for w in n.get("works", [])}
        names = {x.lower() for x in (n.get("entity_name"), n.get("entity_title", "").replace("_", " "),
                                      *n.get("related", [])) if x}
        # "cause": release (a new film, show, game or book), death, or news; decides the section.
        # "new_work": the Wikidata ID of that new release, so its titles join the same story.
        note = {"text": n["note"], "source": n["source"], "id": n["id"], "cause": n.get("cause", "news")}
        if n.get("new_work"):
            note["new_work"] = n["new_work"]
        if n.get("headline"):           # for the story grouping its titles; {n} = how many
            note["headline"] = n["headline"]
        if n.get("via"):            # e.g. "reader tip": credited when the mystery is marked solved
            note["via"] = n["via"]
        for r in results:
            if not lo <= r["spike_start"] <= hi:
                continue
            rip = (r.get("ripple") or {}).get("name", "").lower()
            if r.get("label", "").lower() in works or r["qid"] in n.get("qids", []) or (rip and rip in names):
                r["editor_note"] = note
                if r["verdict"] not in ("death", "derivative", "same-creator", "anniversary", "public domain", "honor"):
                    r["verdict"] = EDITOR_VERDICT.get(note["cause"], "editor")
        for t in threads:
            if t["name"].lower() in names and lo <= t["around"] <= hi:
                t["editor_note"] = note


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Corroborate draft editor's notes from open sources")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    notes = load()
    if args.check:
        n = check_drafts(notes)
        save(notes)
        print(f"{n} draft(s) corroborated and published; sources off: {radar.HEALTH.get('sources_off', [])}")
