"""
Bluesky, for comebacks people are talking about. Bluesky's search (app.bsky.feed.searchPosts) finds
posts naming a title in quotes from 3 days before the comeback started to 7 days after. Search without
an account is refused after a couple of requests, so this signs in with an app password from the
BLUESKY_HANDLE and BLUESKY_APP_PASSWORD repository secrets (Bluesky: Settings > Privacy and security >
App passwords). Without them, everything here quietly does nothing.

What we keep is our own summary: how many posts we found, and a link to the same search on Bluesky.
Posts belong to the people who wrote them, so no post text is shown or stored; the most-liked posts'
words are only read, in memory, to see whether they agree on a reason ("RIP", "trailer", "Netflix").
That also means a deleted post is never kept anywhere (Bluesky developer guideline 3).

Developer guidelines: https://bsky.network/docs/developer-guidelines (read-only use: no posting,
following or liking; contact address on the About page).
"""

from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PDS = "https://bsky.social/xrpc"
API = f"{PDS}/app.bsky.feed.searchPosts"
UA = {"User-Agent": "Rallyback/1.0 (+https://therallyback.com/?tab=about)", "Accept": "application/json"}
MAX_SEARCHES = 120
MIN_POSTS = 15                 # fewer than this in ten days is ordinary chatter
STATS = {"searches": 0, "found": 0, "failed": 0}
_last = 0.0
_off = False
_token: str | None = None


def _login() -> str | None:
    global _token, _off
    if _token or _off:
        return _token
    handle, password = os.environ.get("BLUESKY_HANDLE"), os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not password:
        _off = True
        return None
    body = json.dumps({"identifier": handle, "password": password}).encode()
    try:
        req = urllib.request.Request(f"{PDS}/com.atproto.server.createSession", data=body,
                                     headers={**UA, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            _token = json.load(r).get("accessJwt")
    except Exception as e:
        print(f"      Bluesky: sign-in failed ({e})", file=sys.stderr)
        _off = True
    return _token


def _get(params: dict) -> dict | None:
    global _last, _off
    if not _login():
        return None
    wait = 1.0 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}",
                                                           headers={**UA, "Authorization": f"Bearer {_token}"}),
                                    timeout=25) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        STATS["failed"] += 1
        if e.code in (401, 403, 429) or STATS["failed"] >= 5:
            _off = True
            print(f"      Bluesky: switching off for this run ({e.code})", file=sys.stderr)
            try:
                import radar
                radar.HEALTH.setdefault("sources_off", []).append("Bluesky")
            except Exception:
                pass
        return None
    except Exception:
        STATS["failed"] += 1
        return None


def _name(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def talk(title: str, around: dt.date, kind: str | None = None) -> list[dict]:
    if _off or STATS["searches"] >= MAX_SEARCHES:
        return []
    name = _name(title)
    if len(name) < 5 or len(name.split()) < 2 and len(name) < 8:
        return []                        # "Heat", "Arthur": far too common in everyday posts
    lo, hi = around - dt.timedelta(days=3), min(around + dt.timedelta(days=7), dt.date.today() + dt.timedelta(days=1))
    STATS["searches"] += 1
    base = {"q": f'"{name}"', "since": f"{lo.isoformat()}T00:00:00Z", "until": f"{hi.isoformat()}T00:00:00Z",
            "lang": "en", "limit": 100}
    posts, cursor = [], None
    for _ in range(3):                                   # up to 300 posts is plenty to tell
        d = _get({**base, "sort": "latest", **({"cursor": cursor} if cursor else {})})
        if not d:
            break
        posts += d.get("posts") or []
        cursor = d.get("cursor")
        if not cursor:
            break
    rx = re.compile(r"(?<!\w)" + re.escape(name).replace(r"\ ", r"\s+") + r"(?!\w)", re.I)
    posts = [p for p in posts if rx.search((p.get("record") or {}).get("text", ""))]
    if len(posts) < MIN_POSTS:
        return []
    # What do the most-liked posts say? Read in memory only.
    import explain
    top = sorted(posts, key=lambda p: -(p.get("likeCount") or 0))[:20]
    votes = collections.Counter()
    for p in top:
        text = (p.get("record") or {}).get("text", "")
        for cause, crx in explain._CAUSE_RE:
            if crx.search(text):
                votes[cause] += 1
    likes = sum(p.get("likeCount") or 0 for p in posts)
    more = "+" if cursor and len(posts) >= 250 else ""
    e = {"source": "Bluesky", "date": around.isoformat(), "published": around.isoformat(),
         "text": f"{len(posts)}{more} Bluesky posts mention it between {lo:%b %-d} and {hi - dt.timedelta(days=1):%b %-d} ({likes:,} likes)",
         "url": "https://bsky.app/search?" + urllib.parse.urlencode({"q": f'"{name}"'}), "posts": len(posts)}
    if votes:
        cause, n = votes.most_common(1)[0]
        if n >= 3:                                       # several popular posts agree on why
            e["cause"] = cause
    STATS["found"] += 1
    return [e]


def summary() -> str:
    if not os.environ.get("BLUESKY_HANDLE"):
        return "      Bluesky: no account set (BLUESKY_HANDLE, BLUESKY_APP_PASSWORD), skipped"
    return f"      Bluesky: {STATS['searches']} searches, talk found for {STATS['found']}" + \
        (f", {STATS['failed']} failed" if STATS["failed"] else "")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        t, _, d = arg.partition("|")
        print(t, talk(t, dt.date.fromisoformat(d) if d else dt.date.today() - dt.timedelta(days=5)))
    print(summary().strip())
