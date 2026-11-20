"""
Two more kinds of "Coming up":

  warming   Titles on a steady climb that haven't crossed the comeback line yet: the last week
            well above their usual level, higher than the week before, and not just a one-day
            spike. From the daily view counts the watchlist already keeps (no extra requests).
  subjects  Documentaries and biopics on the way: a new film or series *about* a person or band
            sends people back to that person's own work, the way a sequel does for its original.
            From Wikidata (the new work's "main subject"), checked weekly.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import math
import os
import statistics
import sys
import time

import radar

SUBJECTS_CACHE = os.path.join(radar.CACHE, "subjects.json")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def warming(watch: dict[str, dict], on_list: set[str], run: str, top: int = 30) -> list[dict]:
    files = sorted(glob.glob(os.path.join(radar.CACHE, "bulk", "*.json")))[-28:]
    if len(files) < 21:
        log(f"      warming up: needs 21 days of daily counts, have {len(files)}")
        return []
    days = []
    for f in files:
        try:
            with open(f) as fh:
                days.append(json.load(fh))
        except (OSError, json.JSONDecodeError):
            continue
    out = []
    for title, w in watch.items():
        if title in on_list:
            continue
        s = [d.get(title, [0, 0])[0] for d in days]
        base = statistics.median(s[:-7])
        if base < 50:                                   # too quiet to call a trend
            continue
        last, prev = s[-7:], s[-14:-7]
        w1, w0 = sum(last) / 7, sum(prev) / 7
        ratio = w1 / base
        # Up at least 40% on the usual, higher than the week before, and every day of the
        # last week above usual (a steady climb, not a one-day spike).
        # Below 3x: past that it's a comeback, not warming up.
        if ratio < 1.4 or ratio >= 3 or w1 < w0 * 1.1 or w0 < base or min(last) < base * 1.1:
            continue
        out.append({"title": title, "label": title.replace("_", " "), "qid": w["qid"], "kind": w["kind"],
                    "release": w.get("release", ""), "date": run, "ratio": round(ratio, 2),
                    "week_ratio": round(w1 / max(w0, 1), 2), "usual": round(base), "trend": s[-21:],
                    "score": ratio * math.log10(base)})
    out.sort(key=lambda x: -x["score"])
    for x in out:
        x.pop("score")
    log(f"      warming up: {len(out)} titles on a steady climb (showing {min(top, len(out))})")
    return out[:top]


SUBJECT_CLASSES = "wd:Q11424 wd:Q93204 wd:Q5398426 wd:Q1259759 wd:Q24869"   # film, documentary, TV series, miniseries, feature
PEOPLE = "wd:Q5 wd:Q215380 wd:Q5741069"                                       # human, band, musical group
CREDITS = "wdt:P175 wdt:P57 wdt:P50 wdt:P161 wdt:P86 wdt:P170 wdt:P162 wdt:P58"


def subjects(watch: dict[str, dict], horizon: int = 183, max_age_days: float = 7) -> list[dict]:
    """New films and series about a person or band, due in the next six months, with that
    person's best-known older works from the watchlist."""
    today = dt.date.today()
    cached = None
    if os.path.exists(SUBJECTS_CACHE) and time.time() - os.path.getmtime(SUBJECTS_CACHE) < max_age_days * 86400:
        with open(SUBJECTS_CACHE) as f:
            cached = json.load(f)
    if cached is None:
        lo, hi = today.isoformat(), (today + dt.timedelta(days=horizon)).isoformat()
        new = []
        for cls in SUBJECT_CLASSES.split():             # one query per type keeps each one small
            q = f"""SELECT DISTINCT ?new ?newLabel ?date ?who ?whoLabel WHERE {{
              ?new wdt:P31 {cls} ; wdt:P577 ?date .
              FILTER(?date >= "{lo}T00:00:00Z"^^xsd:dateTime && ?date < "{hi}T00:00:00Z"^^xsd:dateTime)
              ?new wdt:P921 ?who . VALUES ?t {{ {PEOPLE} }} ?who wdt:P31 ?t .
              SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }} }}"""
            try:
                rows = radar.sparql(q)
            except Exception as e:
                log(f"      documentary/biopic lookup failed ({cls}): {e}")
                continue
            new += [{"new": radar.qid(radar.v(r, "new")), "new_label": radar.nice_label(radar.v(r, "newLabel")),
                     "date": radar.v(r, "date")[:10], "who": radar.qid(radar.v(r, "who")),
                     "who_label": radar.nice_label(radar.v(r, "whoLabel"))} for r in rows]
        people = sorted({n["who"] for n in new})
        credits: dict[str, list[str]] = {}
        for i in range(0, len(people), 100):
            vals = " ".join(f"wd:{p}" for p in people[i:i + 100])
            try:
                res = radar.sparql(f"SELECT DISTINCT ?who ?w WHERE {{ VALUES ?who {{ {vals} }} VALUES ?p {{ {CREDITS} }} ?w ?p ?who . }}")
            except Exception as e:
                log(f"      documentary/biopic credits lookup failed: {e}")
                continue
            for r in res:
                credits.setdefault(radar.qid(radar.v(r, "who")), []).append(radar.qid(radar.v(r, "w")))
        cached = {"new": new, "credits": credits}
        if not new:
            return []
        os.makedirs(radar.CACHE, exist_ok=True)
        with open(SUBJECTS_CACHE, "w") as f:
            json.dump(cached, f)
    by_qid = {w["qid"]: (t, w) for t, w in watch.items()}
    out, seen = [], set()
    for n in sorted(cached["new"], key=lambda n: n["date"]):
        if n["date"] < today.isoformat() or (n["new"], n["who"]) in seen:
            continue
        works = [by_qid[q] for q in set(cached["credits"].get(n["who"], [])) if q in by_qid and q != n["new"]]
        if not works:
            continue
        seen.add((n["new"], n["who"]))
        works.sort(key=lambda tw: -tw[1].get("sitelinks", 0))
        out.append({**n, "works": [{"qid": w["qid"], "title": t, "label": t.replace("_", " "), "kind": w["kind"],
                                    "release": w.get("release", "")} for t, w in works[:4]],
                    "more": max(0, len(works) - 4)})
    log(f"      documentaries and biopics: {len(out)} on the way about people with notable older work")
    return out
