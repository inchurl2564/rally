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
    each with the first reference URL cited alongside it."""
    a, b = _rev_at(title, around - dt.timedelta(days=2)), _rev_at(title, around + dt.timedelta(days=5))
    if not a or not b or a == b:
        return []
    d = _mw({"action": "compare", "fromrev": a, "torev": b, "prop": "diff", "difftype": "table"})
    diff = (d or {}).get("compare", {}).get("body", "")
    added = []
    for cell in re.findall(r'<td class="diff-addedline[^"]*"[^>]*>(.*?)</td>', diff, flags=re.S):
        raw = html.unescape(re.sub(r"<[^>]+>", "", cell))
        text = _clean(raw)
        if len(text) < 40:
            continue
        url = (_REF_URL.search(raw) or _BARE_URL.search(raw))
        added.append({"source": "Wikipedia (cited)" if url else "Wikipedia edit", "date": around.isoformat(),
                      "text": text[:300], "url": url.group(1) if url else
                      f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&diff={b}&oldid={a}"})
    return added


def current_events(name: str, around: dt.date, days: int = 4) -> list[dict]:
    """Lines mentioning `name` on Wikipedia's Portal:Current_events daily pages."""
    out = []
    for i in range(-1, days):
        d = around + dt.timedelta(days=i)
        page = f"Portal:Current events/{d.year} {d.strftime('%B')} {d.day}"
        r = _mw({"action": "parse", "page": page, "prop": "wikitext"})
        text = (r or {}).get("parse", {}).get("wikitext", "")
        for line in text.splitlines():
            if name.lower() in line.lower():
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
                if r["verdict"] not in ("death", "derivative", "same-creator", "anniversary"):
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
