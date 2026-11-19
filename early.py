"""
Early detection from Wikimedia's daily bulk pageview files.

The per-article API needs one request per article, so the radar used to only look
at works that reached English Wikipedia's daily top 1,000 — by which point a spike
is big and often already noticed. The bulk files (dumps.wikimedia.org,
pageview_complete, human traffic only) contain every article's views in one
download, so we can watch tens of thousands of notable older works every day and
flag them as soon as they start to rise.

  watchlist   ~35k creative works with an English Wikipedia article, at least
              MIN_SITELINKS language editions, released at least MIN_AGE years ago
              (from Wikidata, rebuilt weekly)
  daily file  stream the bz2, keep only en.wikipedia rows for watchlist titles,
              store {title: [views, desktop_views]} per day
  flag        yesterday's views well above the title's own recent median
"""

from __future__ import annotations

import bz2
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.request

import radar

DUMPS = "https://dumps.wikimedia.org/other/pageview_complete"
BULK = os.path.join(radar.CACHE, "bulk")
WATCHLIST = os.path.join(radar.CACHE, "watchlist.json")

MIN_SITELINKS = 10

# (kind, classes, date property path, date ranges)
# Films are the biggest group: 5-year slices keep each query under Wikidata's 60 s limit.
_DECADES = [(1500, 1930), (1930, 1950)] + [(y, y + 5) for y in range(1950, 2030, 5)]
GROUPS = [
    ("film", "wd:Q11424 wd:Q24869 wd:Q202866 wd:Q506240", "wdt:P577", _DECADES),
    ("song", "wd:Q7366 wd:Q134556 wd:Q105543609", "wdt:P577", [(1500, 1960), (1960, 1980), (1980, 2000), (2000, 2030)]),
    ("album", "wd:Q482994 wd:Q208569 wd:Q169930 wd:Q209939", "wdt:P577", [(1500, 1970), (1970, 1990), (1990, 2005), (2005, 2030)]),
    ("video game", "wd:Q7889", "wdt:P577", [(1950, 2000), (2000, 2030)]),
    ("TV series", "wd:Q5398426 wd:Q581714 wd:Q1259759 wd:Q63952888 wd:Q526877 wd:Q117467246",
     "wdt:P580|wdt:P577", [(1900, 2030)]),
    ("book", "wd:Q7725634 wd:Q8261 wd:Q47461344 wd:Q571", "wdt:P577", [(1000, 2030)]),
    ("manga/comic", "wd:Q21198342 wd:Q1004 wd:Q14406742", "wdt:P577", [(1800, 2030)]),
]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def build_watchlist(min_age: int, max_age_days: float = 7) -> dict[str, dict]:
    """{enwiki title: {"qid", "kind", "release"}} for notable older works. Cached for a week."""
    if os.path.exists(WATCHLIST) and time.time() - os.path.getmtime(WATCHLIST) < max_age_days * 86400:
        with open(WATCHLIST) as f:
            return json.load(f)
    cutoff = dt.date.today().year - min_age
    out: dict[str, dict] = {}
    for kind, classes, prop, ranges in GROUPS:
        for lo, hi in ranges:
            hi = min(hi, cutoff + 1)
            if lo >= hi:
                continue
            q = f"""
            SELECT ?item ?article (MIN(?date) AS ?d) (MAX(?sl) AS ?s) WHERE {{
              VALUES ?class {{ {classes} }}
              ?item wdt:P31 ?class; wikibase:sitelinks ?sl; {prop} ?date .
              FILTER(?sl >= {MIN_SITELINKS} && ?date >= "{lo:04d}-01-01T00:00:00Z"^^xsd:dateTime
                     && ?date < "{hi:04d}-01-01T00:00:00Z"^^xsd:dateTime)
              ?article schema:about ?item; schema:isPartOf <https://en.wikipedia.org/> .
            }} GROUP BY ?item ?article"""
            try:
                rows = radar.sparql(q)
            except Exception as e:
                log(f"      watchlist query failed ({kind} {lo}-{hi}): {e}")
                radar.HEALTH["lookups_failed"] += 1
                continue
            for row in rows:
                title = radar.urllib.parse.unquote(radar.v(row, "article").split("/wiki/", 1)[1])
                out.setdefault(title, {"qid": radar.qid(radar.v(row, "item")), "kind": kind,
                                       "release": (radar.v(row, "d") or "")[:10],
                                       "sitelinks": int(radar.v(row, "s") or 0)})
    if out:
        os.makedirs(radar.CACHE, exist_ok=True)
        with open(WATCHLIST, "w") as f:
            json.dump(out, f)
    elif os.path.exists(WATCHLIST):  # every query failed: fall back to last week's list
        with open(WATCHLIST) as f:
            return json.load(f)
    return out


