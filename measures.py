"""
Measures only The Rallyback can calculate, from its own permanent record. Each is worked out
every night, kept hidden until it has enough examples to be trustworthy, then published on the
Track record page (and announced in the feeds) the day it crosses that line. If a measure later
falls below its threshold (a source breaks, the record is reset), it hides itself again.

  staying       how long a comeback lasts, by what caused it (a death, a new release, news...)
  lead          does Wikipedia attention move before the charts (iTunes, Deezer, Steam, Open Library)?
  star          whose news moves their old work most: people behind 3+ separate comebacks
  calibration   our own forecasts: when we said "60% chance", how often did it happen?

Writes site/data/measures.json. Returns the measures that became ready today, for the feeds.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import sys

import archive

NEED = {"staying": 20, "lead": 30, "star": 25, "calibration": 100}
CAUSE = {"death": "A death", "derivative": "A new release", "same-creator": "A new release",
         "anniversary": "An anniversary", "editor": "News", "editor-release": "A new release", "editor-death": "A death", "coverage": "News", "ripple": "News",
         "common thread": "Unexplained", "unexplained": "Unexplained", "weak link": "Unexplained", "lookup failed": "Unexplained"}
PERSON_CAUSES = ("death", "ripple", "common thread", "same-creator")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _d(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def build(site: str) -> list[dict]:
    hist = archive.load_history(site)
    runs = sorted(hist["days"])
    if not runs:
        return []
    end = _d(runs[-1])
    works, names = hist["works"], hist["names"]
    eps = [(q, e) for q in works for e in archive.episodes_of(q, hist["days"], runs)]
    out = {}

    # Staying power: finished comebacks only (off the list for over a week).
    done = [(q, e) for q, e in eps if (end - _d(e["last_seen"])).days > archive.EPISODE_GAP and e["verdict"] in CAUSE]
    by_cause: dict[str, list[int]] = {}
    for q, e in done:
        by_cause.setdefault(CAUSE[e["verdict"]], []).append((_d(e["last_seen"]) - _d(e["start"])).days + 1)
    ready_causes = {c: xs for c, xs in by_cause.items() if len(xs) >= NEED["staying"]}
    out["staying"] = {
        "title": "Staying power: how long a comeback lasts, by cause",
        "have": max((len(xs) for xs in by_cause.values()), default=0), "need": NEED["staying"],
        "unit": "finished comebacks for a cause", "ready": len(ready_causes) >= 2,
        "progress": {c: len(xs) for c, xs in sorted(by_cause.items(), key=lambda kv: -len(kv[1]))},
        "result": [{"cause": c, "n": len(xs), "median_days": statistics.median(xs),
                    "long": sorted(xs)[(3 * len(xs)) // 4]} for c, xs in sorted(ready_causes.items(), key=lambda kv: -statistics.median(kv[1]))]}

    # Lead time: when a comeback also shows up on a chart, which moved first?
    sdir = os.path.join(site, "data", "signals")
    first_chart: dict[str, dt.date] = {}
    sig_start = None
    for f in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        try:
            with open(os.path.join(sdir, f)) as fh:
                m = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        for day, charts in sorted(m.get("days", {}).items()):
            sig_start = sig_start or _d(day)
            for chart, pos in charts.items():
                if chart == "steam":                     # player counts, not a chart position
                    continue
                for q in pos:
                    first_chart.setdefault(q, _d(day))
    leads = []
    for q, e in eps:
        s = _d(e["start"])
        if q in first_chart and sig_start and s >= sig_start + dt.timedelta(days=30) and abs((first_chart[q] - s).days) <= 30:
            leads.append((first_chart[q] - s).days)
    out["lead"] = {
        "title": "Lead time: does Wikipedia move before the charts?", "have": len(leads), "need": NEED["lead"],
        "unit": "comebacks that also reached a chart", "ready": len(leads) >= NEED["lead"],
        "result": {"n": len(leads), "median_days": statistics.median(leads) if leads else None,
                   "wiki_first": round(sum(1 for x in leads if x > 0) / len(leads), 2) if leads else None}}

    # Star power: people behind 3+ separate comebacks (two weeks apart or more).
    events: dict[str, list[tuple[dt.date, float, str]]] = {}
    for q, e in eps:
        for c in e.get("causes") or []:
            if c[0] in PERSON_CAUSES and c[1]:
                events.setdefault(c[1], []).append((_d(e["start"]), e["peak_lift"], q))
    stars = []
    for who, ev in events.items():
        ev.sort()
        moments, last = [], None
        for d, lift, q in ev:
            if last is None or (d - last).days >= 14:
                moments.append([])
                last = d
            moments[-1].append(lift)
        if len(moments) >= 3:
            stars.append({"qid": who, "name": names.get(who), "moments": len(moments),
                          "median_lift": round(statistics.median(max(m) for m in moments), 1),
                          "titles": len({q for _, _, q in ev})})
    stars.sort(key=lambda x: (-x["median_lift"], -x["moments"]))
    out["star"] = {"title": "Star power: whose news moves their old work most", "have": len(stars), "need": NEED["star"],
                   "unit": "people behind 3+ separate comebacks", "ready": len(stars) >= NEED["star"], "result": stars[:25]}

    # Calibration: our own forecasts, grouped by the chance we gave them.
    checks = [x for x in archive._load(os.path.join(site, "data", "forecast_checks.json"), {}).values()
              if (x.get("predicted") or {}).get("chance") is not None]
    buckets: dict[int, list[bool]] = {}
    for x in checks:
        b = min(int(x["predicted"]["chance"] * 10), 9)
        buckets.setdefault(b, []).append(bool(x["hit"]))
    out["calibration"] = {
        "title": "How good are our odds? Predicted chance vs. what happened", "have": len(checks), "need": NEED["calibration"],
        "unit": "checked forecasts with a % chance", "ready": len(checks) >= NEED["calibration"],
        "result": [{"said": f"{b * 10}–{b * 10 + 9}%", "n": len(v), "happened": round(sum(v) / len(v), 2)}
                   for b, v in sorted(buckets.items())]}

    path = os.path.join(site, "data", "measures.json")
    old = archive._load(path, {})
    announce = []
    for k, m in out.items():
        was = (old.get(k) or {}).get("ready_since")
        m["ready_since"] = (was or runs[-1]) if m["ready"] else None
        if m["ready"] and not was:
            announce.append({"key": k, "title": m["title"], "date": runs[-1]})
    archive._save(path, {**out, "updated": runs[-1]})
    log("      measures: " + ", ".join(f"{k} {m['have']}/{m['need']}{' READY' if m['ready'] else ''}" for k, m in out.items()))
    return announce
