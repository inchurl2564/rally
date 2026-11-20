"""
Second opinions: is an old favorite back outside Wikipedia too?

Open sources that need no API key, matched to works through Wikidata IDs:

  Steam              current players for older games (api.steampowered.com)      Wikidata P1733
  iTunes charts      top songs, albums and movies, US (itunes.apple.com RSS)    P10110 / P2281 / P6398, else title
  Open Library       daily trending books (openlibrary.org)                       P648

Charts and player counts are snapshots, so each run records one in site/data/signals.json
and compares it with the days before. That history is also published as open data.

A signal is *strong* when it shows a change, not just presence:
  Steam: players at least 2x the median of earlier days
  Charts: a new entry (absent the previous 7 recorded days) or a big climb
Strong signals can add a work to the candidates; any signal is shown on its card.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
import urllib.parse

import radar

STORE = "signals.json"
KEEP_DAYS = 60
CHARTS = {
    "itunes-songs": ("iTunes top songs", "https://itunes.apple.com/us/rss/topsongs/limit=200/json", "P10110"),
    "itunes-albums": ("iTunes top albums", "https://itunes.apple.com/us/rss/topalbums/limit=200/json", "P2281"),
    "itunes-movies": ("iTunes top movies", "https://itunes.apple.com/us/rss/topmovies/limit=200/json", "P6398"),
}
OL_TRENDING = "https://openlibrary.org/trending/daily.json?limit=1000"
STEAM = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?appid={}"
NEW_DAYS = 7          # a chart entry is "new" if absent from the previous 7 recorded days
MIN_HISTORY = 3       # days of history before "new" or "Nx usual" can be judged
STEAM_MIN = 50        # ignore games with fewer players than this


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _get(url):
    try:
        return radar.http_json(url, max_age_h=0)
    except Exception as e:
        log(f"      {urllib.parse.urlparse(url).netloc}: {e}")
        return None


def _norm(s: str) -> str:
    s = re.sub(r"\s*[\(\[].*?[\)\]]", "", s or "")          # (Remastered), [2022 Mix], (1987)
    s = re.sub(r"^(dr\. seuss' |disney's |bram stoker's )", "", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------- snapshots ----------

def _charts() -> dict:
    out = {}
    for key, (_, url, _) in CHARTS.items():
        d = _get(url)
        entries = ((d or {}).get("feed") or {}).get("entry") or []
        rows = []
        for i, e in enumerate(entries, 1):
            href = e["id"]["label"]
            m = re.search(r"\?i=(\d+)", href)
            album = re.search(r"/(?:id)?(\d+)(?:\?|$)", href.split("?i=")[0] + "?")
            rows.append({"rank": i, "id": m.group(1) if m else e["id"]["attributes"]["im:id"],
                         "album": album.group(1) if album else None,
                         "name": e["im:name"]["label"], "artist": (e.get("im:artist") or {}).get("label"),
                         "year": (e.get("im:releaseDate") or {}).get("label", "")[:4]})
        if rows:
            out[key] = rows
    d = _get(OL_TRENDING)
    rows = [{"rank": i, "id": w["key"].rsplit("/", 1)[-1], "name": w.get("title"),
             "artist": ", ".join(w.get("author_name") or [])[:80], "year": str(w.get("first_publish_year") or "")}
            for i, w in enumerate((d or {}).get("works") or [], 1)]
    if rows:
        out["openlibrary"] = rows
    return out


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


def _steam(ids: dict[str, str]) -> dict[str, int]:
    def one(app):
        d = _get(STEAM.format(app))
        time.sleep(0.2)
        return app, ((d or {}).get("response") or {}).get("player_count")
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        return {app: n for app, n in ex.map(one, sorted(set(ids.values()))) if n is not None}


# ---------- matching chart entries to works ----------

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


KIND_FOR = {"itunes-songs": {"song"}, "itunes-albums": {"album"}, "itunes-movies": {"film"},
            "openlibrary": {"book", "manga/comic"}}


def _match(snap: dict, watch: dict, today_year: int) -> dict[str, dict[str, int]]:
    """{source: {qid: rank}} for chart entries that are watched (notable, older) works."""
    by_q = {w["qid"]: w for w in watch.values()}
    by_name: dict[tuple, list] = {}
    for title, w in watch.items():
        by_name.setdefault((w["kind"], _norm(title.replace("_", " "))), []).append(w)
    out = {}
    for src, rows in snap.items():
        if src == "steam":
            continue
        prop = CHARTS.get(src, (None, None, "P648"))[2]
        ids = _map_ids(prop, [r["id"] for r in rows])
        got = {}
        for r in rows:
            q = ids.get(r["id"])
            if not q and r["year"].isdigit():
                # Fall back to an exact title match within the right medium, only when the chart's own
                # release year says it's an older work: the same year for films (a new film often reuses
                # an old title); for music, no earlier than the original (reissues and compilations).
                cy = int(r["year"])
                for kind in KIND_FOR[src]:
                    for w in by_name.get((kind, _norm(r["name"])), []):
                        wy = int(w["release"][:4])
                        if cy <= today_year - 10 and (abs(cy - wy) <= 1 if kind == "film" else wy <= cy):
                            q = w["qid"]
                            break
                    if q:
                        break
            if q in by_q and q not in got:
                got[q] = r["rank"]
        out[src] = got
    return out


# ---------- the daily record and what it says ----------

def collect(site: str, watch: dict, today: dt.date) -> dict:
    """Take today's snapshots, add them to the published record, return the record."""
    path = os.path.join(site, "data", STORE)
    try:
        with open(path) as f:
            store = json.load(f)
    except (OSError, json.JSONDecodeError):
        store = {"days": {}}
    snap = _charts()
    steam_ids = _steam_ids(watch)
    steam = _steam(steam_ids) if steam_ids else {}
    matched = _match(snap, watch, today.year)
    app_to_q = {}
    for q, app in steam_ids.items():
        app_to_q.setdefault(app, q)
    day = {src: ranks for src, ranks in matched.items()}
    if steam:
        day["steam"] = {app_to_q[a]: n for a, n in steam.items() if a in app_to_q}
    day["_charts"] = {src: [r["name"] for r in rows[:100]] for src, rows in snap.items()}   # raw top lists, for context
    store["days"][today.isoformat()] = day
    for d in sorted(store["days"])[:-KEEP_DAYS]:
        del store["days"][d]
    store["sources"] = {**{k: v[0] for k, v in CHARTS.items()}, "openlibrary": "Open Library trending",
                        "steam": "Steam players"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(store, f, separators=(",", ":"))
    log(f"      signals: " + ", ".join(f"{s} {len(v)}" for s, v in day.items() if not s.startswith("_")))
    return store


def read(store: dict, today: dt.date) -> dict[str, list[dict]]:
    """{qid: [signal]} for today. Each signal: {source, text, strong}."""
    days = sorted(d for d in store.get("days", {}) if d <= today.isoformat())
    if not days:
        return {}
    now, past = store["days"][days[-1]], [store["days"][d] for d in days[:-1]]
    names = store.get("sources", {})
    out: dict[str, list] = {}
    for src, ranks in now.items():
        if src.startswith("_"):
            continue
        for q, val in ranks.items():
            if src == "steam":
                hist = [p.get("steam", {}).get(q) for p in past[-28:]]
                hist = [x for x in hist if x]
                if val < STEAM_MIN:
                    continue
                if len(hist) >= MIN_HISTORY:
                    ratio = val / max(statistics.median(hist), 1)
                    if ratio >= 1.5:
                        out.setdefault(q, []).append({"source": "Steam", "strong": ratio >= 2,
                                                      "text": f"{ratio:.1f}× its usual players on Steam ({val:,} playing)"})
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
    return out