def ingest_day(day: dt.date, titles: set[str], project: str = "en.wikipedia") -> dict | None:
    """Views for watchlist titles on one day, from the bulk file. Stored, so each day is read once."""
    os.makedirs(BULK, exist_ok=True)
    path = os.path.join(BULK, f"{day.isoformat()}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    url = f"{DUMPS}/{day:%Y}/{day:%Y-%m}/pageviews-{day:%Y%m%d}-user.bz2"
    prefix = project.encode() + b" "
    keep = {t.encode() for t in titles}
    views: dict[bytes, list[int]] = {}
    t0 = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": radar.UA})
        resp = urllib.request.urlopen(req, timeout=120)
    except Exception as e:
        log(f"      bulk file for {day} unavailable: {e}")
        return None
    dec = bz2.BZ2Decompressor()
    buf = b""
    seen_project = False
    try:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            buf += dec.decompress(chunk)
            lines = buf.split(b"\n")
            buf = lines.pop()
            for ln in lines:
                if not ln.startswith(prefix):
                    if seen_project:      # file is sorted by project: we're past it
                        raise StopIteration
                    continue
                seen_project = True
                # "en.wikipedia Title page_id platform daily_total hourly"
                parts = ln.split(b" ")
                if len(parts) < 5 or parts[1] not in keep:
                    continue
                v = views.setdefault(parts[1], [0, 0])
                n = int(parts[4])
                v[0] += n
                if parts[3] == b"desktop":
                    v[1] += n
    except StopIteration:
        pass
    except Exception as e:
        log(f"      bulk file for {day} failed mid-stream: {e}")
        radar.HEALTH["pages_skipped"] += 1
        return None
    finally:
        resp.close()
    out = {k.decode(): val for k, val in views.items()}
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    log(f"      {day}: {len(out):,} watched works in {time.time() - t0:.0f}s")
    return out


def latest_bulk_day() -> dt.date:
    """The bulk file for a day appears a few hours after it ends."""
    d = dt.date.today() - dt.timedelta(days=1)
    for _ in range(4):
        url = f"{DUMPS}/{d:%Y}/{d:%Y-%m}/pageviews-{d:%Y%m%d}-user.bz2"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": radar.UA})
            urllib.request.urlopen(req, timeout=30).close()
            return d
        except Exception:
            d -= dt.timedelta(days=1)
    return d


def prune(keep_days: int) -> None:
    if not os.path.isdir(BULK):
        return
    cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    for f in os.listdir(BULK):
        if f[:10] < cutoff:
            os.remove(os.path.join(BULK, f))


def early_candidates(min_age: int, days: int = 28, min_ratio: float = 2.5, min_views: int = 150,
                     max_new_days: int = 28) -> dict[str, dict]:
    """Titles from the watchlist whose last 1–3 days are well above their own recent median.

    Needs at least 8 days of bulk data. The first run downloads up to `max_new_days` files
    (about a minute each); later runs download one."""
    watch = build_watchlist(min_age)
    log(f"      watchlist: {len(watch):,} notable works")
    if not watch:
        return {}
    titles = set(watch)
    end = latest_bulk_day()
    days_data: list[tuple[dt.date, dict]] = []
    fetched = 0
    for i in range(days):
        d = end - dt.timedelta(days=i)
        have = os.path.exists(os.path.join(BULK, f"{d.isoformat()}.json"))
        if not have and fetched >= max_new_days:
            continue
        data = ingest_day(d, titles)
        if not have:
            fetched += 1
        if data is not None:
            days_data.append((d, data))
    prune(days + 7)
    days_data.sort()
    if len(days_data) < 8:
        log(f"      only {len(days_data)} days of bulk data so far; early detection starts at 8")
        return {}
    hist = days_data
    recent = [dd for d, dd in hist[-3:]]
    base_days = [dd for d, dd in hist[:-3]]
    flagged = {}
    for t in titles:
        base = [dd.get(t, [0, 0])[0] for dd in base_days]
        med = max(statistics.median(base), 5)
        last = [dd.get(t, [0, 0])[0] for dd in recent]
        best = max(last[-1], sum(last) / len(last))
        if best >= min_views and best / med >= min_ratio:
            flagged[t] = {"early_ratio": round(best / med, 1), "early_views": int(best), "watch": watch[t]}
    log(f"      {len(flagged)} watched works rising early (≥{min_ratio}× their recent median)")
    return flagged
