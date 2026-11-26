#!/usr/bin/env python3
"""
The Rallyback (the comeback report): find old pop-culture works that are suddenly getting attention
again, and guess why.

Uses only open, unrestricted sources:
  * Wikimedia Pageviews API (wikimedia.org)  - daily attention, CC0
  * Wikidata SPARQL (query.wikidata.org)     - what each page is about,
                                               release dates, people, sequels, CC0

Pipeline
  1. Discover: pull Wikipedia's daily top-1000 articles for the last N days.
  2. Classify: map titles to Wikidata items, keep creative works (films, songs,
     albums, TV series, games, books, ...) released at least MIN_AGE years ago.
  3. Measure: fetch ~13 months of daily views per work, compare the recent
     window against a long-run baseline, find when the spike started.
  4. Explain: look for likely triggers in Wikidata around the spike start:
       - a death of someone credited on the work
       - a new derivative work (sequel, remake, adaptation, same series)
       - a new release by the same artist / director / author
       - a round-number anniversary
     Spikes with no trigger found are flagged "unexplained"; those are often
     the most interesting (memes, TV/ad sync placements, viral clips).
  5. Report: JSON + a self-contained HTML report with sparklines.

Only the Python standard library is used.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import json
import math
import re
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Run as a script, this file is "__main__"; the modules it loads do `import radar`. Make that
# the same module, so what they record (sources switched off, failed lookups) lands in the
# one HEALTH record that's saved with the edition, instead of in a second copy that's lost.
if __name__ == "__main__":
    sys.modules.setdefault("radar", sys.modules[__name__])

_contact = os.environ.get("RADAR_CONTACT") or (
    f"https://github.com/{os.environ['GITHUB_REPOSITORY']}" if os.environ.get("GITHUB_REPOSITORY") else "")
UA = f"Rallyback/0.4 ({_contact or 'open-data prototype'}; python-urllib)"
HEALTH = {"pages_skipped": 0, "lookups_failed": 0, "requests": 0}
PV = "https://wikimedia.org/api/rest_v1/metrics/pageviews"
SPARQL = "https://query.wikidata.org/sparql"

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")

# Wikidata classes counted as "creative works" (matched on P31 directly;
# subclass walking is too slow for large batches).
WORK_CLASSES = {
    "Q11424": "film", "Q24869": "film", "Q202866": "film", "Q506240": "film",
    "Q24862": "film", "Q29168811": "film",
    "Q5398426": "TV series", "Q581714": "TV series", "Q1259759": "TV series",
    "Q63952888": "TV series", "Q526877": "TV series", "Q117467246": "TV series",
    "Q7366": "song", "Q134556": "song", "Q105543609": "song",
    "Q482994": "album", "Q208569": "album", "Q169930": "album", "Q209939": "album",
    "Q7889": "video game",
    "Q7725634": "book", "Q8261": "book", "Q47461344": "book", "Q571": "book",
    "Q21198342": "manga/comic", "Q1004": "manga/comic", "Q14406742": "manga/comic",
    "Q2031291": "musical", "Q2743": "musical",
}

# Credits whose holders we check for deaths, with a rough "how strong a link" weight.
CREDIT_PROPS = {
    "P175": ("performer", 3), "P50": ("author", 3), "P57": ("director", 3),
    "P170": ("creator", 3), "P86": ("composer", 2), "P676": ("lyricist", 2),
    "P162": ("producer", 1), "P58": ("screenwriter", 2), "P161": ("cast member", 1),
    "P725": ("voice actor", 1), "P1431": ("executive producer", 1),
}
# Credits used to look for "new release by same creator".
SAME_CREATOR_PROPS = ["P175", "P50", "P57", "P170"]

ANNIVERSARIES = {10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100}

NAMESPACE_PREFIXES = (
    "Special:", "Wikipedia:", "File:", "Portal:", "Help:", "Category:",
    "Template:", "Talk:", "User:", "Draft:", "Module:", "MediaWiki:",
)


# --------------------------------------------------------------------------- #
# HTTP with a tiny disk cache
# --------------------------------------------------------------------------- #

def _cache_path(key: str) -> str:
    return os.path.join(CACHE, hashlib.sha1(key.encode()).hexdigest() + ".json")


def http_json(url: str, data: bytes | None = None, cache_key: str | None = None,
              max_age_h: float = 12, retries: int = 6):
    key = cache_key or url + (data.decode() if data else "")
    path = _cache_path(key)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age_h * 3600:
        with open(path) as f:
            return json.load(f)
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers["Accept"] = "application/sparql-results+json"
    for attempt in range(retries):
        try:
            HEALTH["requests"] += 1
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as r:
                out = json.load(r)
            os.makedirs(CACHE, exist_ok=True)
            with open(path, "w") as f:
                json.dump(out, f)
            return out
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(wait) if wait and wait.isdigit() else 2 ** attempt * 3)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            raise


def sparql(query: str):
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    res = http_json(SPARQL, data=body, max_age_h=24, retries=2)
    return res["results"]["bindings"] if res else []


def v(row, k):
    return row[k]["value"] if k in row else None


def nice_label(label: str | None, title: str | None = None) -> str:
    """Wikidata returns the bare QID when an item has no label in the requested languages."""
    if label and not (label[0] == "Q" and label[1:].isdigit()):
        return label
    return title.replace("_", " ") if title else (label or "?")


def qid(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


# --------------------------------------------------------------------------- #
# Step 1: discovery from Wikipedia top lists
# --------------------------------------------------------------------------- #

def latest_available_day(project: str) -> dt.date:
    d = dt.date.today() - dt.timedelta(days=1)
    for _ in range(5):
        url = f"{PV}/top/{project}/all-access/{d:%Y/%m/%d}"
        if http_json(url, max_age_h=6):
            return d
        d -= dt.timedelta(days=1)
    raise SystemExit("Could not find recent top-articles data.")


def discover(project: str, end: dt.date, days: int) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for i in range(days):
        d = end - dt.timedelta(days=i)
        res = http_json(f"{PV}/top/{project}/all-access/{d:%Y/%m/%d}", max_age_h=24 * 30)
        if not res:
            continue
        for a in res["items"][0]["articles"]:
            t = a["article"]
            if t in ("Main_Page", "-") or t.startswith(NAMESPACE_PREFIXES):
                continue
            s = seen.setdefault(t, {"days_in_top": 0, "best_rank": 10**6})
            s["days_in_top"] += 1
            s["best_rank"] = min(s["best_rank"], a["rank"])
    return seen


# --------------------------------------------------------------------------- #
# Step 2: classify via Wikidata
# --------------------------------------------------------------------------- #

def wiki_iri(project: str, title: str) -> str:
    lang = project.split(".")[0]
    # Matches MediaWiki's wfUrlencode, which is how Wikidata stores sitelink IRIs.
    return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title, safe=";@$!*(),/~:")


def classify(project: str, titles: list[str], min_age: int, today: dt.date) -> list[dict]:
    classes = " ".join(f"wd:{c}" for c in WORK_CLASSES)
    by_iri = {wiki_iri(project, t): t for t in titles}
    iris = list(by_iri)
    works: dict[str, dict] = {}
    for i in range(0, len(iris), 150):
        chunk = " ".join(f"<{u}>" for u in iris[i:i + 150])
        q = f"""
        SELECT ?article ?item ?itemLabel ?class ?date ?prec WHERE {{
          VALUES ?article {{ {chunk} }}
          VALUES ?class {{ {classes} }}
          ?article schema:about ?item .
          ?item wdt:P31 ?class .
          OPTIONAL {{ ?item p:P577/psv:P577 [ wikibase:timeValue ?date; wikibase:timePrecision ?prec ] }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        for row in sparql(q):
            title = by_iri.get(v(row, "article"))
            if not title:
                continue
            item = qid(v(row, "item"))
            w = works.setdefault(item, {
                "qid": item, "title": title, "label": nice_label(v(row, "itemLabel"), title),
                "kind": WORK_CLASSES[qid(v(row, "class"))], "release": None, "release_prec": 0,
            })
            date, prec = v(row, "date"), int(v(row, "prec") or 0)
            if date and not date.startswith("-"):
                try:
                    d = dt.date.fromisoformat(date[:10])
                except ValueError:  # e.g. 1999-00-00 for year-precision dates
                    d = dt.date(int(date[:4]), 1, 1)
                if w["release"] is None or d < w["release"]:
                    w["release"], w["release_prec"] = d, prec
    cutoff = today.replace(year=today.year - min_age)
    return [w for w in works.values() if w["release"] and w["release"] <= cutoff]


# --------------------------------------------------------------------------- #
# Step 3: measure the spike
# --------------------------------------------------------------------------- #

HISTORY = os.path.join(CACHE, "history")


def prune_cache(days: int) -> None:
    """Drop stale API responses (not history, bulk days or the watchlist) to keep the CI cache small."""
    if not os.path.isdir(CACHE):
        return
    cutoff = time.time() - days * 86400
    for f in os.listdir(CACHE):
        path = os.path.join(CACHE, f)
        if f.endswith(".json") and len(f) == 45 and os.path.getmtime(path) < cutoff:
            os.remove(path)


def history_views(project: str, title: str, start: dt.date, end: dt.date) -> dict[dt.date, int]:
    """Daily all-access views, stored per article so later runs only fetch the new days."""
    os.makedirs(HISTORY, exist_ok=True)
    path = os.path.join(HISTORY, hashlib.sha1(f"{project}|{title}".encode()).hexdigest() + ".json")
    rec = None
    if os.path.exists(path):
        with open(path) as f:
            rec = json.load(f)
    if rec and rec["from"] <= start.isoformat():
        through = dt.date.fromisoformat(rec["through"])
        if through >= end:
            fetched = {}
        else:
            fetched = daily_views(project, title, through + dt.timedelta(days=1), end, cache=False)
            if fetched is None:
                return None
        views = {**{dt.date.fromisoformat(k): val for k, val in rec["views"].items()}, **fetched}
    else:
        views = daily_views(project, title, start, end, cache=False)
        if views is None:
            return None
    keep = {d: n for d, n in views.items() if d >= end - dt.timedelta(days=800)}
    covered_from = rec["from"] if rec and rec["from"] <= start.isoformat() else start.isoformat()
    covered_through = max(end.isoformat(), rec["through"] if rec else "")
    with open(path, "w") as f:
        json.dump({"from": covered_from, "through": covered_through,
                   "views": {d.isoformat(): n for d, n in keep.items()}}, f)
    return views


def daily_views(project: str, title: str, start: dt.date, end: dt.date,
                access: str = "all-access", cache: bool = True) -> dict[dt.date, int] | None:
    t = urllib.parse.quote(title, safe="")
    url = f"{PV}/per-article/{project}/{access}/user/{t}/daily/{start:%Y%m%d}00/{end:%Y%m%d}00"
    try:
        res = http_json(url, max_age_h=24 if cache else 0)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"      skipped {title}: {e}", file=sys.stderr)
        HEALTH["pages_skipped"] += 1
        return None
    time.sleep(0.15)  # stay well under Wikimedia's per-client rate limit
    out = {}
    for it in (res or {}).get("items", []):
        out[dt.datetime.strptime(it["timestamp"][:8], "%Y%m%d").date()] = it["views"]
    return out


def measure(series: dict[dt.date, int], end: dt.date, recent_days: int) -> dict | None:
    days = [end - dt.timedelta(days=i) for i in range(400)][::-1]
    vals = [series.get(d, 0) for d in days]
    recent = vals[-recent_days:]
    base_window = vals[: -(recent_days + 45)]          # skip the run-up before the window
    base_window = [x for x in base_window if x > 0]
    if len(base_window) < 60:
        return None                                     # page too new to have a baseline
    baseline = max(statistics.median(base_window), 1.0)
    peak = max(recent)
    peak_day = days[len(days) - recent_days + recent.index(peak)]
    recent_mean = sum(recent) / len(recent)
    # Walk back from the peak to find where views first rose above 2x baseline.
    i = days.index(peak_day)
    while i > 0 and vals[i - 1] > 2 * baseline and (days.index(peak_day) - i) < 90:
        i -= 1
    last7 = vals[-7:]
    last3 = sum(vals[-3:]) / 3
    start = days[i]
    if start >= end - dt.timedelta(days=4):
        stage = "emerging"
    elif last3 < 0.5 * peak:
        stage = "fading"
    elif sum(x > 2 * baseline for x in last7) >= 5 and start <= end - dt.timedelta(days=10):
        stage = "sustained"
    else:
        stage = "peaking"
    return {
        "lift3": round(last3 / baseline, 1),
        "stage": stage,
        "baseline": round(baseline),
        "recent_mean": round(recent_mean),
        "peak": peak,
        "peak_day": peak_day,
        "spike_start": days[i],
        "lift": round(recent_mean / baseline, 1),
        "peak_lift": round(peak / baseline, 1),
        "still_elevated": sum(x > 2 * baseline for x in last7) >= 5,
        "spark": vals,
        "spark_start": days[0],
    }


def sanity_checks(project: str, w: dict, end: dt.date, recent_days: int) -> None:
    """Two checks that stop false 'revivals':
    - seasonal: was the same calendar window last year also well above baseline?
    - automated: is the spike almost all desktop traffic? Human surges are mostly mobile."""
    s0 = end - dt.timedelta(days=recent_days - 1)
    ly = daily_views(project, w["title"], s0.replace(year=s0.year - 1) - dt.timedelta(days=7),
                     end.replace(year=end.year - 1) + dt.timedelta(days=7))
    ly = ly or {}
    ly_mean = sum(ly.values()) / max(len(ly), 1)
    w["last_year_lift"] = round(ly_mean / w["baseline"], 1)
    desk = daily_views(project, w["title"], s0, end, access="desktop")
    total = sum(w["spark"][-recent_days:])
    w["desktop_share"] = round(sum(desk.values()) / total, 2) if total and desk is not None else None


# --------------------------------------------------------------------------- #
# Step 4: explain - look for triggers in Wikidata
# --------------------------------------------------------------------------- #

TRIGGER_TYPES = {"deaths": "death", "derivatives": "derivative", "same-creator": "same-creator",
                 "honors": "honor", "public domain": "public domain"}


def find_triggers(works: list[dict], since: dt.date, batch: int = 12, retry_batch: int = 3,
                  retry_pause: float = 20) -> None:
    for w in works:
        w["triggers"] = []
    lookups = (("deaths", _deaths), ("derivatives", _derivatives), ("same-creator", _same_creator),
               ("honors", _honors), ("public domain", _public_domain_people))
    failed = []
    for i in range(0, len(works), batch):
        chunk = works[i:i + batch]
        for name, fn in lookups:
            try:
                fn(chunk, since)
            except Exception as e:  # Wikidata's 60s query limit; don't let one batch sink the run
                print(f"      {name} lookup failed for a batch: {e}", file=sys.stderr)
                failed.append((name, fn, chunk))
    # Second try for failed batches, in smaller pieces (smaller queries finish inside the limit).
    if failed:
        time.sleep(retry_pause)
    for name, fn, chunk in failed:
        for j in range(0, len(chunk), retry_batch):
            part = chunk[j:j + retry_batch]
            try:
                fn(part, since)
                print(f"      {name} retry worked for {len(part)} titles", file=sys.stderr)
            except Exception as e:
                print(f"      {name} retry failed for {len(part)} titles: {e}", file=sys.stderr)
                HEALTH["lookups_failed"] += 1
                for w in part:
                    w.setdefault("lookup_failed", []).append(name)


def carry_over_triggers(works: list[dict], editions: list[list[dict]]) -> int:
    """A lookup that failed twice keeps the triggers of that kind from the latest earlier edition that had
    them for the same comeback (same spike start), so a bad night on Wikidata doesn't wipe a known reason.
    `editions`: earlier editions' results, newest first."""
    n = 0
    for w in works:
        if not w.get("lookup_failed"):
            continue
        kinds = {TRIGGER_TYPES[x] for x in w["lookup_failed"]}
        for results in editions:
            p = next((r for r in results or [] if r.get("qid") == w["qid"]), None)
            if not p or str(p.get("spike_start")) != str(w["spike_start"]):
                continue
            old = [t for t in p.get("triggers") or [] if t.get("type") in kinds]
            for t in old:
                text = re.sub(r" \((upcoming|attention rose before release)\)$", "", t.get("text", ""))
                w["triggers"].append({k: val for k, val in t.items() if k != "lead_days"} | {"text": text})
                n += 1
            if old:
                break
    return n


def _prep(works, since):
    values = " ".join(f"wd:{w['qid']}" for w in works)
    by_q = {w["qid"]: w for w in works}
    lit = f'"{since.isoformat()}T00:00:00Z"^^xsd:dateTime'
    return values, by_q, lit


def _deaths(works, since):
    values, by_q, lit = _prep(works, since)
    # (a) deaths of credited people
    props = " ".join(f"wdt:{p}" for p in CREDIT_PROPS)
    q = f"""
    SELECT ?item ?prop ?person ?personLabel ?died WHERE {{
      VALUES ?item {{ {values} }}
      VALUES ?prop {{ {props} }}
      ?item ?prop ?person .
      ?person wdt:P570 ?died .
      FILTER(?died >= {lit})
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }}"""
    for row in sparql(q):
        w = by_q[qid(v(row, "item"))]
        role, weight = CREDIT_PROPS[qid(v(row, "prop"))]
        w["triggers"].append({
            "type": "death", "date": v(row, "died")[:10], "weight": weight,
            "text": f"{v(row, 'personLabel')} ({role}) died",
            "qid": qid(v(row, "person")),
        })



def _derivatives(works, since):
    values, by_q, lit = _prep(works, since)
    # (b) new derivative works. One small query per relationship: a single big UNION
    # runs close to Wikidata's 60-second limit.
    patterns = {
        "adaptation/based on it": "?new wdt:P144 ?item .",
        "sequel": "?new wdt:P155 ?item .",
        "derivative work": "?item wdt:P4969 ?new .",
        "remake/new version": "?new wdt:P5059 ?item .",
        "new entry in same series": "?item wdt:P179 ?s . ?new wdt:P179 ?s . FILTER(?new != ?item)",
        "new entry in the franchise": "?item wdt:P8345 ?f . ?new wdt:P8345 ?f . FILTER(?new != ?item)",
        "new adaptation of the same source": "?item wdt:P144 ?src . ?new wdt:P144 ?src . FILTER(?new != ?item)",
        "follow-up": "?item wdt:P156 ?new .",
        "adaptation of part of it": "?part wdt:P179|wdt:P361 ?item . ?new wdt:P144 ?part .",
    }
    for rel, pat in patterns.items():
        q = f"""
        SELECT DISTINCT ?item ?new ?newLabel ?date WHERE {{
          VALUES ?item {{ {values} }}
          {pat}
          ?new wdt:P577 ?date .
          FILTER(?date >= {lit})
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        for row in sparql(q):
            w = by_q[qid(v(row, "item"))]
            w["triggers"].append({
                "type": "derivative", "date": v(row, "date")[:10], "weight": 3,
                "text": f"{rel}: {v(row, 'newLabel')}", "qid": qid(v(row, "new")),
            })


def _same_creator(works, since):
    values, by_q, lit = _prep(works, since)
    # (c) new release by the same artist / author / director
    props = " ".join(f"wdt:{p}" for p in SAME_CREATOR_PROPS)
    q = f"""
    SELECT DISTINCT ?item ?c ?cLabel ?new ?newLabel ?date ?who WHERE {{
      VALUES ?item {{ {values} }}
      VALUES ?prop {{ {props} }}
      ?item ?prop ?c .
      FILTER(?c != wd:Q3108914)          # "various artists" is not a real creator link
      ?new ?prop ?c .
      FILTER(?new != ?item)
      ?new wdt:P577 ?date .
      FILTER(?date >= {lit})
      # A person or a band, whose photo can lead the story (not a studio or publisher).
      BIND(EXISTS {{ VALUES ?pt {{ wd:Q5 wd:Q215380 wd:Q5741069 wd:Q9212979 }} ?c wdt:P31 ?pt }} AS ?who)
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }} LIMIT 2000"""
    for row in sparql(q):
        w = by_q[qid(v(row, "item"))]
        w["triggers"].append({
            "type": "same-creator", "date": v(row, "date")[:10], "weight": 2,
            "text": f"new work by {v(row, 'cLabel')}: {v(row, 'newLabel')}",
            "qid": qid(v(row, "new")),
            "person": qid(v(row, "c")) if v(row, "who") == "true" else None,   # the creator, for their photo
        })


# Registries and halls of fame Wikidata records as "part of" with a start date, not as an award.
REGISTRIES = {"Q823422": "National Film Registry", "Q253299": "National Recording Registry"}
# Honors to a credited person that send people back to their work (a career award, an induction).
# Everyday awards (a film festival prize for a new film) are left out.
PERSON_HONOR = re.compile(r"hall of fame|kennedy center honors|lifetime achievement|honorary|presidential medal|"
                          r"nobel prize|national medal of arts|polar music prize|afi life|bafta fellowship|"
                          r"cecil b\. demille|irving g\. thalberg|gershwin prize|pulitzer prize", re.I)
HONOR_PEOPLE = ["P175", "P50", "P57", "P170", "P86", "P676"]
# Honors Wikidata often dates only to the year, with the month they're always announced in.
HONOR_MONTH = [(re.compile(r"^Nobel Prize", re.I), 10), (re.compile(r"Kennedy Center Honors", re.I), 12),
               (re.compile(r"^Pulitzer Prize", re.I), 5), (re.compile(r"Rock and Roll Hall of Fame", re.I), 4)]


def _honor_date(date: str, prec: int, label: str) -> tuple[str, bool]:
    """(date, approximate?) for an honor: a year-only date moves to the honor's usual month."""
    if prec >= 10:
        return date[:10], False
    for rx, month in HONOR_MONTH:
        if rx.search(label):
            return f"{date[:4]}-{month:02d}-01", True
    return date[:10], True


def _honors(works, since):
    """Awards and designations dated near the comeback: the work joining the National Film
    Registry or the Grammy Hall of Fame, or someone behind it getting a career honor. Many are
    dated only to the year (Wikidata stores 1 January), so those are marked approximate."""
    values, by_q, _ = _prep(works, since)
    lit = f'"{(since - dt.timedelta(days=400)).isoformat()}T00:00:00Z"^^xsd:dateTime'
    regs = " ".join(f"wd:{q}" for q in REGISTRIES)
    q = f"""
    SELECT DISTINCT ?item ?h ?hLabel ?date ?prec ?how WHERE {{
      VALUES ?item {{ {values} }}
      {{ ?item p:P166 ?st . ?st ps:P166 ?h . ?st pqv:P585 [ wikibase:timeValue ?date; wikibase:timePrecision ?prec ] . BIND("received" AS ?how) }}
      UNION {{ ?item p:P1435 ?st . ?st ps:P1435 ?h . ?st pqv:P580 [ wikibase:timeValue ?date; wikibase:timePrecision ?prec ] . BIND("added" AS ?how) }}
      UNION {{ VALUES ?h {{ {regs} }} ?item p:P361 ?st . ?st ps:P361 ?h . ?st pqv:P580 [ wikibase:timeValue ?date; wikibase:timePrecision ?prec ] . BIND("added" AS ?how) }}
      FILTER(?date >= {lit})
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }}"""
    for row in sparql(q):
        w = by_q[qid(v(row, "item"))]
        label = v(row, "hLabel")
        if not label or re.fullmatch(r"Q\d+", label):
            continue
        how = v(row, "how")
        if how == "received" and re.search(r"hall of fame", label, re.I):
            how = "added"
        day, approx = _honor_date(v(row, "date"), int(v(row, "prec") or 11), label)
        w["triggers"].append({
            "type": "honor", "date": day, "weight": 2,
            "text": f"{'added to the' if how == 'added' else 'received the'} {label}",
            "qid": qid(v(row, "h")), "approx": approx,
        })
    props = " ".join(f"wdt:{p}" for p in HONOR_PEOPLE)
    q = f"""
    SELECT DISTINCT ?item ?prop ?p ?pLabel ?h ?hLabel ?date ?prec WHERE {{
      VALUES ?item {{ {values} }}
      VALUES ?prop {{ {props} }}
      ?item ?prop ?p .
      ?p p:P166 ?st . ?st ps:P166 ?h . ?st pqv:P585 [ wikibase:timeValue ?date; wikibase:timePrecision ?prec ] .
      FILTER(?date >= {lit})
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }} LIMIT 2000"""
    for row in sparql(q):
        label = v(row, "hLabel") or ""
        if not PERSON_HONOR.search(label):
            continue
        w = by_q[qid(v(row, "item"))]
        role, _ = CREDIT_PROPS[qid(v(row, "prop"))]
        day, approx = _honor_date(v(row, "date"), int(v(row, "prec") or 11), label)
        w["triggers"].append({
            "type": "honor", "date": day, "weight": 2,
            "text": f"{v(row, 'pLabel')} ({role}): {label}",
            "qid": qid(v(row, "p")), "approx": approx,
        })


def _public_domain_people(works, since, year: int | None = None):
    """Public Domain Day, life + 70 rule (UK, EU and many other countries): on 1 January, the
    work of authors and composers who died 70 years earlier becomes free to use. Only looked up
    in December to mid-February, when such a comeback could start."""
    today = dt.date.today()
    if year is None:
        if today.month not in (12, 1, 2):
            return
        year = today.year + (1 if today.month == 12 else 0)    # the 1 January in question
    values, by_q, _ = _prep(works, since)
    q = f"""
    SELECT DISTINCT ?item ?prop ?p ?pLabel ?died WHERE {{
      VALUES ?item {{ {values} }}
      VALUES ?prop {{ wdt:P50 wdt:P86 wdt:P676 }}
      ?item ?prop ?p .
      ?p wdt:P570 ?died .
      FILTER(YEAR(?died) = {year - 71})
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }}"""
    for row in sparql(q):
        w = by_q[qid(v(row, "item"))]
        role, _ = CREDIT_PROPS[qid(v(row, "prop"))]
        w["triggers"].append({
            "type": "public domain", "date": f"{year}-01-01", "weight": 3,
            "text": f"entered the public domain in the UK, EU and elsewhere: {v(row, 'pLabel')} ({role}) died in {year - 71}",
            "qid": qid(v(row, "p")),
        })


def _public_domain_us(w: dict) -> dict | None:
    """US rule: published works enter the public domain on 1 January, 95 years after the year of
    publication (sound recordings: 100 years)."""
    r = w.get("release")
    if not r or (w.get("release_prec") or 0) < 9:
        return None
    years = 100 if w.get("kind") in ("song", "album") else 95
    day = dt.date(r.year + years + 1, 1, 1)
    return {"type": "public domain", "date": day.isoformat(), "weight": 3, "qid": None,
            "text": f"entered the US public domain ({'recorded' if years == 100 else 'published'} in {r.year}, {years} years ago)"}


def annotate(w: dict) -> None:
    """Keep triggers that land near the spike start; add anniversaries; pick a verdict."""
    s = w["spike_start"]
    near = []
    for t in w.get("triggers", []):
        try:
            d = dt.date.fromisoformat(t["date"])
        except ValueError:
            continue
        lead = (s - d).days          # trigger N days before spike start
        # A date known only to the year is stored as 1 January: the event could be weeks earlier
        # (the National Film Registry is announced in mid-December), so allow more lead-in.
        if -3 <= lead <= 45 or (t.get("approx") and -45 <= lead < -3):
            t["lead_days"] = lead
            near.append(t)
        elif t["type"] in ("derivative", "same-creator") and -45 <= lead < -3:
            # attention building ahead of a release
            t["lead_days"] = lead
            t["text"] += " (upcoming)" if d > w["window_end"] else " (attention rose before release)"
            near.append(t)
    # Public Domain Day (US rule), from the release year
    pd = _public_domain_us(w)
    if pd:
        lead = (s - dt.date.fromisoformat(pd["date"])).days
        if -10 <= lead <= 45:
            near.append({**pd, "lead_days": lead})
    # anniversaries (only if we know the release day, precision 11 = day)
    r = w["release"]
    if w["release_prec"] >= 11:
        for years in ANNIVERSARIES:
            try:
                ann = r.replace(year=r.year + years)
            except ValueError:
                continue
            if -10 <= (s - ann).days <= 21 or abs((w["peak_day"] - ann).days) <= 7:
                near.append({"type": "anniversary", "date": ann.isoformat(), "weight": 2,
                             "text": f"{years}th anniversary of release",
                             "lead_days": (s - ann).days})
    # de-duplicate and rank: strongest link first, then closest in time
    uniq = {}
    for t in near:
        uniq.setdefault((t["type"], t["text"]), t)
    near = sorted(uniq.values(), key=lambda t: (-t["weight"], abs(t["lead_days"])))
    w["triggers"] = near[:5]
    if not near and w.get("lookup_failed"):
        w["verdict"] = "lookup failed"
    elif not near:
        w["verdict"] = "unexplained"
    elif near[0]["weight"] >= 2:
        w["verdict"] = near[0]["type"]
    else:
        w["verdict"] = "weak link"


def common_threads(works: list[dict], window: int = 7, batch: int = 25) -> list[dict]:
    """Among spikes with no explanation, find people credited on several of them whose
    spikes began within a few days of each other. Wikidata may not say what happened,
    but a shared person plus shared timing points at an event."""
    if len(works) < 2:
        return []
    props = " ".join(f"wdt:{p}" for p in CREDIT_PROPS)
    people: dict[str, dict] = {}
    for i in range(0, len(works), batch):
        chunk = works[i:i + batch]
        values = " ".join(f"wd:{w['qid']}" for w in chunk)
        by_q = {w["qid"]: w for w in chunk}
        q = f"""
        SELECT DISTINCT ?item ?prop ?person ?personLabel ?pa WHERE {{
          VALUES ?item {{ {values} }}
          VALUES ?prop {{ {props} }}
          ?item ?prop ?person .
          ?person wdt:P31 wd:Q5 .
          OPTIONAL {{ ?pa schema:about ?person; schema:isPartOf <https://en.wikipedia.org/> . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        try:
            rows = sparql(q)
        except Exception as e:
            print(f"      credits lookup failed for a batch: {e}", file=sys.stderr)
            HEALTH["lookups_failed"] += 1
            continue
        for row in rows:
            pq = qid(v(row, "person"))
            pa = v(row, "pa")
            g = people.setdefault(pq, {"qid": pq, "name": nice_label(v(row, "personLabel")), "works": {},
                                       "title": urllib.parse.unquote(pa.split("/wiki/", 1)[1]) if pa else None})
            g["works"][qid(v(row, "item"))] = (by_q[qid(v(row, "item"))], CREDIT_PROPS[qid(v(row, "prop"))][0])
    threads = []
    for g in people.values():
        if len(g["works"]) < 2:
            continue
        starts = sorted(w["spike_start"] for w, _ in g["works"].values())
        mid = starts[len(starts) // 2]
        hits = [(w, role) for w, role in g["works"].values() if abs((w["spike_start"] - mid).days) <= window]
        if len(hits) >= 2:
            threads.append({"qid": g["qid"], "name": g["name"], "around": mid, "title": g["title"],
                            "works": sorted(hits, key=lambda h: h[0]["spike_start"])})
    threads.sort(key=lambda t: -len(t["works"]))
    # Big casts make chance overlaps: keep a work in only its strongest thread.
    used, out = set(), []
    for t in threads:
        fresh = [h for h in t["works"] if h[0]["qid"] not in used]
        if len(fresh) >= 2:
            t["works"] = fresh
            used.update(h[0]["qid"] for h in fresh)
            out.append(t)
            for w, role in fresh:
                w["verdict"] = "common thread"
                w["triggers"].insert(0, {"type": "common thread", "date": t["around"].isoformat(),
                                         "weight": 2, "lead_days": 0, "qid": t["qid"],
                                         "text": f"{t['name']} ({role}) is credited on {len(fresh)} works "
                                                 f"that all started spiking around {t['around']}"})
    return out


# --------------------------------------------------------------------------- #
# Step 5: report
# --------------------------------------------------------------------------- #

def sparkline(vals: list[int], baseline: float, width=260, height=46) -> str:
    vals = vals[-365:]
    top = max(max(vals), baseline * 2, 1)
    lg = lambda x: math.log10(1 + x)
    n = len(vals)
    pts = " ".join(f"{i * width / (n - 1):.1f},{height - lg(x) / lg(top) * (height - 2):.1f}"
                   for i, x in enumerate(vals))
    by = height - lg(baseline) / lg(top) * (height - 2)
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" aria-label="Daily views, last 12 months, log scale">'
            f'<line x1="0" x2="{width}" y1="{by:.1f}" y2="{by:.1f}" class="base"/>'
            f'<polyline points="{pts}" class="line"/></svg>')


VERDICT_LABEL = {
    "unexplained": "No trigger found",
    "death": "Death of someone credited",
    "derivative": "New sequel/adaptation",
    "same-creator": "New work by same creator",
    "anniversary": "Anniversary",
    "public domain": "Entered the public domain",
    "honor": "An award, registry or hall of fame",
    "weak link": "Weak link only",
    "lookup failed": "Trigger lookup failed",
    "seasonal": "Seasonal (also up last year)",
    "automated?": "Likely automated traffic",
    "common thread": "Shared person, same timing",
    "coverage": "Cause suggested by news/edits",
    "ripple": "Riding a connected story",
    "editor": "Editor's note",
    "editor-release": "Editor's note: a new release",
    "editor-death": "Editor's note: a death",
    "front page": "Featured on Wikipedia's front page",
}


def slug(verdict: str) -> str:
    return verdict.replace(" ", "-").replace("?", "")


SECTIONS = [
    ("Unexplained revivals", "Big jumps with no trigger in Wikidata. These are the leads worth chasing: "
     "memes, TV or ad placements, viral clips, or events Wikidata doesn't record.", {"unexplained", "lookup failed"}),
    ("Explained revivals", "A likely trigger was found near the start of the spike.",
     {"death", "derivative", "same-creator", "anniversary", "public domain", "honor", "weak link", "common thread"}),
    ("Filtered out", "Seasonal items that were also up this time last year, and spikes that are almost all "
     "desktop traffic (real surges are mostly mobile), and one-day surges from a feature on Wikipedia's front page.",
     {"seasonal", "automated?", "front page"}),
]


def write_html(results: list[dict], meta: dict, path: str, clusters=(), threads=()) -> None:
    def esc(x):
        return html.escape(str(x))

    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    chips = " ".join(f'<span class="chip v-{slug(k)}">{esc(VERDICT_LABEL[k])}: {n}</span>'
                     for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    def card(r):
        trig = "".join(
            (f'<li><a href="https://www.wikidata.org/wiki/{esc(t["qid"])}">{esc(t["text"])}</a>'
             if t.get("qid") else f'<li>{esc(t["text"])}')
            + f' <span class="muted">{esc(t["date"])}</span></li>'
            for t in r["triggers"])
        extra = []
        if r.get("last_year_lift") is not None:
            extra.append(f"same weeks last year: {r['last_year_lift']}× baseline")
        if r.get("desktop_share") is not None:
            extra.append(f"desktop share of recent views: {round(r['desktop_share'] * 100)}%")
        return f"""
        <article class="card">
          <div class="head">
            <div>
              <h2><a href="https://{esc(meta['project'].split('.')[0])}.wikipedia.org/wiki/{esc(urllib.parse.quote(r['title']))}">{esc(r['label'] or r['title'].replace('_', ' '))}</a></h2>
              <div class="muted">{esc(r['kind'])} · released {esc(r['release'].year)} · {esc(r['age'])} yrs old</div>
            </div>
            <span class="chip v-{slug(r['verdict'])}">{esc(VERDICT_LABEL[r['verdict']])}</span>
          </div>
          <div class="body">
            <div class="spark">{sparkline(r['spark'], r['baseline'])}
              <div class="muted small">12 months, log scale · dashed = baseline</div></div>
            <dl>
              <div><dt>Lift</dt><dd>{esc(r['lift'])}×</dd></div>
              <div><dt>Peak</dt><dd>{esc(r['peak_lift'])}×</dd></div>
              <div><dt>Baseline</dt><dd>{r['baseline']:,}/day</dd></div>
              <div><dt>Spike began</dt><dd>{esc(r['spike_start'])}</dd></div>
            </dl>
          </div>
          {"<ul class='trig'>" + trig + "</ul>" if trig else "<p class='muted small'>No credited deaths, sequels, adaptations, new releases or anniversaries found near the spike in Wikidata.</p>"}
          <p class="muted small checks">{esc(" · ".join(extra))}</p>
        </article>"""

    body = []
    if clusters:
        items = []
        for g in clusters:
            t = g["trigger"]
            names = ", ".join(f'{esc(w["label"])} <span class="muted">({esc(w["kind"])}, {w["release"].year})</span>'
                              for w in g["works"])
            what = esc(t["text"].split(": ", 1)[-1] if t["type"] != "death" else t["text"].split(" (")[0])
            kind = {"death": "Death", "derivative": "New release", "same-creator": "New release"}.get(t["type"], "Event")
            items.append(f'<li><span class="muted">{kind} · {esc(t["date"])}</span><br>'
                         f'<a href="https://www.wikidata.org/wiki/{esc(t["qid"])}"><b>{what}</b></a> → '
                         f'{len(g["works"])} older works spiked: {names}</li>')
        body.append('<section><h3>Shared triggers</h3><p class="muted">One event linked to several '
                    'spiking works at once. This kind of finding needs data joined across sources.</p>'
                    f'<ul class="clusters">{"".join(items)}</ul></section>')
    if threads:
        items = []
        for t in threads:
            ws = ", ".join(f'{esc(w["label"])} <span class="muted">({esc(role)})</span>' for w, role in t["works"])
            items.append(f'<li><span class="muted">around {esc(t["around"])}</span><br>'
                         f'<a href="https://www.wikidata.org/wiki/{esc(t["qid"])}"><b>{esc(t["name"])}</b></a> → '
                         f'{len(t["works"])} works spiked together: {ws}</li>')
        body.append('<section><h3>Hidden common threads</h3><p class="muted">Spikes Wikidata can\'t explain, '
                    'but the works share a credited person and started rising within a week of each other. '
                    'Something likely happened involving that person. Check the news before drawing conclusions.</p>'
                    f'<ul class="clusters">{"".join(items)}</ul></section>')
    for title, blurb, verdicts in SECTIONS:
        sec = [r for r in results if r["verdict"] in verdicts]
        if sec:
            body.append(f'<section><h3>{esc(title)} <span class="muted">({len(sec)})</span></h3>'
                        f'<p class="muted">{esc(blurb)}</p>{"".join(card(r) for r in sec)}</section>')
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Rallyback</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1b; --muted:#6b6a65; --card:#fff; --line:#e6e3dc;
  --accent:#2d5bd7; --base:#b9b5ab;
  --c-unexplained:#b4462c; --c-death:#55555a; --c-derivative:#2d6f4f; --c-same:#6a4fb0; --c-ann:#9a6a14; --c-weak:#8a877f; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#151513; --fg:#ecebe6; --muted:#9d9b94; --card:#1e1e1b; --line:#33322e;
  --accent:#8aa9ff; --base:#5d5a53;
  --c-unexplained:#ff8a6b; --c-death:#b9b9c0; --c-derivative:#6fcf9f; --c-same:#b9a2ff; --c-ann:#e7b65a; --c-weak:#9d9b94; }} }}
:root[data-theme="dark"] {{ --bg:#151513; --fg:#ecebe6; --muted:#9d9b94; --card:#1e1e1b; --line:#33322e;
  --accent:#8aa9ff; --base:#5d5a53;
  --c-unexplained:#ff8a6b; --c-death:#b9b9c0; --c-derivative:#6fcf9f; --c-same:#b9a2ff; --c-ann:#e7b65a; --c-weak:#9d9b94; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width:920px; margin:0 auto; padding:32px 16px 64px }}
h1 {{ font-size:28px; margin:0 0 4px; letter-spacing:-.01em }}
h2 {{ font-size:17px; margin:0 }}
a {{ color:var(--accent); text-decoration:none }} a:hover {{ text-decoration:underline }}
.muted {{ color:var(--muted) }} .small {{ font-size:12px }}
.lede {{ max-width:68ch; color:var(--muted); margin:8px 0 16px }}
.chips {{ display:flex; flex-wrap:wrap; gap:6px; margin:12px 0 24px }}
.chip {{ font-size:12px; padding:2px 9px; border-radius:999px; border:1px solid currentColor; white-space:nowrap }}
.v-unexplained {{ color:var(--c-unexplained) }} .v-death {{ color:var(--c-death) }}
.v-derivative {{ color:var(--c-derivative) }} .v-same-creator {{ color:var(--c-same) }}
.v-anniversary {{ color:var(--c-ann) }} .v-common-thread {{ color:var(--c-same) }} .v-weak-link, .v-seasonal, .v-automated, .v-lookup-failed {{ color:var(--c-weak) }}
h3 {{ font-size:19px; margin:36px 0 2px }}
section > p.muted {{ margin:0 0 14px; max-width:70ch }}
.clusters {{ padding-left:18px }} .clusters li {{ margin:0 0 12px }}
.checks {{ margin:8px 0 0 }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin:0 0 12px }}
.head {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-start }}
.body {{ display:flex; flex-wrap:wrap; gap:20px; align-items:center; margin-top:12px }}
.spark svg {{ max-width:100%; height:auto; display:block }}
.spark .line {{ fill:none; stroke:var(--accent); stroke-width:1.4 }}
.spark .base {{ stroke:var(--base); stroke-dasharray:3 3 }}
dl {{ display:grid; grid-template-columns:repeat(4, auto); gap:4px 22px; margin:0 }}
dt {{ font-size:12px; color:var(--muted) }} dd {{ margin:0; font-variant-numeric:tabular-nums; font-weight:600 }}
.trig {{ margin:12px 0 0; padding-left:18px }}
footer {{ margin-top:32px; font-size:12px; color:var(--muted); max-width:72ch }}
@media (max-width:560px) {{ dl {{ grid-template-columns:repeat(2, auto) }} .head {{ flex-direction:column }} }}
</style></head>
<body><main>
<h1>The Rallyback</h1>
<p class="lede">Creative works released at least {meta['min_age']} years ago that reached English Wikipedia's daily top 1,000
between {esc(meta['window_start'])} and {esc(meta['window_end'])}, ranked by how far their recent attention sits above
their own 12-month baseline. Each is checked against Wikidata for a likely trigger.</p>
<div class="chips">{chips}</div>
{''.join(body) if body else '<p>No revivals met the thresholds in this window.</p>'}
<footer>Sources: Wikimedia Pageviews API (human traffic only) and Wikidata, both CC0. Lift = mean daily views over the last
{meta['recent_days']} days ÷ median daily views over the prior ~11 months. "No trigger found" means Wikidata has no
credited death, sequel, adaptation, new release or anniversary near the spike. It doesn't mean there's no cause:
memes, TV and ad sync placements, and viral clips aren't in Wikidata. Generated {esc(meta['generated'])}.</footer>
</main></body></html>"""
    with open(path, "w") as f:
        f.write(doc)


def fetch_images(qids: set[str], batch: int = 150) -> dict[str, str]:
    """Freely licensed images (Wikimedia Commons file names) via Wikidata: image, poster, logo.
    Only Commons files are linked, so everything shown is free to reuse with credit."""
    out: dict[str, str] = {}
    qids = [q for q in qids if q]
    for i in range(0, len(qids), batch):
        values = " ".join(f"wd:{q}" for q in qids[i:i + batch])
        q = f"""SELECT ?item ?p ?img WHERE {{
          VALUES ?item {{ {values} }}
          VALUES ?p {{ wdt:P18 wdt:P3383 wdt:P154 }}
          ?item ?p ?img .
        }}"""
        try:
            rows = sparql(q)
        except Exception as e:
            print(f"      image lookup failed for a batch: {e}", file=sys.stderr)
            continue
        rank = {"P18": 0, "P3383": 1, "P154": 2}
        best: dict[str, tuple[int, str]] = {}
        for row in rows:
            item, prop = qid(v(row, "item")), qid(v(row, "p"))
            name = urllib.parse.unquote(v(row, "img").rsplit("/", 1)[-1])
            if name.lower().endswith((".svg", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff")):
                if item not in best or rank[prop] < best[item][0]:
                    best[item] = (rank[prop], name)
        out.update({k: val for k, (_, val) in best.items()})
    return out


PERSON_RIPPLES = ("franchise", "series", "character", "source material", "sequel or adaptation")


def headline_person(r: dict) -> tuple[str, str] | None:
    """(person qid, name) when a story's headline is about a person: someone credited who died, a
    creator's new release, someone honoured, or the person in the news it rides on."""
    t = (r.get("triggers") or [{}])[0]
    text, v = t.get("text") or "", r.get("verdict")
    if v == "death" and t.get("qid"):
        return t["qid"], text.split(" (")[0]
    if v == "same-creator" and t.get("qid"):
        m = re.match(r"new work by (.+?):", text)
        return (t.get("person"), m.group(1)) if m else None   # the trigger's qid is the new work; "person" is the creator
    if v == "honor" and t.get("qid") and "): " in text:
        return t["qid"], text.split(" (")[0]
    rp = r.get("ripple") or {}
    if v == "ripple" and rp.get("qid") and rp.get("relation") not in PERSON_RIPPLES:
        return rp["qid"], rp.get("name") or ""
    return None


def fetch_series_images(qids: set[str], batch: int = 120) -> dict[str, tuple[str, str]]:
    """For works with no free image of their own: the logo (or image) of the series or franchise they
    belong to, from Commons via Wikidata. Better than a photo of the studio's office or a crew member:
    Grand Theft Auto (1998) gets the Grand Theft Auto series logo. {work qid: (file, series name)}."""
    out: dict[str, tuple[str, str]] = {}
    qids = [q for q in qids if q]
    rank = {"P154": 0, "P18": 1, "P3383": 2}
    for i in range(0, len(qids), batch):
        values = " ".join(f"wd:{q}" for q in qids[i:i + batch])
        q = f"""SELECT ?item ?rel ?s ?sLabel ?p ?img WHERE {{
          VALUES ?item {{ {values} }}
          VALUES ?rel {{ wdt:P179 wdt:P8345 }}
          VALUES ?p {{ wdt:P154 wdt:P18 wdt:P3383 }}
          ?item ?rel ?s . ?s ?p ?img .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        try:
            rows = sparql(q)
        except Exception as e:
            print(f"      series-image lookup failed for a batch: {e}", file=sys.stderr)
            continue
        best: dict[str, tuple] = {}
        for row in rows:
            item, prop, rel = qid(v(row, "item")), qid(v(row, "p")), qid(v(row, "rel"))
            name = urllib.parse.unquote(v(row, "img").rsplit("/", 1)[-1])
            if not name.lower().endswith((".svg", ".jpg", ".jpeg", ".png", ".webp")):
                continue
            key = (0 if rel == "P179" else 1, rank[prop])           # the series before the wider franchise
            if item not in best or key < best[item][0]:
                best[item] = (key, name, v(row, "sLabel"))
        out.update({k: (f, who) for k, (_, f, who) in best.items()})
    return out


PEOPLE_IMAGE_PROPS = ["P175", "P50", "P57", "P170", "P178", "P86", "P162", "P58"]  # performer, author, director, creator, developer, composer, producer, writer


# Films and TV: the best-known cast member first (people recognise stars, not directors).
SCREEN_IMAGE_PROPS = ["P161", "P57", "P58", "P162", "P86"]
WD_API = "https://www.wikidata.org/w/api.php"


def _entities(ids: list[str], props: str) -> dict:
    out = {}
    for i in range(0, len(ids), 50):
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props,
                                    "languages": "en", "format": "json"})
        try:
            out.update((http_json(f"{WD_API}?{q}", max_age_h=24 * 7) or {}).get("entities") or {})
        except Exception as e:
            print(f"      Wikidata entity lookup failed for a batch: {e}", file=sys.stderr)
    return out


def fetch_person_images_by_title(titles: set[str]) -> dict[str, tuple[str, str]]:
    """{English Wikipedia title: (Commons photo, name)} for titles whose article is about a person
    (Wikidata P31 = human) with a free photo. Used for editor's notes about a person."""
    titles = sorted(t for t in titles if t)
    if not titles:
        return {}
    values = " ".join('"' + t.replace("_", " ").replace("\\", "").replace('"', "") + '"@en' for t in titles)
    q = f"""SELECT ?t ?img ?pLabel WHERE {{
      VALUES ?t {{ {values} }}
      ?art schema:name ?t ; schema:isPartOf <https://en.wikipedia.org/> ; schema:about ?p .
      ?p wdt:P31 wd:Q5 ; wdt:P18 ?img .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
    }}"""
    try:
        rows = sparql(q)
    except Exception as e:
        print(f"      note-person image lookup failed: {e}", file=sys.stderr)
        return {}
    out: dict[str, tuple[str, str]] = {}
    for row in rows:
        name = urllib.parse.unquote(v(row, "img").rsplit("/", 1)[-1])
        if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
            out.setdefault(v(row, "t").replace(" ", "_"), (name, v(row, "pLabel")))
    return out


def fetch_star_images(qids: set[str], billed: int = 3) -> dict[str, tuple[str, str]]:
    """A photo of a film's or show's star: the first of its top-billed cast (Wikidata keeps the cast
    in billing order) with a free photo on Commons. Ranking by fame instead picks cameos: Kevin Bacon
    over Steve Martin and John Candy in Planes, Trains and Automobiles. {work qid: (file, name)}."""
    def claim_ids(ent, prop):
        return [c["mainsnak"]["datavalue"]["value"]["id"] for c in (ent.get("claims") or {}).get(prop, [])
                if c.get("mainsnak", {}).get("datavalue") and c.get("rank") != "deprecated"]
    works = _entities(sorted(q for q in qids if q), "claims")
    cast = {q: claim_ids(e, "P161")[:billed] for q, e in works.items()}
    people = _entities(sorted({p for ps in cast.values() for p in ps}), "claims|labels")
    out = {}
    for q, ps in cast.items():
        for p in ps:
            e = people.get(p) or {}
            imgs = [c["mainsnak"]["datavalue"]["value"] for c in (e.get("claims") or {}).get("P18", [])
                    if c.get("mainsnak", {}).get("datavalue")]
            img = next((i for i in imgs if i.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"))), None)
            if img:
                out[q] = (img, ((e.get("labels") or {}).get("en") or {}).get("value") or "")
                break
    return out


def fetch_people_images(qids: set[str], batch: int = 80, props_order: list[str] | None = None) -> dict[str, tuple[str, str]]:
    """For works with no free image of their own: a free photo of the person (or studio logo)
    behind them — performer, author, director, creator, developer. {work qid: (file, name)}."""
    out: dict[str, tuple[str, str]] = {}
    qids = [q for q in qids if q]
    order = props_order or PEOPLE_IMAGE_PROPS
    rank = {p: i for i, p in enumerate(order)}
    for i in range(0, len(qids), batch):
        values = " ".join(f"wd:{q}" for q in qids[i:i + batch])
        props = " ".join(f"wdt:{p}" for p in order)
        q = f"""SELECT ?item ?p ?who ?whoLabel ?img ?links WHERE {{
          VALUES ?item {{ {values} }}
          VALUES ?p {{ {props} }}
          ?item ?p ?who .
          VALUES ?t {{ wd:Q5 wd:Q215380 wd:Q5741069 wd:Q210167 wd:Q4830453 wd:Q1762059 wd:Q2088357 wd:Q105543609 }}
          ?who wdt:P31 ?t .
          ?who wdt:P18 ?img .
          ?who wikibase:sitelinks ?links .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        try:
            rows = sparql(q)
        except Exception as e:
            print(f"      people-image lookup failed for a batch: {e}", file=sys.stderr)
            continue
        best: dict[str, tuple] = {}
        for row in rows:
            item, prop = qid(v(row, "item")), qid(v(row, "p"))
            name = urllib.parse.unquote(v(row, "img").rsplit("/", 1)[-1])
            if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
                continue
            key = (rank[prop], -int(v(row, "links") or 0))
            if item not in best or key < best[item][0]:
                best[item] = (key, name, v(row, "whoLabel"))
        out.update({k: (f, who) for k, (_, f, who) in best.items()})
    return out


UNEXPLAINED_VERDICTS = {"unexplained", "weak link", "lookup failed", "common thread"}
SET_ASIDE_VERDICTS = {"seasonal", "automated?", "front page"}


def _open_cases(d: dict) -> set[str]:
    """Qids an edition listed as Unexplained (same rule as the site: a 'same person' group
    with a known cause counts as news, not a mystery)."""
    explained = {w["qid"] for t in d.get("common_threads", [])
                 if t.get("editor_note") or t.get("person_jump") or t.get("cause") for w in t["works"]}
    return {r["qid"] for r in d.get("results", []) if r["verdict"] in UNEXPLAINED_VERDICTS and r["qid"] not in explained}


def solved_cases(rdir: str, data: dict, run_id: str, days: int = 7) -> list[dict]:
    """Mysteries from the last week's editions that today's edition can explain: 'Case closed'."""
    start = (dt.date.fromisoformat(run_id) - dt.timedelta(days=days)).isoformat()
    editions = []
    for f in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []:
        rid = f[:-5]
        if f.endswith(".json") and start <= rid < run_id:
            try:
                with open(os.path.join(rdir, f)) as fh:
                    editions.append((rid, json.load(fh)))
            except (OSError, json.JSONDecodeError):
                continue
    editions.append((run_id, data))
    now_open = _open_cases(data)
    explained_now = {r["qid"]: r for r in data["results"]
                     if r["qid"] not in now_open and r["verdict"] not in SET_ASIDE_VERDICTS}
    out, last_open, solved_on = [], {}, {}
    for rid, d in editions:
        opened = _open_cases(d)
        present = {r["qid"] for r in d.get("results", [])}
        for q in opened:
            last_open[q] = rid
            solved_on.pop(q, None)
        for q in present - opened:
            if q in last_open and q not in solved_on:
                solved_on[q] = rid
    for q, day in solved_on.items():
        if q in explained_now:
            r = explained_now[q]
            out.append({"qid": q, "solved_on": day, "open_since": min(rid for rid, d in editions if q in _open_cases(d)),
                        "via": (r.get("editor_note") or {}).get("via")})
    out.sort(key=lambda x: (x["solved_on"], explained_now[x["qid"]].get("score", 0)), reverse=True)
    return out


_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def url_date(url: str) -> dt.date | None:
    """The publication date most news sites put in an article's address:
    /2026/10/31/, /2026/oct/31/, /2026-10-31, _20261119_, /2026/10/ (taken as the 1st)."""
    import re
    path = urllib.parse.urlparse(url).path.lower()
    pats = [(r"(?<!\d)(20\d\d|19\d\d)[/-](\d{1,2})[/-](\d{1,2})(?!\d)", lambda m: (m[1], m[2], m[3])),
            (r"(?<!\d)(20\d\d|19\d\d)/([a-z]{3})/(\d{1,2})(?!\d)", lambda m: (m[1], _MONTHS.get(m[2]), m[3])),
            (r"(?<!\d)(20\d\d|19\d\d)(\d\d)(\d\d)(?!\d)", lambda m: (m[1], m[2], m[3])),
            (r"(?<!\d)(20\d\d|19\d\d)/(\d{1,2})/", lambda m: (m[1], m[2], 1))]
    for rx, parts in pats:
        for m in re.finditer(rx, path):
            y, mo, d = parts(m)
            try:
                return dt.date(int(y), int(mo), int(d))
            except (TypeError, ValueError):
                continue
    return None


LINK_CHECKS = os.path.join(CACHE, "link_checks.json")
_link_cache: dict | None = None
_link_budget_end: float | None = None


def link_ok(url: str) -> bool:
    """Does the article still load, as itself (not an error, not a bounce to the homepage)?
    Remembered for 30 days. A site that blocks automated checks (401/403/405/429) gets the
    benefit of the doubt, since the address and date already matched."""
    global _link_cache
    if _link_cache is None:
        try:
            with open(LINK_CHECKS) as f:
                _link_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _link_cache = {}
    hit = _link_cache.get(url)
    if hit and time.time() - hit[1] < 30 * 86400:
        return hit[0]
    # At most 5 minutes of new checks a night; anything left waits for tomorrow (and isn't linked tonight).
    global _link_budget_end
    if _link_budget_end is None:
        _link_budget_end = time.time() + 300
    if time.time() > _link_budget_end:
        return False
    ok = True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Rallyback link check)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            final = urllib.parse.urlparse(r.geturl())
            ok = final.path.strip("/") != "" or urllib.parse.urlparse(url).path.strip("/") == ""
    except urllib.error.HTTPError as e:
        ok = e.code in (401, 403, 405, 429)
    except Exception:
        ok = False
    _link_cache[url] = [ok, time.time()]
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(LINK_CHECKS, "w") as f:
            json.dump(_link_cache, f)
    except OSError:
        pass
    return ok


def article_ok(url: str | None, start: dt.date | str | None, check: bool = True,
               published: str | None = None) -> bool:
    """An outside article fit to show readers: dated (by the news feed it came from, or in its
    address) from 120 days before this comeback started to today, and still loading as itself.
    Google News links are redirects that only a browser follows, so they aren't load-checked."""
    if not url or "wikipedia.org" in url:
        return bool(url)                              # Wikipedia's own pages are always fine
    if isinstance(start, str):
        start = dt.date.fromisoformat(start[:10])
    when = dt.date.fromisoformat(published[:10]) if published else url_date(url)
    lo = (start or dt.date.today()) - dt.timedelta(days=120)
    if when is None or not (lo <= when <= dt.date.today() + dt.timedelta(days=1)):
        return False
    return not check or "news.google.com" in url or link_ok(url)


def clean_evidence(evidence: list[dict] | None, start, check: bool = True) -> list[dict]:
    """Sources as shown on a story: what was found stays, but a link to an old, undated or
    broken article is removed (the line shows as plain text)."""
    out = []
    for e in evidence or []:
        if e.get("url") and not article_ok(e["url"], start, check, e.get("published")):
            e = {k: v for k, v in e.items() if k != "url"}
        out.append(e)
    return out


def cause_link(cause: str | None, evidence: list[dict] | None, start: dt.date | str | None = None,
               check: bool = True) -> dict | None:
    """The article behind a likely cause: an outside article whose text matches that cause
    (e.g. a 4K restoration announcement for "re-release"), published around this comeback.

    Wikipedia pages cite articles of any age, so a citation added this month can be a 2008
    story; only an article dated (in its address) from 120 days before the comeback started
    to today counts, and only if it still loads. No such article: no link, the reason stands
    as plain text."""
    if not cause or not evidence:
        return None
    import explain
    rx = dict(explain._CAUSE_RE).get(cause)
    if isinstance(start, str):
        start = dt.date.fromisoformat(start[:10])
    lo = (start or dt.date.today()) - dt.timedelta(days=120)
    hits = []
    for e in evidence:
        url = e.get("url")
        if not url or "wikipedia.org" in url or "bsky.app" in url or (rx is not None and not rx.search(e.get("text", ""))
                                                    and e.get("cause") != cause):
            continue
        published = dt.date.fromisoformat(e["published"][:10]) if e.get("published") else url_date(url)
        if published is None or not (lo <= published <= dt.date.today() + dt.timedelta(days=1)):
            continue
        hits.append((published, url, e.get("credit")))
    for published, url, credit in sorted(hits, key=lambda h: h[:2], reverse=True):
        if not check or "news.google.com" in url or link_ok(url):
            return {"url": url, "date": published.isoformat(), **({"credit": credit} if credit else {})}
    return None


def mark_freshness(rdir: str, data: dict, run_id: str) -> None:
    """For a front page that changes every morning: each comeback's days_on (editions in a row it has
    been on the list, 1 = new today) and prev_score (its Rallyback Score in the previous edition)."""
    prev_ids = sorted(f[:-5] for f in os.listdir(rdir) if f.endswith(".json") and f[:-5] < run_id) if os.path.isdir(rdir) else []
    prev = {}
    if prev_ids:
        try:
            with open(os.path.join(rdir, f"{prev_ids[-1]}.json")) as f:
                prev = {r["qid"]: r for r in json.load(f).get("results", [])}
        except (OSError, json.JSONDecodeError):
            prev = {}
    for r in data["results"]:
        p = prev.get(r["qid"])
        r["days_on"] = (p.get("days_on") or 1) + 1 if p else 1
        r["prev_score"] = p.get("rally_score") if p else None


def write_site_data(site: str, results, meta, clusters, threads, keep_runs: int,
                    coming_up: dict | None = None) -> dict:
    """latest.json + an archive of runs + an index of runs, for the static site."""
    def work(r):
        out = {k: r.get(k) for k in (
            "qid", "title", "label", "kind", "age", "verdict", "lift", "peak_lift", "baseline",
            "recent_mean", "peak", "score", "still_elevated", "last_year_lift", "desktop_share",
            "days_in_top", "best_rank", "lift3", "stage", "early", "early_ratio", "cause", "evidence",
            "edit_burst", "corroborated", "image", "image_of", "ripple", "editor_note", "front_page", "signals",
            "rally_score", "global", "chatter")}
        out["cause_link"] = cause_link(r.get("cause"), r.get("evidence"), r.get("spike_start"))
        out["evidence"] = clean_evidence(r.get("evidence"), r.get("spike_start"))
        out.update(release=r["release"].isoformat(), release_year=r["release"].year,
                   spike_start=r["spike_start"].isoformat(), peak_day=r["peak_day"].isoformat(),
                   spark_start=(r["spark_start"] + dt.timedelta(days=len(r["spark"]) - 365)).isoformat(),
                   spark=r["spark"][-365:],
                   triggers=[{k: t.get(k) for k in ("type", "date", "text", "qid", "lead_days", "weight", "shared", "approx", "person")}
                             for t in r["triggers"]])
        return out

    want = {r["qid"] for r in results} | {t["qid"] for t in threads} | \
           {g["trigger"].get("qid") for g in clusters} | \
           {c[k] for c in (coming_up or {}).get("derivatives", []) for k in ("new", "old")} | \
           {a["qid"] for a in (coming_up or {}).get("anniversaries", [])} | \
           {a["qid"] for a in (coming_up or {}).get("seasonal", [])} | \
           {a["qid"] for a in (coming_up or {}).get("warming", [])} | \
           {s["who"] for s in (coming_up or {}).get("subjects", [])} | \
           {w["qid"] for s in (coming_up or {}).get("subjects", []) for w in s["works"]}
    want |= {(r.get("ripple") or {}).get("qid") for r in results}
    want |= {(headline_person(r) or (None,))[0] for r in results} - {None}
    images = fetch_images(want)
    for r in results:
        r["image"], r["image_of"] = images.get(r["qid"]), None
        rp = r.get("ripple") or {}
        if not r["image"] and images.get(rp.get("qid")):
            r["image"], r["image_of"] = images[rp["qid"]], rp.get("name")
    # Films and TV: a photo of their best-known star by default (readers recognise the star more
    # readily than a still); before 1970, the film's own picture (the original poster) when it has one.
    screen_q = {r["qid"] for r in results if r.get("kind") in ("film", "TV series")}
    screen = fetch_star_images(screen_q)
    # No top-billed star with a photo: the director, writer, producer or composer.
    screen.update({q: v for q, v in fetch_people_images(screen_q - set(screen), props_order=SCREEN_IMAGE_PROPS[1:]).items()})
    for r in results:
        # Films made before 1970 keep their own picture (usually the original poster, public domain).
        classic = r.get("release") and str(r["release"])[:4] < "1970" and r["image"]
        if r["qid"] in screen and not classic:
            r["image"], r["image_of"] = screen[r["qid"]]
    # Games, books and music: the series or franchise logo (Grand Theft Auto's), before a person.
    series = fetch_series_images({r["qid"] for r in results if not r["image"]})
    for r in results:
        if not r["image"] and r["qid"] in series:
            r["image"], r["image_of"] = series[r["qid"]]
    people = fetch_people_images({r["qid"] for r in results if not r["image"]} |
                                 {c["old"] for c in (coming_up or {}).get("derivatives", []) if not images.get(c["old"])} |
                                 {a["qid"] for a in (coming_up or {}).get("anniversaries", []) if not images.get(a["qid"])} |
                                 {a["qid"] for a in (coming_up or {}).get("seasonal", []) if not images.get(a["qid"])})
    for r in results:
        if not r["image"] and r["qid"] in people:
            r["image"], r["image_of"] = people[r["qid"]]
    for c in (coming_up or {}).get("derivatives", []):
        c["new_image"], c["old_image"], c["old_image_of"] = images.get(c["new"]), images.get(c["old"]), None
        if not c["old_image"] and c["old"] in people:
            c["old_image"], c["old_image_of"] = people[c["old"]]
    for a in (coming_up or {}).get("anniversaries", []) + (coming_up or {}).get("seasonal", []) + (coming_up or {}).get("warming", []):
        a["image"], a["image_of"] = images.get(a["qid"]), None
    for s_ in (coming_up or {}).get("subjects", []):
        s_["image"] = images.get(s_["who"])
        for w_ in s_["works"]:
            w_["image"] = images.get(w_["qid"])
        if not a["image"] and a["qid"] in people:
            a["image"], a["image_of"] = people[a["qid"]]
    # Editor's notes about a person (Robert Pattinson cast as Bond): that person's photo leads the story.
    notes = [x["editor_note"] for x in [*results, *threads] if x.get("editor_note")]
    by_title = fetch_person_images_by_title({n.get("entity_title", "").replace(" ", "_") for n in notes})
    for n in notes:
        pic = by_title.get(n.get("entity_title", "").replace(" ", "_"))
        if pic:
            n["image"], n["image_of"] = pic
    # A story whose headline names a person shows that person ("…as fans remember Tom Stoppard").
    for r in results:
        hp = headline_person(r)
        if hp and hp[0] and images.get(hp[0]) and images[hp[0]].lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
            r["image"], r["image_of"] = images[hp[0]], hp[1]
    data = {
        "meta": meta,
        "results": [work(r) for r in results],
        "shared_triggers": [{"type": g["trigger"]["type"], "date": g["trigger"]["date"],
                             "image": images.get(g["trigger"].get("qid")),
                             "qid": g["trigger"]["qid"], "text": g["trigger"]["text"],
                             "works": [w["qid"] for w in g["works"]]} for g in clusters],
        "common_threads": [{"qid": t["qid"], "name": t["name"], "around": t["around"].isoformat(),
                            "title": t.get("title"), "cause": t.get("cause"), "evidence": clean_evidence(t.get("evidence"), t.get("around")),
                            "cause_link": cause_link(t.get("cause"), t.get("evidence"), t.get("around")),
                            "image": images.get(t["qid"]), "person_jump": t.get("person_jump"),
                            "editor_note": t.get("editor_note"),
                            "edit_burst": t.get("edit_burst"),
                            "works": [{"qid": w["qid"], "role": role} for w, role in t["works"]]}
                           for t in threads],
        "coming_up": coming_up or {"derivatives": [], "anniversaries": []},
    }
    ddir = os.path.join(site, "data")
    rdir = os.path.join(ddir, "runs")
    os.makedirs(rdir, exist_ok=True)
    run_id = meta["window_end"]
    mark_freshness(rdir, data, str(run_id))
    try:
        data["solved"] = solved_cases(rdir, json.loads(json.dumps(data, default=str)), str(run_id))
    except Exception as e:
        print(f"      solved-cases check failed: {e}", file=sys.stderr)
        data["solved"] = []
    for path in (os.path.join(ddir, "latest.json"), os.path.join(rdir, f"{run_id}.json")):
        with open(path, "w") as f:
            json.dump(data, f, separators=(",", ":"), default=str)
    # index of runs, newest first; prune old archives
    runs = sorted((f[:-5] for f in os.listdir(rdir) if f.endswith(".json")), reverse=True)
    for old in runs[keep_runs:]:
        os.remove(os.path.join(rdir, f"{old}.json"))
    index = []
    for rid in runs[:keep_runs]:
        with open(os.path.join(rdir, f"{rid}.json")) as f:
            d = json.load(f)
        counts = {}
        for r in d["results"]:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        top = [r["label"] for r in d["results"] if r["verdict"] in ("unexplained", "common thread")][:3]
        index.append({"id": rid, "generated": d["meta"]["generated"], "n": len(d["results"]),
                      "counts": counts, "top_unexplained": top})
    with open(os.path.join(ddir, "index.json"), "w") as f:
        json.dump({"runs": index, "verdict_labels": VERDICT_LABEL}, f, separators=(",", ":"))
    # Flat CSV of the latest run, for spreadsheets and research.
    import csv
    cols = ["label", "kind", "release", "age", "verdict", "stage", "lift", "lift3", "peak_lift", "baseline",
            "recent_mean", "spike_start", "peak_day", "still_elevated", "early", "cause", "top_trigger",
            "last_year_lift", "desktop_share", "qid", "title"]
    with open(os.path.join(ddir, "latest.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        for r in data["results"]:
            row = {**r, "top_trigger": r["triggers"][0]["text"] if r["triggers"] else ""}
            wr.writerow([row.get(c, "") if row.get(c) is not None else "" for c in cols])
    return data


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default="en.wikipedia")
    ap.add_argument("--days", type=int, default=30, help="discovery window (days of top lists)")
    ap.add_argument("--recent", type=int, default=14, help="days used to measure current attention")
    ap.add_argument("--min-age", type=int, default=10, help="minimum years since release")
    ap.add_argument("--min-lift", type=float, default=3.0)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--site", help="also write data for the website into SITE/data")
    ap.add_argument("--keep-runs", type=int, default=120, help="archived runs to keep on the site")
    ap.add_argument("--early-lift", type=float, default=2.5, help="3-day lift that counts as an early riser")
    ap.add_argument("--no-early", action="store_true", help="skip the bulk-file watchlist (faster, later detection)")
    ap.add_argument("--bulk-new-days", type=int, default=28,
                    help="max bulk pageview files to download in one run (~1 min each; later runs need 1)")
    ap.add_argument("--no-news", action="store_true", help="skip news lookups (news sites' feeds, Google News)")
    ap.add_argument("--explain-max", type=int, default=100, help="max unexplained spikes to research per run")
    ap.add_argument("--site-url", default="https://therallyback.com/",
                    help="the site's official address, used in feeds, share links and title pages")
    args = ap.parse_args()

    today = dt.date.today()
    end = latest_available_day(args.project)
    log = lambda *a: print(*a, file=sys.stderr, flush=True)

    prune_cache(35)
    log(f"[1/5] Discovering: top articles {end - dt.timedelta(days=args.days - 1)} .. {end}")
    seen = discover(args.project, end, args.days)
    log(f"      {len(seen):,} distinct articles")
    watch, audience = {}, {}
    if not args.no_early:
        import early
        log("      early detection from bulk pageview files")
        try:
            flagged, watch, audience = early.early_candidates(args.min_age, max_new_days=args.bulk_new_days)
        except Exception as e:  # never let the optional stage sink the run
            log(f"      early detection failed: {e}")
            flagged = {}
        for t, info in flagged.items():
            if t not in seen:
                seen[t] = {"days_in_top": 0, "best_rank": None, "early": True,
                           "early_ratio": info["early_ratio"]}

    # Second opinions from outside Wikipedia: Steam players, iTunes charts, Open Library trending.
    sig, strong = {}, set()
    if watch:
        import signals
        log("      other signals (Steam, iTunes charts, Open Library)")
        try:
            store = signals.collect(args.site or args.out, watch, today)
            sig = signals.read(store, today)
        except Exception as e:  # never let the optional stage sink the run
            log(f"      signals failed: {e}")
        strong = {q for q, ss in sig.items() if any(x["strong"] for x in ss)}
        q2t = {w["qid"]: t for t, w in watch.items()}
        for q in strong:
            t = q2t.get(q)
            if t and t not in seen:
                seen[t] = {"days_in_top": 0, "best_rank": None, "early": False}
        log(f"      {len(strong)} works with a strong signal elsewhere")

    log("[2/5] Classifying via Wikidata")
    works = classify(args.project, list(seen), args.min_age, today)
    log(f"      {len(works)} creative works at least {args.min_age} years old")

    log("[3/5] Measuring attention")
    start = end - dt.timedelta(days=399)

    def job(w):
        series = history_views(args.project, w["title"], start, end)
        m = measure(series, end, args.recent) if series is not None else None
        return w, m

    results = []
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        for w, m in ex.map(job, works):
            # Backed by a strong signal elsewhere, a smaller Wikipedia rise is enough.
            backed = w["qid"] in strong and m and max(m["lift"], m["lift3"]) >= 1.5
            if m and (m["lift"] >= args.min_lift or m["lift3"] >= args.early_lift or backed):
                w.update(m)
                w["age"] = today.year - w["release"].year
                w.update(seen[w["title"]])
                results.append(w)
    log(f"      {len(results)} with lift >= {args.min_lift}x (or rising >= {args.early_lift}x in 3 days)")

    log("[4/5] Looking for triggers")
    if results:
        since = min(r["spike_start"] for r in results) - dt.timedelta(days=50)
        find_triggers(results, since)
        if args.site and any(r.get("lookup_failed") for r in results):
            rdir = os.path.join(args.site, "data", "runs")
            paths = [os.path.join(args.site, "data", "latest.json")] + [
                os.path.join(rdir, x) for x in sorted(os.listdir(rdir), reverse=True)[:7]] if os.path.isdir(rdir) else []
            editions = []
            for path in paths:
                try:
                    with open(path) as f:
                        editions.append(json.load(f).get("results"))
                except (OSError, json.JSONDecodeError):
                    pass
            n = carry_over_triggers(results, editions)
            log(f"      kept {n} reasons from earlier editions where Wikidata failed twice")
        for r in results:
            r["window_end"] = end
            annotate(r)
            del r["window_end"]

    log("      sanity checks (seasonality, automated traffic)")
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(lambda r: sanity_checks(args.project, r, end, args.recent), results))

    # Shared triggers: one event (a death, a new film) linked to several spiking works.
    shared: dict[str, dict] = {}
    for r in results:
        for t in r["triggers"]:
            if t.get("qid"):
                g = shared.setdefault(t["qid"], {"trigger": t, "works": []})
                if all(w["qid"] != r["qid"] for w in g["works"]):
                    g["works"].append(r)
    clusters = sorted((g for g in shared.values() if len(g["works"]) >= 2),
                      key=lambda g: -len(g["works"]))
    for g in clusters:
        for r in g["works"]:
            for t in r["triggers"]:
                if t.get("qid") == g["trigger"]["qid"]:
                    t["weight"] = max(t["weight"], 3)
                    t["shared"] = len(g["works"])
            r["triggers"].sort(key=lambda t: (-t["weight"], abs(t["lead_days"])))
            r["verdict"] = r["triggers"][0]["type"]

    for r in results:
        strong = r["triggers"] and r["triggers"][0]["weight"] >= 2
        if strong:
            continue
        if r.get("desktop_share") is not None and r["desktop_share"] >= 0.85:
            r["verdict"] = "automated?"
        elif r.get("last_year_lift", 0) >= 2.5:
            r["verdict"] = "seasonal"
    # Wikipedia's own front page (featured article, Did you know, On this day) explains a one-day surge.
    try:
        import explain
        days = {r["peak_day"] + dt.timedelta(days=k) for r in results for k in (-1, 0)}
        feats = explain.front_page(days)
        for r in results:
            hit = [(d, kind) for d, kind in feats.get(r["title"], []) if 0 <= (r["peak_day"] - d).days <= 1]
            if hit:
                r["front_page"] = {"date": hit[0][0].isoformat(), "kind": hit[0][1]}
                if r["verdict"] not in ("death", "derivative", "editor", "editor-release", "editor-death"):
                    r["verdict"] = "front page"
        log(f"      front page: {sum(1 for r in results if r.get('front_page'))} spikes were Wikipedia front-page features")
    except Exception as e:
        log(f"      front-page check failed: {e}")
    for r in results:
        r["score_hint"] = math.log2(max(r["lift"], r["lift3"], 1.01)) * math.log10(10 + r["recent_mean"])
    log("      looking for common threads among unexplained spikes")
    threads = common_threads([r for r in results if r["verdict"] == "unexplained"])

    log("      ripple effect (did a connected person, franchise or adaptation spike too?)")
    import related
    try:
        related.ripple(args.project, [r for r in results if r["verdict"] in ("unexplained", "weak link", "common thread")], end)
    except Exception as e:
        log(f"      ripple check failed: {e}")
    for r in results:
        if r.get("ripple") and r["verdict"] in ("unexplained", "weak link"):
            r["verdict"] = "ripple"
    for t in threads:
        if t.get("title"):
            t["person_jump"] = related.person_jump(args.project, t["title"], t["around"], end)

    log("      researching causes (edit history, news)")
    import explain
    todo = sorted((r for r in results if r["verdict"] in ("unexplained", "ripple")), key=lambda r: -r["score_hint"])
    for r in todo[:args.explain_max]:
        rip = r.get("ripple")
        title, name = (rip["title"], rip["name"]) if rip else (r["title"], r["label"] or r["title"].replace("_", " "))
        # A ripple searches the connected person or franchise; otherwise the work's own title.
        e = explain.explain(args.project, title, name, r["spike_start"], with_news=not args.no_news,
                            person=bool(rip and rip.get("relation") not in
                                        ("franchise", "series", "character", "source material", "sequel or adaptation")),
                            kind=None if rip else r.get("kind"), video=not rip, qid=None if rip else r.get("qid"))
        r.update(evidence=e["evidence"], cause=e["cause"], edit_burst=e["edit_burst"])
        if e["cause"] and r["verdict"] == "unexplained":
            r["verdict"] = "coverage"
    for t in threads:
        if t.get("title"):
            e = explain.explain(args.project, t["title"], t["name"], t["around"], with_news=not args.no_news, person=True)
            t.update(evidence=e["evidence"], cause=e["cause"], edit_burst=e["edit_burst"])
    try:
        import youtube
        import tvmaze
        import musicbrainz
        import bluesky
        log(youtube.summary())
        log(tvmaze.summary())
        log(musicbrainz.summary())
        log(bluesky.summary())
        import currents
        log(currents.summary())
    except Exception:
        pass
    # Spot-check explained spikes against independent evidence (feeds the Accuracy tab).
    explained = [r for r in results if r["verdict"] in ("death", "derivative", "same-creator", "anniversary", "honor")]
    for r in explained[:15]:
        e = explain.explain(args.project, r["title"], r["label"] or r["title"].replace("_", " "),
                            r["spike_start"], with_news=not args.no_news, kind=r.get("kind"), qid=r.get("qid"))
        r.update(evidence=e["evidence"], edit_burst=e["edit_burst"])
        r["corroborated"] = explain.corroborates(r["triggers"][0], e["evidence"])

    import annotations
    annotations.apply(results, threads)

    coming_up = {"derivatives": [], "anniversaries": []}
    if watch:
        import forecast
        log("      forecasting (upcoming sequels/adaptations, anniversaries)")
        try:
            coming_up["derivatives"] = forecast.upcoming_derivatives(watch)[:200]
        except Exception as e:
            log(f"      derivative forecast failed: {e}")
        coming_up["anniversaries"] = forecast.anniversaries(watch, audience)
        # Predictions: learn from past releases and anniversaries how big a comeback to expect,
        # and find works that come back around the same date every year.
        try:
            import calibrate
            # The past is measured once (calibrate.py, via the "Backfill predictions" workflow);
            # nightly we only add our own newly checked forecasts and apply the model.
            calibrate.refresh(args.site)
            calibrate.annotate(args.site, coming_up, audience)
            by_qid = {w["qid"]: t for t, w in watch.items()}
            seasonal_seen = {r["title"] for r in results if (r.get("last_year_lift") or 0) >= 2 or r["verdict"] == "seasonal"}
            hdir = os.path.join(args.site, "data", "history")
            for f in sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []:
                with open(os.path.join(hdir, f)) as fh:
                    month = json.load(fh)
                for day in month.get("days", {}).values():
                    seasonal_seen |= {by_qid[q] for q, row in day.items() if row[3] == "seasonal" and q in by_qid}
            coming_up["seasonal"] = calibrate.seasonal(args.site, args.project, watch, audience, seasonal_seen,
                                                       budget_s=3 * 60)
        except Exception as e:
            log(f"      predictions failed: {e}")
        # Titles on a steady climb, and documentaries / biopics about people with older work.
        try:
            import outlook
            coming_up["warming"] = outlook.warming(watch, {r["title"] for r in results}, end.isoformat())
            coming_up["subjects"] = outlook.subjects(watch)
        except Exception as e:
            log(f"      warming up / documentaries failed: {e}")
    for r in results:
        r["label"] = nice_label(r["label"], r["title"])
        for t in r["triggers"]:
            t["text"] = t["text"].replace(t.get("qid") or "@@", "a new work") if t.get("qid") and t["qid"] in t["text"] else t["text"]

    # Rank: lift, damped by scale so tiny pages with noisy baselines don't dominate.
    # Second opinions per comeback: other-language Wikipedia, Bluesky chatter.
    import enrich
    for r in results:
        r["signals"] = sig.get(r["qid"], [])
    for name, fn in (("other languages", enrich.global_reach), ("Bluesky", enrich.chatter)):
        try:
            fn(results, end)
        except Exception as e:  # optional; never sink the run
            log(f"      {name} check failed: {e}")
    # Rank by the Rallyback Score (0-100): jump, audience, confirmations elsewhere, staying power.
    for r in results:
        r["rally_score"] = enrich.rally_score(r, end)
        r["score"] = round(r["rally_score"] + r.pop("score_hint") / 100, 2)   # hint breaks ties
        r["early"] = bool(r.get("early"))
    results.sort(key=lambda r: -r["score"])

    log("[5/5] Writing report")
    os.makedirs(args.out, exist_ok=True)
    meta = {
        "project": args.project, "min_age": args.min_age, "recent_days": args.recent,
        "window_start": (end - dt.timedelta(days=args.days - 1)).isoformat(),
        "window_end": end.isoformat(),
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candidates": len(works), "articles_scanned": len(seen), "health": HEALTH,
    }
    write_html(results, meta, os.path.join(args.out, "report.html"), clusters, threads)
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump({"meta": meta, "results": [{k: val for k, val in r.items() if k != "spark"} for r in results]},
                  f, indent=2, default=str)

    if args.site:
        prev = None
        try:
            with open(os.path.join(args.site, "data", "latest.json")) as f:
                prev = json.load(f)
            if prev.get("meta", {}).get("window_end") == end.isoformat():
                prev_file = sorted(os.listdir(os.path.join(args.site, "data", "runs")))
                prev_file = [x for x in prev_file if x < f"{end.isoformat()}.json"]
                prev = json.load(open(os.path.join(args.site, "data", "runs", prev_file[-1]))) if prev_file else None
        except (OSError, json.JSONDecodeError, IndexError):
            prev = None
        data = write_site_data(args.site, results, meta, clusters, threads, args.keep_runs, coming_up)
        try:
            enrich.record(args.site, results, end.isoformat())     # permanent daily history
        except Exception as e:
            log(f"      history record failed: {e}")
        try:
            import measures     # measures that publish themselves once they have enough examples
            data["measures_new"] = measures.build(args.site)
        except Exception as e:
            log(f"      measures failed: {e}")
        import feeds
        import evaluate
        new = feeds.write(args.site, data, prev, args.site_url, VERDICT_LABEL)
        log(f"      {len(new)} new findings in feeds")
        try:
            evaluate.summarize(args.site, args.project)
        except Exception as e:
            log(f"      accuracy summary failed: {e}")
        try:
            import archive      # title pages, search index, leaderboards, weekly roundup
            archive.build(args.site, args.site_url)
        except Exception as e:
            log(f"      archive build failed: {e}")

    print(f"\n{'Work':42} {'Kind':11} {'Year':>4} {'Lift':>6}  Verdict / top trigger")
    for r in results[:40]:
        top = r["triggers"][0]["text"] if r["triggers"] else ""
        name = (r["label"] or r["title"])[:42]
        print(f"{name:42} {r['kind'][:11]:11} {r['release'].year:>4} {r['lift']:>5}x  "
              f"{VERDICT_LABEL[r['verdict']]}{' - ' + top if top else ''}")
    print(f"\nReport: {os.path.join(args.out, 'report.html')}")


if __name__ == "__main__":
    main()
