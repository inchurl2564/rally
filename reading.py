"""
Free ways to read a book that's back: Project Gutenberg (free ebooks, public domain) and
Open Library (borrow a copy, where one is available). From Wikidata's Project Gutenberg ID
(P2034) and Open Library ID (P648). Looked up once per book and rechecked every 30 days;
kept in site/data/reading.json so a quiet night costs no requests.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

BOOK_KINDS = {"book", "manga/comic"}
RECHECK_DAYS = 30


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def lookup(site: str, qids: list[str], today: str | None = None) -> dict[str, list[dict]]:
    """{qid: [{"source", "label", "url"}]} for the books in qids that can be read or borrowed free."""
    path = os.path.join(site, "data", "reading.json")
    cache = _load(path)
    today = today or dt.date.today().isoformat()
    stale = [q for q in qids if q not in cache or
             (dt.date.fromisoformat(today) - dt.date.fromisoformat(cache[q].get("checked", "2000-01-01"))).days > RECHECK_DAYS]
    if stale:
        try:
            import radar                              # only needed when there's something to look up
            for i in range(0, len(stale), 200):
                batch = stale[i:i + 200]
                rows = radar.sparql("SELECT ?w ?g ?ol WHERE { VALUES ?w { " + " ".join(f"wd:{q}" for q in batch) +
                                    " } OPTIONAL { ?w wdt:P2034 ?g } OPTIONAL { ?w wdt:P648 ?ol } }")
                found: dict[str, dict] = {q: {"g": None, "ol": None, "checked": today} for q in batch}
                for r in rows:
                    q = radar.qid(radar.v(r, "w"))
                    g, ol = radar.v(r, "g"), radar.v(r, "ol")
                    if g and not found[q]["g"]:
                        found[q]["g"] = g
                    # Prefer an Open Library *work* (OL…W) over an edition or an author.
                    if ol and (not found[q]["ol"] or (ol.endswith("W") and not found[q]["ol"].endswith("W"))):
                        found[q]["ol"] = ol
                cache.update(found)
        except Exception as e:                        # a lookup failure just means no links tonight
            log(f"      free reading lookup failed: {e}")
        with open(path, "w") as f:
            json.dump(cache, f, separators=(",", ":"), sort_keys=True)
    out = {}
    for q in qids:
        c = cache.get(q) or {}
        links = []
        if c.get("g"):
            links.append({"source": "Project Gutenberg", "label": "Read it free on Project Gutenberg",
                          "url": f"https://www.gutenberg.org/ebooks/{c['g']}"})
        ol = c.get("ol") or ""
        if ol.endswith("W") or ol.endswith("M"):
            links.append({"source": "Open Library", "label": "Borrow it free from Open Library, if a copy is available",
                          "url": f"https://openlibrary.org/{'works' if ol.endswith('W') else 'books'}/{ol}"})
        if links:
            out[q] = links
    n_new = sum(1 for q in stale if q in out)
    if stale:
        log(f"      free reading: checked {len(stale)} books, {n_new} with a free copy")
    return out
