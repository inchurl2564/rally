"""
MusicBrainz, for album reissues: a remaster, an anniversary edition or a vinyl repress often brings an
old album (and its songs) back. MusicBrainz's core data (artists, releases, release dates, formats) is
CC0, free for any use; we read nothing else (tags and ratings are non-commercial).
https://musicbrainz.org/doc/About/Data_License

  reissues(qid, around, kind)   editions of this album (or of the album a song is on) released from
                                21 days before the comeback started to 5 days after. The album is
                                found through Wikidata's MusicBrainz release group ID (P436).

MusicBrainz asks for at most one request a second and a User-Agent that says who we are.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://musicbrainz.org/ws/2"
WD_API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "Rallyback/1.0 ( https://therallyback.com/?tab=about )", "Accept": "application/json"}
MAX_LOOKUPS = 60
STATS = {"lookups": 0, "found": 0, "failed": 0}
_last = 0.0


def _get(url: str):
    global _last
    wait = 1.1 - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()
    for attempt in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt == 0:      # MusicBrainz's "slow down": wait and try once more
                time.sleep(3)
                continue
            if e.code != 404:
                STATS["failed"] += 1
            return None
        except Exception:
            STATS["failed"] += 1
            return None
    return None


def _claims(qid: str, prop: str) -> list[str]:
    d = _get(f"{WD_API}?{urllib.parse.urlencode({'action': 'wbgetclaims', 'entity': qid, 'property': prop, 'format': 'json'})}")
    out = []
    for c in ((d or {}).get("claims") or {}).get(prop, []):
        v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        out.append(v.get("id") if isinstance(v, dict) else v)
    return [x for x in out if x]


def _range(date: str) -> tuple[dt.date, dt.date] | None:
    """A MusicBrainz date ("2026-11-14", "2026-11" or "2026") as a range of days."""
    try:
        parts = [int(x) for x in date.split("-")]
    except ValueError:
        return None
    if len(parts) == 3:
        d = dt.date(*parts)
        return d, d
    if len(parts) == 2:
        first = dt.date(parts[0], parts[1], 1)
        return first, (first + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    return None                                   # a year alone is too vague to time a comeback


def reissues(qid: str | None, around: dt.date, kind: str | None) -> list[dict]:
    if not qid or kind not in ("album", "song") or STATS["lookups"] >= MAX_LOOKUPS or STATS["failed"] >= 10:
        return []
    STATS["lookups"] += 1
    groups = _claims(qid, "P436")
    if not groups and kind == "song":
        for album in _claims(qid, "P361")[:2]:       # the album the song is on
            groups += _claims(album, "P436")
    lo, hi = around - dt.timedelta(days=21), around + dt.timedelta(days=5)
    out = []
    for mbid in groups[:2]:
        rg = _get(f"{API}/release-group/{mbid}?{urllib.parse.urlencode({'inc': 'releases+media', 'fmt': 'json'})}")
        if not rg:
            continue
        first = _range(rg.get("first-release-date") or "")
        if first and first[1] >= lo:
            continue                                  # a new album, not a reissue
        for rel in rg.get("releases") or []:
            r = _range(rel.get("date") or "")
            if not r or r[0] > hi or r[1] < lo:
                continue
            fmts = sorted({m.get("format") for m in rel.get("media") or [] if m.get("format")})
            what = f"{', '.join(fmts)} " if fmts else ""
            when = f"{r[0].day} {r[0]:%B %Y}" if r[0] == r[1] else f"{r[0]:%B %Y}"
            out.append({"source": "MusicBrainz", "date": r[0].isoformat(), "published": r[0].isoformat(),
                        "text": f"A new {what}edition of “{rg.get('title')}” came out in {when}"
                                + (f" ({rel.get('disambiguation')})" if rel.get("disambiguation") else ""),
                        "url": f"https://musicbrainz.org/release/{rel['id']}", "cause": "re-release"})
            break
    STATS["found"] += bool(out)
    return out[:1]


def summary() -> str:
    return f"      MusicBrainz: {STATS['lookups']} albums looked up, reissues found for {STATS['found']}" + \
        (f", {STATS['failed']} failed" if STATS["failed"] else "")


if __name__ == "__main__":
    # python musicbrainz.py "Q-id|album|YYYY-MM-DD" ...
    for arg in sys.argv[1:]:
        q, k, d = (arg.split("|") + ["", ""])[:3]
        print(q, reissues(q, dt.date.fromisoformat(d) if d else dt.date.today() - dt.timedelta(days=5), k or "album"))
    print(summary().strip())
