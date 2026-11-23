"""
GDELT, read from its raw data files instead of its search service (which refuses shared cloud
addresses). GDELT publishes a Global Knowledge Graph file every 15 minutes at
data.gdeltproject.org/gdeltv2/<YYYYMMDDHHMMSS>.gkg.csv.zip: one row per news article seen
worldwide, with its address, outlet and (in the last column) its headline.

  refresh()   once a night: download the 15-minute files since the last run (at most a day's
              worth, 96 files), keep only headlines that quote something (‘Title’, "Title"), the
              way news writes the names of films, songs, games and books. Kept 30 days,
              gzipped, in .cache/gdelt_headlines.json.gz (the workflow cache).
  search(q)   those headlines matching a work's title, same rules as newsfeeds.py.

Run `python gdeltfiles.py --test [hours] ["Title" ...]` to time a download and search.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

import newsfeeds

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, ".cache", "gdelt_headlines.json.gz")
BASE = "http://data.gdeltproject.org/gdeltv2/{}.gkg.csv.zip"
KEEP_DAYS = 30
MAX_FILES = 96                    # one day of 15-minute files a night
BUDGET = 15 * 60                  # seconds for the whole download
_TITLE = re.compile(rb"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)
_QUOTED = re.compile("[‘'\"“][A-Z0-9][^’'\"”]{1,80}[’'\"”]")

_store: dict | None = None
_refreshed = False
STATS = {"files": 0, "failed": 0, "rows": 0, "kept": 0, "mb": 0.0, "seconds": 0.0}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _load() -> dict:
    global _store
    if _store is None:
        try:
            with gzip.open(STORE, "rt") as f:
                _store = json.load(f)
        except (OSError, json.JSONDecodeError, EOFError):
            _store = {}
        _store.setdefault("done", "")             # last 15-minute slot read
        _store.setdefault("items", {})            # url → [date, outlet, headline]
    return _store


def _save() -> None:
    s = _load()
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    s["items"] = {u: v for u, v in s["items"].items() if v[0] >= cutoff}
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with gzip.open(STORE, "wt") as f:
        json.dump(s, f, separators=(",", ":"))


def _slots(since: str, now: dt.datetime, limit: int) -> list[str]:
    """15-minute file names after `since` (YYYYMMDDHHMMSS), oldest first, at most `limit`
    (the newest ones when there are more). GDELT posts each file a few minutes after its slot."""
    end = now - dt.timedelta(minutes=20)
    end = end.replace(minute=end.minute - end.minute % 15, second=0, microsecond=0)
    start = dt.datetime.strptime(since, "%Y%m%d%H%M%S") + dt.timedelta(minutes=15) if since else end - dt.timedelta(days=1)
    start = max(start, end - dt.timedelta(minutes=15 * (limit - 1)))
    out, t = [], start
    while t <= end:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t += dt.timedelta(minutes=15)
    return out


def _read(slot: str, items: dict) -> bool:
    try:
        req = urllib.request.Request(BASE.format(slot), headers=newsfeeds.UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except Exception:
        return False
    STATS["mb"] += len(raw) / 1e6
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        data = z.read(z.namelist()[0])
    except Exception:
        return False
    day = f"{slot[:4]}-{slot[4:6]}-{slot[6:8]}"
    for line in data.split(b"\n"):
        if not line:
            continue
        STATS["rows"] += 1
        m = _TITLE.search(line)
        if not m:
            continue
        title = newsfeeds._text(m.group(1).decode("utf-8", "replace"))
        if not _QUOTED.search(title):
            continue
        cols = line.split(b"\t", 5)
        if len(cols) < 5:
            continue
        url = cols[4].decode("utf-8", "replace")
        if url.startswith("http") and url not in items:
            items[url] = [day, cols[3].decode("utf-8", "replace") or "news", title[:200]]
            STATS["kept"] += 1
    return True


def refresh(budget: float = BUDGET, limit: int = MAX_FILES) -> dict:
    global _refreshed
    if _refreshed:
        return STATS
    _refreshed = True
    s = _load()
    t0 = time.time()
    slots = _slots(s["done"], dt.datetime.utcnow(), limit)
    for slot in slots:
        if time.time() - t0 > budget:
            log("      GDELT files: time limit reached")
            break
        if _read(slot, s["items"]):
            STATS["files"] += 1
            s["done"] = slot
        else:
            STATS["failed"] += 1
    STATS["seconds"] = round(time.time() - t0, 1)
    if STATS["files"]:
        _save()
    elif slots:
        try:
            import radar
            radar.HEALTH.setdefault("sources_off", []).append("GDELT files")
        except Exception:
            pass
    log(f"      GDELT files: {STATS['files']} read ({STATS['mb']:.0f} MB, {STATS['seconds']:.0f}s), "
        f"{STATS['kept']} new quoted headlines, {len(s['items'])} kept"
        + (f", {STATS['failed']} failed" if STATS["failed"] else ""))
    return STATS


def search(query: str, around: dt.date, before: int = 14, after: int = 7, n: int = 6) -> list[dict]:
    """Headlines quoting this work's title, published around the comeback."""
    refresh()
    core = newsfeeds._pattern(query)
    if core is None:
        return []
    lo, hi = (around - dt.timedelta(days=before)).isoformat(), (around + dt.timedelta(days=after)).isoformat()
    hits = sorted(((d, src, t, u) for u, (d, src, t) in _load()["items"].items()
                   if lo <= d <= hi and newsfeeds._matches(core, False, t)), reverse=True)
    # Wire stories (AP, Reuters) run in dozens of papers under one headline: keep one of each.
    seen, out = set(), []
    for d, src, t, u in hits:
        key = re.sub(r"\W+", " ", t.lower()).strip()[:90]
        if key not in seen:
            seen.add(key)
            out.append(newsfeeds._evidence(src, d, t, u, ""))
        if len(out) >= n:
            break
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--test"]
    hours = int(args.pop(0)) if args and args[0].isdigit() else 24
    refresh(budget=BUDGET, limit=hours * 4)
    print(json.dumps(STATS))
    today = dt.date.today()
    for q in args:
        hits = search(q, today - dt.timedelta(days=3))
        print(f"\n== {q}: {len(hits)}")
        for e in hits[:5]:
            print(f"   {e['published']}  {e['source']}: {e['text'][:100]}\n      {e['url'][:110]}")
