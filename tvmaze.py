"""
TVmaze, for TV comebacks: a new season, a revival or a special airing is the most common reason an
old series comes back. TVmaze's API is free and its data is licensed CC BY-SA, which allows
commercial use with credit (https://www.tvmaze.com/api#licensing). No key needed; the limit is
20 calls every 10 seconds.

  episodes(qid, around)   episodes of this series (found by its IMDb number from Wikidata) that
                          aired from 14 days before the comeback started to 3 days after.
                          Evidence items like explain.py's, credited "TVmaze".
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.tvmaze.com"
WD_API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "Rallyback/1.0 (+https://therallyback.com/?tab=about)"}
MAX_LOOKUPS = 80
STATS = {"lookups": 0, "found": 0, "failed": 0}
_last = 0.0


def _get(url: str, headers: dict | None = None):
    global _last
    wait = 0.6 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            STATS["failed"] += 1
        return None
    except Exception:
        STATS["failed"] += 1
        return None


def imdb_id(qid: str) -> str | None:
    d = _get(f"{WD_API}?{urllib.parse.urlencode({'action': 'wbgetclaims', 'entity': qid, 'property': 'P345', 'format': 'json'})}")
    for c in ((d or {}).get("claims") or {}).get("P345", []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(v, str) and v.startswith("tt"):
            return v
    return None


def _channel(show: dict) -> str:
    return ((show.get("webChannel") or {}).get("name") or (show.get("network") or {}).get("name") or "").strip()


def episodes(qid: str | None, around: dt.date, before: int = 14, after: int = 3) -> list[dict]:
    if not qid or STATS["lookups"] >= MAX_LOOKUPS or STATS["failed"] >= 5:
        return []
    STATS["lookups"] += 1
    imdb = imdb_id(qid)
    if not imdb:
        return []
    show = _get(f"{API}/lookup/shows?imdb={imdb}")
    if not show or not show.get("id"):
        return []
    eps = _get(f"{API}/shows/{show['id']}/episodes?specials=1") or []
    lo, hi = around - dt.timedelta(days=before), around + dt.timedelta(days=after)
    hits = []
    for e in eps:
        try:
            day = dt.date.fromisoformat(e.get("airdate") or "")
        except ValueError:
            continue
        if lo <= day <= hi:
            hits.append((day, e))
    if not hits:
        return []
    hits.sort(key=lambda x: x[0])
    day, first = hits[0]
    chan = _channel(show)
    seasons = sorted({e.get("season") for _, e in hits if e.get("season")})
    if first.get("type") == "significant_special" or not first.get("number"):
        what = f"A special, “{first.get('name')}”, aired"
    elif first.get("number") == 1:
        what = f"Season {first.get('season')} premiered"
    else:
        what = f"New episodes of season {', '.join(map(str, seasons))} aired"
    text = f"{what} on {day.day} {day:%B %Y}" + (f" on {chan}" if chan else "") + \
           (f" ({len(hits)} episodes in the window)" if len(hits) > 1 else "")
    STATS["found"] += 1
    return [{"source": "TVmaze", "date": day.isoformat(), "published": day.isoformat(), "text": text, "cause": "new season",
             "url": first.get("url") or show.get("url") or f"https://www.tvmaze.com/shows/{show['id']}"}]


def summary() -> str:
    return f"      TVmaze: {STATS['lookups']} series looked up, new episodes found for {STATS['found']}" + \
        (f", {STATS['failed']} failed" if STATS["failed"] else "")


if __name__ == "__main__":
    # python tvmaze.py Q-id|YYYY-MM-DD ...
    for arg in sys.argv[1:]:
        q, _, d = arg.partition("|")
        around = dt.date.fromisoformat(d) if d else dt.date.today() - dt.timedelta(days=5)
        print(q, around, episodes(q, around))
    print(summary().strip())
