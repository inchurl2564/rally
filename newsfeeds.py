"""
News for "why is it back?": a rolling library of headlines from entertainment and culture news
sites' own RSS feeds, plus a Google News search for comebacks the library can't explain.
Replaces GDELT, which refuses requests from shared cloud addresses (GitHub's included).

  refresh()        once a night: read each outlet's newest feed pages until reaching articles
                   already in the library (WordPress sites page back with ?paged=N); keep 75 days.
                   Stored in .cache/news_index.json (kept between runs by the workflow's cache).
  news(q, around)  articles mentioning q, published from 14 days before the comeback started to
                   7 days after: the library first, then Google News (at most GOOGLE_MAX a night).

Each result is evidence like the rest of explain.py: {"source", "date", "text", "url",
"published", "detail"}, where "published" is the article's own date (so a link can be checked
against the comeback's dates even when the address has no date in it).

Run `python newsfeeds.py --test [name ...]` to fetch every feed and search for some names.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, ".cache", "news_index.json")
KEEP_DAYS = 75
UA = {"User-Agent": "Mozilla/5.0 (compatible; Rallyback news reader; +https://therallyback.com/?tab=about)"}

# (outlet, feed address, pages back on a normal night, pages back the first time)
# Paged feeds are WordPress sites (?paged=N); the others are read once (they hold more items).
FEEDS = [
    ("Variety", "https://variety.com/feed/", 12, 60),
    ("Deadline", "https://deadline.com/feed/", 12, 60),
    ("The Hollywood Reporter", "https://www.hollywoodreporter.com/feed/", 10, 50),
    ("IndieWire", "https://www.indiewire.com/feed/", 6, 30),
    ("Billboard", "https://www.billboard.com/feed/", 10, 50),
    ("Rolling Stone", "https://www.rollingstone.com/feed/", 8, 40),
    ("NME", "https://www.nme.com/feed", 8, 40),
    ("Pitchfork", "https://pitchfork.com/feed/feed-news/rss", 1, 1),
    ("Polygon", "https://www.polygon.com/rss/index.xml", 1, 1),
    ("Kotaku", "https://kotaku.com/feed", 6, 30),
    ("Eurogamer", "https://www.eurogamer.net/feed", 1, 1),
    ("GameSpot", "https://www.gamespot.com/feeds/mashup/", 1, 1),
    ("Book Riot", "https://bookriot.com/feed/", 4, 20),
    ("The Guardian", "https://www.theguardian.com/culture/rss", 1, 1),
    ("The Guardian", "https://www.theguardian.com/film/rss", 1, 1),
    ("The Guardian", "https://www.theguardian.com/music/rss", 1, 1),
    ("The Guardian", "https://www.theguardian.com/books/rss", 1, 1),
    ("The Guardian", "https://www.theguardian.com/games/rss", 1, 1),
    ("The Guardian", "https://www.theguardian.com/tv-and-radio/rss", 1, 1),
    ("BBC News", "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml", 1, 1),
]
REFRESH_BUDGET = 8 * 60          # seconds for the whole nightly refresh
GOOGLE = "https://news.google.com/rss/search"
GOOGLE_MAX = 40                  # Google News searches a night, for what the library can't explain
GOOGLE_GAP = 2.0                 # seconds between them

_index: dict | None = None
_refreshed = False
_google_used = 0
_google_off = False
_google_last = 0.0
STATS = {"feeds_ok": 0, "feeds_failed": [], "new_articles": 0, "library": 0, "google": 0}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _get(url: str, timeout: int = 25) -> bytes | None:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def _text(s: str | None) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _date(s: str | None) -> str | None:
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        pass
    m = re.match(r"(\d{4}-\d\d-\d\d)", s.strip())          # Atom: 2026-11-22T10:00:00Z
    return m.group(1) if m else None


def parse(raw: bytes) -> list[dict]:
    """Items from an RSS or Atom feed: url, published date, headline, summary."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    out = []
    atom = "{http://www.w3.org/2005/Atom}"
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        out.append({"url": link, "date": _date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
                    "title": _text(it.findtext("title")), "summary": _text(it.findtext("description"))[:400],
                    "source": _text(it.findtext("source"))})
    for it in root.iter(f"{atom}entry"):
        ln = it.find(f"{atom}link")
        out.append({"url": (ln.get("href") if ln is not None else "") or "",
                    "date": _date(it.findtext(f"{atom}published") or it.findtext(f"{atom}updated")),
                    "title": _text(it.findtext(f"{atom}title")),
                    "summary": _text(it.findtext(f"{atom}summary") or it.findtext(f"{atom}content"))[:400], "source": ""})
    return [x for x in out if x["url"] and x["date"] and x["title"]]


