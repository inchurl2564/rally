"""
YouTube, for comebacks the news can't explain: a trailer, a viral clip or a video essay often
sends people back to an old title. Uses the official YouTube Data API v3 with the
YOUTUBE_API_KEY secret (free; 10,000 quota units a day, a search costs 100).

  search(title, around, kind)   the most-watched videos naming this title, published from
                                14 days before the comeback started to 7 days after, with
                                at least MIN_VIEWS views. Evidence items like explain.py's.

YouTube's terms limit how long raw API data may be kept, so nothing here is stored between
runs: each night's evidence is that night's lookup. The permanent record keeps only our own
conclusion (the cause), not YouTube's numbers.

Without a key, everything here quietly does nothing.
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

API = "https://www.googleapis.com/youtube/v3"
MAX_SEARCHES = 60            # 6,000 of the 10,000 daily units, leaving room for reruns
MIN_VIEWS = 100_000          # smaller videos rarely move a title's Wikipedia traffic
VIRAL_VIEWS = 1_000_000      # a video this big with no other reason in its title counts as "viral"
KIND_NOUN = {"film": "movie", "TV series": "series", "song": "song", "album": "album", "musical": "musical",
             "video game": "game", "book": "book", "manga/comic": "manga"}
STATS = {"searches": 0, "found": 0, "failed": 0, "trending": 0, "trending_found": 0}
_off = False


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _key() -> str | None:
    return os.environ.get("YOUTUBE_API_KEY") or None


def _get(path: str, params: dict) -> dict | None:
    global _off
    key = _key()
    if not key or _off:
        return None
    url = f"{API}/{path}?{urllib.parse.urlencode({**params, 'key': key})}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        STATS["failed"] += 1
        reason = ""
        try:
            reason = json.load(e).get("error", {}).get("errors", [{}])[0].get("reason", "")
        except Exception:
            pass
        if e.code in (400, 403) or STATS["failed"] >= 3:      # bad key, quota used up, or repeated trouble
            _off = True
            log(f"      YouTube: switching off for this run ({e.code} {reason})")
            try:
                import radar
                radar.HEALTH.setdefault("sources_off", []).append("YouTube")
            except Exception:
                pass
        return None
    except Exception:
        STATS["failed"] += 1
        return None


def _name(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


_CONTEXT = re.compile(r"\b(movie|film|trailer|teaser|scene|scenes|clip|official|soundtrack|ost|album|song|music video|"
                      r"lyrics|game|gameplay|remaster|book|novel|audiobook|drama|adaptation|review|explained|ending|"
                      r"cast|behind the scenes|full episode|series|season)\b", re.I)


def _matches(name: str, video_title: str, kind: str | None) -> bool:
    """The title must be in the video's title as a whole phrase, and the video title must also
    say what it is (a trailer, a film, a song...), so "lost in translation" as a phrase or a
    different film's clips with a generic name don't count."""
    if not re.search(r"(?<!\w)" + re.escape(name).replace(r"\ ", r"\s+") + r"(?!\w)", video_title, re.I):
        return False
    return bool(_CONTEXT.search(video_title))


def search(title: str, around: dt.date, kind: str | None = None, n: int = 3) -> list[dict]:
    if not _key() or _off or STATS["searches"] >= MAX_SEARCHES:
        return []
    name = _name(title)
    if len(name) < 5:
        return []                       # "ATM", "Up", "Her": far too ambiguous on YouTube
    lo, hi = around - dt.timedelta(days=14), min(around + dt.timedelta(days=7), dt.date.today() + dt.timedelta(days=1))
    noun = KIND_NOUN.get(kind or "", "")
    STATS["searches"] += 1
    d = _get("search", {"part": "snippet", "type": "video", "order": "viewCount", "maxResults": 15,
                        "q": f'"{name}" {noun}'.strip(), "relevanceLanguage": "en",
                        "publishedAfter": f"{lo.isoformat()}T00:00:00Z", "publishedBefore": f"{hi.isoformat()}T00:00:00Z"})
    items = [x for x in (d or {}).get("items") or [] if x.get("id", {}).get("videoId")]
    items = [x for x in items if _matches(name, _unescape(x["snippet"].get("title", "")), kind)]
    if not items:
        return []
    stats = _get("videos", {"part": "statistics", "id": ",".join(x["id"]["videoId"] for x in items)})   # 1 unit
    views = {v["id"]: int(v.get("statistics", {}).get("viewCount", 0)) for v in (stats or {}).get("items") or []}
    out = []
    for x in sorted(items, key=lambda x: -views.get(x["id"]["videoId"], 0)):
        vid, sn = x["id"]["videoId"], x["snippet"]
        v = views.get(vid, 0)
        if v < MIN_VIEWS:
            continue
        day = sn.get("publishedAt", "")[:10]
        vtitle = _unescape(sn.get("title", ""))
        out.append({"source": f"YouTube · {_unescape(sn.get('channelTitle', 'video'))}", "date": day, "published": day,
                    "text": f"{vtitle} ({v:,} views)"[:200], "url": f"https://www.youtube.com/watch?v={vid}",
                    "detail": _unescape(sn.get("description", ""))[:200], "views": v, "video": True})
        if len(out) >= n:
            break
    STATS["found"] += bool(out)
    return out


TRENDING_REGIONS = ("US", "GB", "CA", "AU")
TRENDING_CATEGORIES = {"10": "Music", "1": "Film & Animation", "24": "Entertainment", "20": "Gaming"}
_trending: list[dict] | None = None


def trending() -> list[dict]:
    """YouTube's most-popular chart, once a run: 4 countries x 4 categories, 50 videos each
    (1 quota unit per call, 16 in all). Kept in memory only, like everything else here."""
    global _trending
    if _trending is not None:
        return _trending
    _trending = []
    key = _key()
    if not key:
        return _trending
    seen: dict[str, dict] = {}
    for region in TRENDING_REGIONS:
        for cat in TRENDING_CATEGORIES:
            url = f"{API}/videos?" + urllib.parse.urlencode({"part": "snippet,statistics", "chart": "mostPopular",
                                                             "regionCode": region, "videoCategoryId": cat,
                                                             "maxResults": 50, "key": key})
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    items = json.load(r).get("items") or []
            except Exception:
                continue                 # some category/country charts don't exist; that's fine
            for it in items:
                v = seen.setdefault(it["id"], {"id": it["id"], "title": _unescape(it["snippet"].get("title", "")),
                                               "channel": _unescape(it["snippet"].get("channelTitle", "")),
                                               "published": it["snippet"].get("publishedAt", "")[:10],
                                               "views": int(it.get("statistics", {}).get("viewCount", 0) or 0),
                                               "category": cat, "regions": []})
                if region not in v["regions"]:
                    v["regions"].append(region)
    _trending = list(seen.values())
    STATS["trending"] = len(_trending)
    return _trending


def _segment_match(name: str, video_title: str) -> bool:
    """A one-word title must be a whole part of the video title ("Looker (1981)"), or in quotes:
    "Arthur" inside "James Arthur - Impossible" is someone's name, not the film."""
    if " " in name:
        return True
    parts = re.split(r"\s+[-–—|x×]\s+|[|()\[\]:,]", video_title)
    if any(p.strip().lower() == name.lower() for p in parts):
        return True
    return bool(re.search(r"[\"'‘“]" + re.escape(name) + r"[\"'’”]", video_title, re.I))


