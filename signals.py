"""
Second opinions: is an old favorite back outside Wikipedia too?

Open sources that need no API key, matched to works through Wikidata IDs:

  Steam players      current players for older games (api.steampowered.com)        Wikidata P1733
  Steam reviews      new reviews per day, from the running total (store.steampowered.com)  P1733
  iTunes charts      top songs, albums and movies, US (itunes.apple.com RSS)      P10110 / P2281 / P6398
  Open Library       daily trending books (openlibrary.org)                         P648
  Project Gutenberg  most-downloaded ebooks, via Gutendex (gutendex.com)              P2034

Chart positions, player counts and review totals are snapshots that can't be fetched after the
fact, so every run records one and keeps it forever: site/data/signals/YYYY-MM.json, one file per
month. That record is published as open data, and it's what later lets The Rallyback measure how long
comebacks last and how big each kind of trigger tends to be.

A signal is *strong* when it shows a change, not just presence:
  Steam: players, or new reviews a day, at least 2x the median of earlier days
  Charts: a new entry (absent the previous 7 recorded days) or a big climb
Strong signals can add a work to the candidates; any signal is shown in its sources.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import glob
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

import radar

DIR = "signals"            # site/data/signals/YYYY-MM.json
CHARTS = {                 # key: (label, url, Wikidata property for the chart's own IDs, kinds it can match)
    "itunes-songs": ("iTunes top songs", "https://itunes.apple.com/us/rss/topsongs/limit=200/json", "P10110", {"song"}),
    "itunes-albums": ("iTunes top albums", "https://itunes.apple.com/us/rss/topalbums/limit=200/json", "P2281", {"album"}),
    "itunes-movies": ("iTunes top movies", "https://itunes.apple.com/us/rss/topmovies/limit=200/json", "P6398", {"film"}),
    # Deezer's charts were dropped on 2026-11-23: its developer terms allow only approved, private,
    # non-commercial use, and forbid keeping a database of its content or text and data mining.
    "openlibrary": ("Open Library trending", "https://openlibrary.org/trending/daily.json?limit=1000", "P648", {"book", "manga/comic"}),
    # Gutenberg's own top-100 page turns away automated requests; Gutendex is a public service
    # built on Gutenberg's catalog for exactly this, ranking books by downloads.
    "gutenberg": ("Project Gutenberg most downloaded", "https://gutendex.com/books/?sort=popular", "P2034", {"book"}),
}
STEAM_PLAYERS = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={}"
STEAM_REVIEWS = "https://store.steampowered.com/appreviews/{}?json=1&num_per_page=0&language=all&purchase_type=all"
NEW_DAYS = 7          # a chart entry is "new" if absent from the previous 7 recorded days
MIN_HISTORY = 3       # days of history before "new" or "Nx usual" can be judged
STEAM_MIN = 50        # ignore games with fewer players than this
REVIEWS_MIN = 5       # …or fewer new reviews a day than this
UA = {"User-Agent": "Rallyback/0.4 (open-data research; +https://github.com/inchurl2564/rally)"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class _Breaker:
    """Stop asking a source after a few failures in a row (it's down, or blocking us)."""
    def __init__(self, name, limit=5):
        self.name, self.limit, self.fails, self.off = name, limit, 0, False

    def ok(self):
        self.fails = 0

    def fail(self, why):
        self.fails += 1
        if self.fails >= self.limit and not self.off:
            self.off = True
            log(f"      {self.name}: switching off for this run ({why})")
            radar.HEALTH.setdefault("sources_off", []).append(self.name)   # shown in the footer; watched by health.py


def _fetch(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        body = r.read()
    if raw:
        return body.decode("utf-8", "replace")
    return json.loads(body)          # raises on an HTML page instead of JSON


def _get(url, raw=False):
    try:
        return _fetch(url, raw)
    except Exception as e:
        log(f"      {urllib.parse.urlparse(url).netloc}: {e}")
        return None


def _norm(s: str) -> str:
    s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s or "")          # (Remastered), [2022 Mix], (1987)
    s = re.sub(r"^(dr\. seuss' |disney's |bram stoker's )", "", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------- chart snapshots: [{rank, id, name, artist, year}] ----------

def _itunes(url):
    d = _get(url)
    rows = []
    for i, e in enumerate(((d or {}).get("feed") or {}).get("entry") or [], 1):
        href = e["id"]["label"]
        m = re.search(r"\?i=(\d+)", href)
        rows.append({"rank": i, "id": m.group(1) if m else e["id"]["attributes"]["im:id"],
                     "name": e["im:name"]["label"], "artist": (e.get("im:artist") or {}).get("label"),
                     "year": (e.get("im:releaseDate") or {}).get("label", "")[:4]})
    return rows


def _openlibrary(url):
    d = _get(url)
    return [{"rank": i, "id": w["key"].rsplit("/", 1)[-1], "name": w.get("title"),
             "artist": ", ".join(w.get("author_name") or [])[:80], "year": str(w.get("first_publish_year") or "")}
            for i, w in enumerate((d or {}).get("works") or [], 1)]


def _gutenberg(url):
    """The 128 most-downloaded Project Gutenberg books, from Gutendex (4 pages of 32)."""
    rows, nxt = [], url
    for _ in range(4):
        d = (_get(nxt) or _get(nxt)) if nxt else None          # Gutendex is sometimes slow: one retry
        for b in (d or {}).get("results") or []:
            rows.append({"rank": len(rows) + 1, "id": str(b["id"]), "name": (b.get("title") or "").split(";")[0].strip(),
                         "artist": ", ".join(a.get("name", "") for a in b.get("authors") or [])[:80], "year": ""})
        nxt = (d or {}).get("next")
        if not nxt:
            break
        time.sleep(1)
    return rows


def _charts() -> dict:
    out = {}
    for key, (label, url, _, _) in CHARTS.items():
        try:
            rows = (_itunes if "itunes" in key
                    else _openlibrary if key == "openlibrary" else _gutenberg)(url)
        except Exception as e:
            log(f"      {label}: {e}")
            rows = []
        if rows:
            out[key] = rows
        else:
            log(f"      {label}: nothing today")
            radar.HEALTH.setdefault("sources_off", []).append(label)
    return out


# ---------- Steam ----------

def _steam_ids(watch: dict) -> dict[str, str]:
    """{qid: steam app id} for watched games; cached for a week."""
    path = os.path.join(radar.CACHE, "steam_ids.json")
    try:
        if time.time() - os.path.getmtime(path) < 7 * 86400:
            with open(path) as f:
                return json.load(f)
    except OSError:
        pass
    games = [w["qid"] for w in watch.values() if w.get("kind") == "video game"]
    out = {}
    for i in range(0, len(games), 300):
        values = " ".join(f"wd:{q}" for q in games[i:i + 300])
        try:
            rows = radar.sparql(f"SELECT ?item ?app WHERE {{ VALUES ?item {{ {values} }} ?item wdt:P1733 ?app . }}")
        except Exception as e:
            log(f"      Steam ID lookup failed for a batch: {e}")
            continue
        for r in rows:
            out.setdefault(radar.qid(radar.v(r, "item")), radar.v(r, "app"))
    if out:
        with open(path, "w") as f:
            json.dump(out, f)
    return out


def _steam(apps: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    """Current players, and total reviews (new reviews a day come from the day-to-day change)."""
    players, reviews = {}, {}
    rev = _Breaker("Steam reviews")

    def one(app):
        n = r = None
        try:
            n = (_fetch(STEAM_PLAYERS.format(app)).get("response") or {}).get("player_count")
        except Exception:
            pass
        if not rev.off:
            try:
                r = (_fetch(STEAM_REVIEWS.format(app)).get("query_summary") or {}).get("total_reviews")
                rev.ok()
            except Exception as e:
                rev.fail(type(e).__name__)
        time.sleep(0.25)
        return app, n, r
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for app, n, r in ex.map(one, apps):
            if n is not None:
                players[app] = n
            if r is not None:
                reviews[app] = r
    return players, reviews


# ---------- matching chart entries to watched works ----------

def _map_ids(prop: str, ids: list[str]) -> dict[str, str]:
    out = {}
    for i in range(0, len(ids), 200):
        values = " ".join(json.dumps(x) for x in ids[i:i + 200])
        try:
            rows = radar.sparql(f"SELECT ?item ?v WHERE {{ VALUES ?v {{ {values} }} ?item wdt:{prop} ?v . }}")
        except Exception as e:
            log(f"      {prop} lookup failed: {e}")
            continue
        for r in rows:
            out[radar.v(r, "v")] = radar.qid(radar.v(r, "item"))
    return out


def _match(snap: dict, watch: dict, today_year: int) -> dict[str, dict[str, int]]:
    """{source: {qid: rank}} for chart entries that are watched (notable, older) works."""
    by_q = {w["qid"]: w for w in watch.values()}
    by_name: dict[tuple, list] = {}
    for title, w in watch.items():
        by_name.setdefault((w["kind"], _norm(title.replace("_", " "))), []).append(w)
    out = {}
    for src, rows in snap.items():
        if src not in CHARTS:
            continue                          # a source no longer used (e.g. Deezer)
        _, _, prop, kinds = CHARTS[src]
        ids = _map_ids(prop, [r["id"] for r in rows])
        got = {}
        for r in rows:
            q = ids.get(r["id"])
            cands = [] if q else [w for k in kinds for w in by_name.get((k, _norm(r["name"])), [])]
            if cands and r["year"].isdigit():
                # A title match counts only when the chart's own release year says it's an older work:
                # the same year for films (a new film often reuses an old title); for music and books,
                # no earlier than the original (reissues, compilations, new editions).
                cy = int(r["year"])
                for w in cands:
                    wy = int(w["release"][:4])
                    if cy <= today_year - 10 and (abs(cy - wy) <= 1 if w["kind"] == "film" else wy <= cy):
                        q = w["qid"]
                        break
            if q in by_q and q not in got:
                got[q] = r["rank"]
        out[src] = got
    return out


# ---------- the permanent record ----------

def _month_path(site, day: str) -> str:
    return os.path.join(site, "data", DIR, f"{day[:7]}.json")


def load(site: str, months: int = 3) -> dict:
    """Recent recorded days across monthly files: {"days": {date: day}}."""
    days = {}
    for path in sorted(glob.glob(os.path.join(site, "data", DIR, "*.json")))[-months:]:
        try:
            with open(path) as f:
                days.update(json.load(f).get("days", {}))
        except (OSError, json.JSONDecodeError):
            pass
    return {"days": days, "sources": {**{k: v[0] for k, v in CHARTS.items()},
                                      "steam": "Steam players", "steam-reviews": "Steam reviews"}}


def _migrate(site: str) -> None:
    """Fold the old single-file record (60-day window) into monthly files."""
    old = os.path.join(site, "data", "signals.json")
    if not os.path.exists(old):
        return
    try:
        with open(old) as f:
            days = json.load(f).get("days", {})
    except (OSError, json.JSONDecodeError):
        days = {}
    for d, v in days.items():
        _save_day(site, d, v)
    os.remove(old)


def _save_day(site: str, day: str, record: dict) -> None:
    path = _month_path(site, day)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path) as f:
            month = json.load(f)
    except (OSError, json.JSONDecodeError):
        month = {"days": {}}
    month["days"][day] = record
    month["days"] = dict(sorted(month["days"].items()))
    with open(path, "w") as f:
        json.dump(month, f, separators=(",", ":"))


def collect(site: str, watch: dict, today: dt.date) -> dict:
    """Take today's snapshots, add them to the permanent record, return recent history."""
    _migrate(site)
    snap = _charts()
    steam_ids = _steam_ids(watch)
    app_to_q = {}
    for q, app in steam_ids.items():
        app_to_q.setdefault(app, q)
    players, reviews = _steam(sorted(app_to_q)) if app_to_q else ({}, {})
    day = _match(snap, watch, today.year)
    if players:
        day["steam"] = {app_to_q[a]: n for a, n in players.items() if a in app_to_q}
    if reviews:
        day["steam-reviews-total"] = {app_to_q[a]: n for a, n in reviews.items() if a in app_to_q}
    # Raw top lists too (title, artist, year), so the record stands on its own.
    day["_charts"] = {src: [[r["name"], r["artist"], r["year"]] for r in rows[:100]] for src, rows in snap.items()}
    _save_day(site, today.isoformat(), day)
    log("      signals: " + ", ".join(f"{s} {len(v)}" for s, v in day.items() if not s.startswith("_")))
    return load(site)


def read(store: dict, today: dt.date) -> dict[str, list[dict]]:
    """{qid: [signal]} for today. Each signal: {source, text, strong}."""
    days = sorted(d for d in store.get("days", {}) if d <= today.isoformat())
    if not days:
        return {}
    now, past = store["days"][days[-1]], [store["days"][d] for d in days[:-1]]
    names = store.get("sources", {})
    out: dict[str, list] = {}

    def ratio_signal(q, val, hist, minimum, source, fmt):
        hist = [x for x in hist if x is not None]
        if val < minimum or len(hist) < MIN_HISTORY:
            return
        ratio = val / max(statistics.median(hist), 1)
        if ratio >= 1.5:
            out.setdefault(q, []).append({"source": source, "strong": ratio >= 2, "text": fmt(ratio, val)})

    for src, ranks in now.items():
        if src.startswith("_") or src == "steam-reviews-total":
            continue
        for q, val in ranks.items():
            if src == "steam":
                ratio_signal(q, val, [p.get("steam", {}).get(q) for p in past[-28:]], STEAM_MIN, "Steam",
                             lambda r, v: f"{r:.1f}× its usual players on Steam ({v:,} playing)")
                continue
            recent = past[-NEW_DAYS:]
            label = names.get(src, src)
            if len(recent) >= MIN_HISTORY and not any(q in p.get(src, {}) for p in recent):
                out.setdefault(q, []).append({"source": label, "strong": True, "text": f"New on {label}: #{val}"})
                continue
            before = [p[src][q] for p in recent if q in p.get(src, {})]
            if before and min(before) - val >= 25:
                out.setdefault(q, []).append({"source": label, "strong": True,
                                              "text": f"Climbing {label}: #{min(before)} → #{val}"})
            else:
                out.setdefault(q, []).append({"source": label, "strong": False, "text": f"On {label}: #{val}"})

    # Steam reviews: new reviews a day = change in the running total between recorded days.
    totals = [(d, store["days"][d].get("steam-reviews-total", {})) for d in days[-29:]]
    for q, total in now.get("steam-reviews-total", {}).items():
        series = [t.get(q) for _, t in totals]
        daily = [b - a for a, b in zip(series, series[1:]) if a is not None and b is not None]
        if len(daily) >= MIN_HISTORY + 1:
            ratio_signal(q, daily[-1], daily[:-1], REVIEWS_MIN, "Steam reviews",
                         lambda r, v: f"{r:.1f}× its usual new reviews on Steam ({v:,} yesterday)")
    return out