def _load() -> dict:
    global _index
    if _index is None:
        try:
            with open(INDEX) as f:
                _index = json.load(f)
        except (OSError, json.JSONDecodeError):
            _index = {}
    return _index


def _save() -> None:
    idx = _load()
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for u in [u for u, v in idx.items() if v[0] < cutoff]:
        del idx[u]
    os.makedirs(os.path.dirname(INDEX), exist_ok=True)
    with open(INDEX, "w") as f:
        json.dump(idx, f, separators=(",", ":"))


def refresh(budget: float = REFRESH_BUDGET) -> dict:
    """Read every feed once a night (newest pages first) into the library."""
    global _refreshed
    if _refreshed:
        return STATS
    _refreshed = True
    idx = _load()
    have = {}
    for v in idx.values():
        have[v[1]] = have.get(v[1], 0) + 1
    end = time.time() + budget
    for name, url, pages, first_pages in FEEDS:
        if time.time() > end:
            log(f"      news library: time limit reached before {name}")
            break
        # A site seen before only needs its newest pages; a new one gets a deeper first read.
        limit = pages if have.get(name) else first_pages
        got_any = False
        for p in range(1, limit + 1):
            if time.time() > end:
                break
            page_url = url if p == 1 else f"{url}{'&' if '?' in url else '?'}paged={p}"
            raw = _get(page_url)
            items = parse(raw) if raw else []
            if not items:
                break
            got_any = True
            new = 0
            for x in items:
                if x["url"] not in idx:
                    idx[x["url"]] = [x["date"], name, x["title"], x["summary"]]
                    new += 1
            STATS["new_articles"] += new
            if new == 0 and have.get(name):
                break                                   # reached what we already have
            time.sleep(0.8)
        if got_any:
            STATS["feeds_ok"] += 1
        else:
            STATS["feeds_failed"].append(name)
    _save()
    STATS["library"] = len(idx)
    failed = sorted(set(STATS["feeds_failed"]))
    log(f"      news library: {STATS['new_articles']} new articles, {len(idx)} kept "
        f"({STATS['feeds_ok']} feeds read{'; failed: ' + ', '.join(failed) if failed else ''})")
    return STATS


_QUOTES_OPEN, _QUOTES_CLOSE = "‘'\"“", "’'\"”"


def _pattern(query: str):
    q = re.sub(r"\s*\([^)]*\)\s*$", "", query).strip()          # "Heist (2001 film)" → "Heist"
    if len(q) < 3:
        return None
    return re.escape(q).replace(r"\ ", r"\s+")


def _matches(core: str, person: bool, headline: str) -> bool:
    """Only headlines count (summaries mention whole filmographies). A work's title must be in
    quotes, the way entertainment news writes titles (‘The Nightingale’ Trailer), so everyday
    phrases ("lost in translation") and genre words ("heist") don't match. A person's full name
    counts as it stands."""
    if person:
        return bool(len(core) > 5 and " " in core.replace(r"\s+", " ")
                    and re.search(r"(?<!\w)" + core + r"(?!\w)", headline, re.I))
    m = re.search(f"[{_QUOTES_OPEN}]" + core + r"(?:[:,]?\s[^’'\"”]{0,60})?" + f"[{_QUOTES_CLOSE}]", headline, re.I)
    if not m:
        return False
    # A comparison is about something else: "'Minority Report' Meets 'Looper'", "a 'Heist'-style plot".
    around = headline[max(0, m.start() - 12): m.end() + 12].lower()
    return not re.search(r"\bmeets\b|-style|-esque|-like\b|\blike\s+[‘'\"“]|\bvibes\b|\bin the vein of\b", around)


def _evidence(source, date, title, url, summary) -> dict:
    return {"source": source, "date": date, "published": date, "text": title[:200], "url": url, "detail": summary[:300]}