def trending_match(title: str, kind: str | None = None) -> list[dict]:
    """Videos on today's trending chart that name this title (same rules as search(), and a
    one-word title must stand on its own in the video title)."""
    name = _name(title)
    if len(name) < 5:
        return []
    out = []
    for v in trending():
        if not _matches(name, v["title"], kind) or not _segment_match(name, v["title"]):
            continue
        e = {"source": f"YouTube trending · {v['channel']}", "date": dt.date.today().isoformat(), "published": v["published"],
             "text": f"On YouTube's trending list ({', '.join(v['regions'])}): {v['title']} ({v['views']:,} views)"[:200],
             "url": f"https://www.youtube.com/watch?v={v['id']}", "views": v["views"], "video": True}
        if v["category"] == "10" and kind in ("song", "album"):
            e["cause"] = "viral"            # an old song's video on the music chart: the internet at work
        out.append(e)
    STATS["trending_found"] += bool(out)
    return out[:2]


def _unescape(s: str) -> str:
    import html
    return html.unescape(s or "")


def summary() -> str:
    if not _key():
        return "      YouTube: no key set (YOUTUBE_API_KEY), skipped"
    return f"      YouTube: {STATS['trending']} trending videos read, matched for {STATS['trending_found']}; " \
        f"{STATS['searches']} searches, videos found for {STATS['found']}" + \
        (f", {STATS['failed']} failed" if STATS["failed"] else "")


if __name__ == "__main__":
    # python youtube.py --test "Title|kind|YYYY-MM-DD" ...   (needs YOUTUBE_API_KEY)
    print("key present:", bool(_key()))
    for arg in [a for a in sys.argv[1:] if a != "--test"]:
        t, k, d = (arg.split("|") + ["", ""])[:3]
        around = dt.date.fromisoformat(d) if d else dt.date.today() - dt.timedelta(days=5)
        hits = search(t, around, k or None)
        print(f"\n== {t} ({k or 'any'}, around {around}): {len(hits)}")
        for e in hits:
            print(f"   {e['published']}  {e['source']}: {e['text'][:110]}\n      {e['url']}")
    print("\n" + summary().strip(), json.dumps(STATS))
