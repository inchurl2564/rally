"""
Currents News API, for news GDELT's files miss: headlines from thousands of news sites, searched by a
comeback's title. Free plan: 250 requests a UTC day, 30 days back, at most 7 days per search, commercial
use allowed with attribution (https://currentsapi.services/en/pricing, /terms). Key: the CURRENTS_API_KEY
repository secret; without it, everything here quietly does nothing.

Currents' terms (read 2026-11-23) shape what we keep:
  * no permanent copies or databases of its data: evidence keeps only the article's link, its site and
    date, and our own reason word. The headline and preview are read in memory to match the title and
    find the reason, then dropped.
  * "Powered by Currents News API", linked, beside anything shown from it: evidence carries
    `credit`, which the site prints next to the link.
  * no publishing statistics about its data: nothing counts Currents results on the site.
Articles stay the publishers'; we only link to them.

  search(title, around)   articles whose headline names the title (in quotes for works, by full name
                          for people) from 5 days before the comeback started to 1 day after (a 7-day
                          window: the free plan's limit per search).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.currentsapi.services/v1/search"
CREDIT = {"text": "Powered by Currents News API", "url": "https://currentsapi.services/"}
UA = {"User-Agent": "Rallyback/1.0 (+https://therallyback.com/?tab=about)", "Accept": "application/json"}
MAX_SEARCHES = 200            # of 250 a day, leaving room for a rerun
LOOKBACK = 29                 # the free plan searches the last 30 days
STATS = {"searches": 0, "found": 0, "failed": 0}
_off = False
_last = 0.0


def _key() -> str | None:
    return os.environ.get("CURRENTS_API_KEY") or None


def _get(params: dict) -> dict | None:
    global _off, _last
    key = _key()
    if not key or _off:
        return None
    wait = 1.0 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}", headers={**UA, "Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        STATS["failed"] += 1
        if e.code in (401, 403, 429) or STATS["failed"] >= 5:      # bad key, daily cap reached, or trouble
            # (a single 400 is one bad query, not a reason to stop)
            _off = True
            print(f"      Currents: switching off for this run ({e.code})", file=sys.stderr)
            try:
                import radar
                radar.HEALTH.setdefault("sources_off", []).append("Currents")
            except Exception:
                pass
        return None
    except Exception:
        STATS["failed"] += 1
        return None


def _site(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def search(title: str, around: dt.date, person: bool = False, kind: str | None = None, n: int = 3) -> list[dict]:
    if not _key() or _off or STATS["searches"] >= MAX_SEARCHES:
        return []
    import explain
    import newsfeeds
    core = newsfeeds._pattern(title)
    if not core:
        return []
    name = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    if not person and len(name.split()) < 2 and len(name) < 8:
        return []                                   # "Heist", "Arthur": everyday words in headlines
    today = dt.date.today()
    lo = max(around - dt.timedelta(days=5), today - dt.timedelta(days=LOOKBACK))
    hi = min(around + dt.timedelta(days=1), today)           # lo..hi end of day = under 7 days
    if lo > hi:
        return []                                   # older than the free plan reaches
    STATS["searches"] += 1
    # `query` is the exact-phrase search; `keywords` matches loosely (word forms, anywhere in the text).
    d = _get({"query": f'"{name}"', "language": "en", "page_size": 20,
              "start_date": f"{lo.isoformat()}T00:00:00+00:00", "end_date": f"{hi.isoformat()}T23:59:59+00:00"})
    out, seen = [], set()
    for a in (d or {}).get("news") or []:
        headline, url = (a.get("title") or "").strip(), a.get("url") or ""
        if not url or not newsfeeds._matches(core, person, headline):
            continue
        site = _site(url)
        if site in seen:
            continue                                # one article per site is plenty
        seen.add(site)
        day = (a.get("published") or "")[:10] or around.isoformat()
        text = f"{headline} {a.get('description') or ''}"          # read here only, never kept
        cause = next((c for c, rx in explain._CAUSE_RE if rx.search(text)), None)
        e = {"source": f"News · {site}", "date": day, "published": day, "url": url,
             "text": f"Report on {site}" + (f" ({cause})" if cause else ""), "credit": CREDIT}
        if cause:
            e["cause"] = cause
        out.append(e)
        if len(out) >= n:
            break
    STATS["found"] += bool(out)
    return out


def summary() -> str:
    if not _key():
        return "      Currents: no key set (CURRENTS_API_KEY), skipped"
    return f"      Currents: {STATS['searches']} searches, articles found for {STATS['found']}" + \
        (f", {STATS['failed']} failed" if STATS["failed"] else "")


if __name__ == "__main__":
    # python currents.py "Title|YYYY-MM-DD" ...   (needs CURRENTS_API_KEY)
    for arg in sys.argv[1:]:
        t, _, day = arg.partition("|")
        around = dt.date.fromisoformat(day) if day else dt.date.today() - dt.timedelta(days=5)
        for e in search(t, around):
            print(f"  {e['published']}  {e['source']}: {e['text']}\n     {e['url']}")
    print(summary().strip())