def library_search(query: str, around: dt.date, before: int = 14, after: int = 7, n: int = 6,
                   person: bool = False) -> list[dict]:
    refresh()
    core = _pattern(query)
    if core is None:
        return []
    lo, hi = (around - dt.timedelta(days=before)).isoformat(), (around + dt.timedelta(days=after)).isoformat()
    hits = [(d, src, t, u, s) for u, (d, src, t, s) in _load().items() if lo <= d <= hi and _matches(core, person, t)]
    hits.sort(reverse=True)
    return [_evidence(src, d, t, u, s) for d, src, t, u, s in hits[:n]]


KIND_NOUN = {"film": "film", "TV series": "series", "song": "song", "album": "album", "musical": "musical",
             "video game": "game", "book": "book", "manga/comic": "manga"}


def google_search(query: str, around: dt.date, before: int = 14, after: int = 7, n: int = 6,
                  person: bool = False, kind: str | None = None) -> list[dict]:
    """Google News, for when the library has nothing. Capped per night; switches itself off
    after repeated failures (it may start refusing automated requests)."""
    global _google_used, _google_off, _google_last
    if _google_off or _google_used >= GOOGLE_MAX:
        return []
    core = _pattern(query)
    if core is None:
        return []
    q = re.sub(r"\s*\([^)]*\)\s*$", "", query).strip()
    lo, hi = around - dt.timedelta(days=before), around + dt.timedelta(days=after)
    # Google searches the whole web: naming the kind of work ("Heist" film) keeps it to coverage
    # of the work, not a stage play or a figure of speech.
    noun = "" if person else KIND_NOUN.get(kind or "", "")
    if not person and len(q.split()) == 1:
        return []                     # one-word titles ("Heist") are too ambiguous across the whole web
    params = {"q": f'"{q}" {noun + " " if noun else ""}after:{lo.isoformat()} before:{(hi + dt.timedelta(days=1)).isoformat()}',
              "hl": "en-US", "gl": "US", "ceid": "US:en"}
    wait = GOOGLE_GAP - (time.time() - _google_last)
    if wait > 0:
        time.sleep(wait)
    _google_last = time.time()
    _google_used += 1
    raw = _get(f"{GOOGLE}?{urllib.parse.urlencode(params)}")
    if raw is None:
        STATS.setdefault("google_failed", 0)
        STATS["google_failed"] += 1
        if STATS["google_failed"] >= 3:
            _google_off = True
            log("      Google News: switching off for this run after repeated errors")
            try:
                import radar
                radar.HEALTH.setdefault("sources_off", []).append("Google News")
            except Exception:
                pass
        return []
    STATS["google"] += 1
    out = []
    for x in parse(raw):
        if not (lo.isoformat() <= x["date"] <= hi.isoformat()):
            continue
        title = x["title"]
        src = x["source"] or "Google News"
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]               # "Headline - Variety" → "Headline"
        if _matches(core, person, title):
            out.append(_evidence(src, x["date"], title, x["url"], ""))
        if len(out) >= n:
            break
    return out


def news(query: str, around: dt.date, n: int = 6, person: bool = False, kind: str | None = None) -> list[dict]:
    return (library_search(query, around, n=n, person=person)
            or google_search(query, around, n=n, person=person, kind=kind))


if __name__ == "__main__":
    # A quick check of every feed and a few searches, for testing on GitHub's servers.
    args = [a for a in sys.argv[1:] if a != "--test"]
    for name, url, *_ in FEEDS:
        raw = _get(url)
        items = parse(raw) if raw else []
        page2 = parse(_get(f"{url}{'&' if '?' in url else '?'}paged=2") or b"") if items else []
        ds = sorted(x["date"] for x in items)
        print(f"{'OK ' if items else 'BAD'} {name:24} {len(items):3} items {ds[0] if ds else '':10} to {ds[-1] if ds else '':10}"
              f"  page 2: {'yes' if page2 and page2[0]['url'] != items[0]['url'] else 'no'}  {url}")
    refresh(budget=300)
    today = dt.date.today()
    for q in args:
        person = q.startswith("@")
        q = q.lstrip("@")
        hits = library_search(q.partition("|")[0], today - dt.timedelta(days=5), person=person) or []
        q, _, kind = q.partition("|")
        g = google_search(q, today - dt.timedelta(days=5), person=person, kind=kind or None) if not hits else []
        print(f"\n== {q}: {len(hits)} from the library, {len(g)} from Google News")
        for e in (hits or g)[:4]:
            print(f"   {e['published']}  {e['source']}: {e['text'][:90]}\n      {e['url'][:110]}")
