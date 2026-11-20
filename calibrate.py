"""
Predictions for "Coming up": how big a comeback to expect, and how likely it is.

Wikipedia's daily views go back to July 2015, and Wikidata lists the sequels, remakes,
adaptations and series entries released since then. So instead of waiting a year for our
own forecasts to be checked, we measure what actually happened to each original when its
follow-up came out (and to well-known works on their past round anniversaries), using
exactly the rule the Track record uses for our own forecasts:

  usual  = median daily views 60 to 14 days before the date
  bump   = best 3-day average within a week either side of the date
  ratio  = bump / usual; a "comeback" is 2x or more

Cases are kept in site/data/calibration/cases.json (permanent, grows a little each night
under a time budget until the backlog is done). model.json summarises them by kind of
release, kind of work and size of everyday audience, and annotate() puts an expected bump
and a chance on every Coming up item.

Also builds "Back every year": works whose views peak around the same date year after year
(Christmas films, Halloween, Valentine's Day...), from three years of their own history.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import os
import statistics
import sys
import time

import radar
import forecast

HIT = 2.0                 # a comeback is 2x the usual interest (same as the Track record)
MIN_CASES = 50            # an expected size is shown only when it rests on at least this many past cases
MIN_CASES_CHANCE = 100    # the "% chance" needs more: with fewer, it could be off by 15+ points
BACKFILL_FROM = dt.date(2016, 1, 1)
PAST_DERIV_CACHE = os.path.join(radar.CACHE, "calibration_past_derivatives.json")


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))


def audience_bucket(views: float | None) -> str:
    v = views or 0
    return "1k+" if v >= 1000 else "100-1k" if v >= 100 else "<100"


def years_bucket(years: int) -> str:
    return "10" if years <= 10 else "20-25" if years <= 25 else "30-40" if years <= 40 else "50+"


# ---------- measuring one case ----------

def measure(project: str, title: str, d: dt.date) -> tuple[float, float] | None:
    """(ratio, usual daily views) around date d, or None if there isn't enough history."""
    series = radar.daily_views(project, title, d - dt.timedelta(days=60), d + dt.timedelta(days=7))
    if not series:
        return None
    base = [series.get(d - dt.timedelta(days=i), 0) for i in range(14, 61)]
    if sum(1 for x in base if x > 0) < 30:
        return None
    usual = statistics.median(base)
    if usual < 5:                      # too quiet to say anything about a ratio
        return None
    near = [series.get(d + dt.timedelta(days=i), 0) for i in range(-7, 8)]
    best3 = max(sum(near[i:i + 3]) / 3 for i in range(len(near) - 2))
    return round(best3 / usual, 2), round(usual, 1)


# ---------- the backlog of past cases ----------

def past_derivatives(watch: dict[str, dict], budget_s: float = 8 * 60, batch: int = 400) -> list[dict]:
    """Sequels, remakes, adaptations and series entries released 2016 to a month ago, whose
    original is on the watchlist. Asked about the watched works directly, a batch at a time;
    each batch's answer is saved as it arrives, so a slow night just resumes the next night.
    Rebuilt from scratch every 30 days."""
    store = _load(PAST_DERIV_CACHE, {})
    if not store or time.time() - store.get("started", 0) > 30 * 86400:
        store = {"started": time.time(), "batches": {}}
    lo, hi = BACKFILL_FROM.isoformat(), (dt.date.today() - dt.timedelta(days=30)).isoformat()
    kinds = {cls.split(":")[1]: kind for kind, cls in forecast.NEW_CLASSES}
    classes = " ".join(cls for _, cls in forecast.NEW_CLASSES)
    when = f'FILTER(?date >= "{lo}T00:00:00Z"^^xsd:dateTime && ?date < "{hi}T00:00:00Z"^^xsd:dateTime)'
    qids = sorted(w["qid"] for w in watch.values() if w.get("qid"))
    t0, done_now = time.time(), 0
    for i in range(0, len(qids), batch):
        key = qids[i]
        if key in store["batches"]:
            continue
        if time.time() - t0 > budget_s:
            break
        values = " ".join(f"wd:{q}" for q in qids[i:i + batch])
        direct = f"""SELECT DISTINCT ?new ?date ?old ?rel ?cls WHERE {{
          VALUES ?old {{ {values} }}
          VALUES (?p ?rel) {{ (wdt:P144 "adaptation of") (wdt:P155 "sequel to") (wdt:P5059 "remake of") }}
          VALUES ?cls {{ {classes} }}
          ?new ?p ?old ; wdt:P31 ?cls ; wdt:P577 ?date . {when} }}"""
        series = f"""SELECT DISTINCT ?new ?date ?old ?cls WHERE {{
          VALUES ?old {{ {values} }}
          VALUES ?cls {{ {classes} }}
          ?old wdt:P179 ?s . ?new wdt:P179 ?s ; wdt:P31 ?cls ; wdt:P577 ?date .
          FILTER(?new != ?old) {when} }}"""
        rows, ok = [], True
        for q, fixed_rel in ((direct, None), (series, "new entry in the series of")):
            try:
                res = radar.sparql(q)
            except Exception as e:
                log(f"      past-release lookup failed for a batch: {e}")
                ok = False
                break
            for r in res:
                rows.append({"new": radar.qid(radar.v(r, "new")), "new_kind": kinds.get(radar.qid(radar.v(r, "cls")), "film"),
                             "rel": fixed_rel or radar.v(r, "rel"), "date": radar.v(r, "date")[:10],
                             "old": radar.qid(radar.v(r, "old"))})
        if ok:
            store["batches"][key] = rows
            done_now += 1
            _save(PAST_DERIV_CACHE, store)
    total = -(-len(qids) // batch)
    log(f"      past releases: {len(store['batches'])} of {total} watchlist batches looked up ({done_now} tonight)")
    rows = [r for b in store["batches"].values() for r in b]
    by_qid = {w["qid"]: (title, w) for title, w in watch.items()}
    out, per_new, seen = [], {}, set()
    for r in sorted(rows, key=lambda r: -(by_qid[r["old"]][1].get("sitelinks", 0) if r["old"] in by_qid else 0)):
        if r["old"] not in by_qid or (r["new"], r["old"]) in seen:
            continue
        title, w = by_qid[r["old"]]
        if w.get("release", "") >= r["date"]:          # the "original" must come first
            continue
        seen.add((r["new"], r["old"]))
        per_new[r["new"]] = per_new.get(r["new"], 0) + 1
        if per_new[r["new"]] > 4:                       # same rule as Coming up: 4 best-known per new work
            continue
        out.append({**r, "title": title, "old_kind": w["kind"], "old_year": w.get("release", "")[:4]})
    return out


def past_anniversaries(watch: dict[str, dict], audience: dict[str, float], top: int = 4000) -> list[dict]:
    """Round anniversaries of well-known watched works, 2016 to a month ago."""
    last = dt.date.today() - dt.timedelta(days=30)
    out = []
    for title, w in sorted(watch.items(), key=lambda x: -audience.get(x[0], 0))[:top]:
        try:
            r = dt.date.fromisoformat(w["release"])
        except (ValueError, KeyError):
            continue
        if (r.month, r.day) == (1, 1):
            continue
        for years in sorted(radar.ANNIVERSARIES):
            try:
                ann = r.replace(year=r.year + years)
            except ValueError:
                ann = dt.date(r.year + years, 3, 1)
            if BACKFILL_FROM <= ann <= last:
                out.append({"title": title, "old": w["qid"], "old_kind": w["kind"], "years": years,
                            "date": ann.isoformat(), "old_year": w["release"][:4]})
    return out


def update(site: str, project: str, watch: dict[str, dict], audience: dict[str, float],
           budget_s: float = 10 * 60, lookup_budget_s: float = 8 * 60) -> dict:
    """Measure more past cases (as many as fit in the time budget), then rebuild the model."""
    cdir = os.path.join(site, "data", "calibration")
    cases = _load(os.path.join(cdir, "cases.json"), {})
    todo = [("derivative", c) for c in past_derivatives(watch, lookup_budget_s)] + [("anniversary", c) for c in past_anniversaries(watch, audience)]
    added = skipped = 0
    t0 = time.time()
    keyf = lambda kind, c: f"{kind}|{c['old']}|{c['date']}" + (f"|{c['new']}" if kind == "derivative" else "")
    # Best-known first, so the model is useful long before the backlog is done.
    pending = [(kind, c) for kind, c in todo if keyf(kind, c) not in cases]
    pending.sort(key=lambda kc: -audience.get(kc[1]["title"], 0))

    def one(kc):
        kind, c = kc
        return kc, measure(project, c["title"], dt.date.fromisoformat(c["date"]))

    with cf.ThreadPoolExecutor(6) as pool:           # a few requests at once, well within Wikimedia's limits
        for i in range(0, len(pending), 60):
            if time.time() - t0 > budget_s:
                break
            for (kind, c), m in pool.map(one, pending[i:i + 60]):
                key = keyf(kind, c)
                if m is None:
                    cases[key] = None                   # remembered, so it isn't fetched again
                    skipped += 1
                    continue
                ratio, usual = m
                cases[key] = {"kind": kind, "date": c["date"], "old": c["old"], "old_kind": c["old_kind"],
                              "old_year": c.get("old_year"), "ratio": ratio, "usual": usual,
                              **({"rel": c["rel"], "new_kind": c["new_kind"], "new": c["new"]} if kind == "derivative"
                                 else {"years": c["years"]})}
                added += 1
    left = sum(1 for kind, c in todo
               if (f"{kind}|{c['old']}|{c['date']}" + (f"|{c['new']}" if kind == "derivative" else "")) not in cases)
    _save(os.path.join(cdir, "cases.json"), cases)
    model = build_model([c for c in cases.values() if c])
    model["backlog_left"] = left
    _save(os.path.join(cdir, "model.json"), model)
    log(f"      predictions: measured {added} past cases ({skipped} too quiet), {left} still to do; "
        f"{model['cases']} cases in the model")
    return model


# ---------- the model ----------

def _keys(c: dict) -> list[str]:
    """Most specific first; a prediction uses the first group with enough cases."""
    b = audience_bucket(c.get("usual"))
    if c["kind"] == "derivative":
        return [f"derivative|{c['rel']}|{c['old_kind']}|{b}", f"derivative|{c['rel']}|{b}",
                f"derivative|{c['rel']}", "derivative"]
    y = years_bucket(c["years"])
    return [f"anniversary|{y}|{c['old_kind']}|{b}", f"anniversary|{y}|{b}", f"anniversary|{y}", "anniversary"]


def build_model(cases: list[dict]) -> dict:
    groups: dict[str, list[float]] = {}
    for c in cases:
        for k in _keys(c):
            groups.setdefault(k, []).append(c["ratio"])
    out = {}
    for k, rs in groups.items():
        rs.sort()
        out[k] = {"n": len(rs), "expected": round(statistics.median(rs), 1),
                  "chance": round(sum(1 for r in rs if r >= HIT) / len(rs), 2),
                  "low": round(rs[len(rs) // 4], 1), "high": round(rs[(3 * len(rs)) // 4], 1)}
    return {"cases": len(cases), "groups": out, "rule": f"comeback = {HIT}x usual interest within a week of the date",
            "built": dt.date.today().isoformat()}


BASIS = {"adaptation of": "adaptations", "sequel to": "sequels", "remake of": "remakes",
         "new entry in the series of": "new series entries"}


def predict(model: dict, c: dict) -> dict | None:
    for k in _keys(c):
        g = model.get("groups", {}).get(k)
        if g and g["n"] >= MIN_CASES:
            what = (f"{BASIS.get(c['rel'], 'new releases')}" if c["kind"] == "derivative"
                    else f"{c['years']}th anniversaries" if years_bucket(c["years"]) == "10" or c["years"] >= 50
                    else "anniversaries like this")
            return {"expected": g["expected"], "chance": g["chance"] if g["n"] >= MIN_CASES_CHANCE else None,
                    "n": g["n"], "low": g["low"], "high": g["high"],
                    "basis": f"Based on {g['n']} past {what}"}
    return None


def annotate(site: str, coming_up: dict, audience: dict[str, float]) -> None:
    """Add expected bump and chance to each Coming up item (when the model has enough cases)."""
    model = _load(os.path.join(site, "data", "calibration", "model.json"), {})
    if not model:
        return
    for c in coming_up.get("derivatives", []):
        p = predict(model, {"kind": "derivative", "rel": c["rel"], "old_kind": c["old_kind"],
                            "usual": audience.get(c.get("old_title"))})
        if p:
            c["prediction"] = p
    for a in coming_up.get("anniversaries", []):
        p = predict(model, {"kind": "anniversary", "years": a["years"], "old_kind": a["kind"], "usual": a.get("audience")})
        if p:
            a["prediction"] = p


# ---------- back every year ----------

HOLIDAYS = {   # Wikidata items used as a work's genre or main subject
    "Q19809": "Christmas", "Q28026639": "Christmas", "Q1443316": "Christmas",
    "Q251868": "Halloween", "Q116918819": "Halloween", "Q2913791": "Thanksgiving", "Q13959": "Thanksgiving",
    "Q37587": "Valentine's Day", "Q11269": "New Year's Eve", "Q21196": "Easter", "Q130881": "Hanukkah",
}
HOLIDAY_CACHE = os.path.join(radar.CACHE, "seasonal_holiday_works.json")


def holiday_works(watch: dict[str, dict]) -> dict[str, str]:
    """{watched title: holiday} for works whose genre or subject is a holiday."""
    found = _load(HOLIDAY_CACHE, None)
    if found is None or time.time() - os.path.getmtime(HOLIDAY_CACHE) > 30 * 86400:
        found = {}
        vals = " ".join(f"wd:{q}" for q in HOLIDAYS)
        try:
            for r in radar.sparql(f"SELECT DISTINCT ?w ?h WHERE {{ VALUES ?h {{ {vals} }} ?w wdt:P136|wdt:P921 ?h . }}"):
                found[radar.qid(radar.v(r, "w"))] = HOLIDAYS[radar.qid(radar.v(r, "h"))]
            _save(HOLIDAY_CACHE, found)
        except Exception as e:
            log(f"      holiday lookup failed: {e}")
    return {title: found[w["qid"]] for title, w in watch.items() if w["qid"] in found}


def _yearly_peaks(series: dict[dt.date, int], today: dt.date) -> list[tuple[dt.date, float]]:
    """For each of the last 3 full years (ending yesterday): the 7-day peak and its size vs that year's median."""
    out = []
    for k in range(3):
        end = today - dt.timedelta(days=1 + 365 * k)
        days = [end - dt.timedelta(days=i) for i in range(365)][::-1]
        vals = [series.get(d, 0) for d in days]
        if sum(1 for v in vals if v > 0) < 300:
            continue
        med = max(statistics.median(vals), 1)
        wk = [sum(vals[i:i + 7]) / 7 for i in range(len(vals) - 6)]
        i = max(range(len(wk)), key=wk.__getitem__)
        out.append((days[i + 3], wk[i] / med))
    return out


def _next_date(day: dt.date, today: dt.date) -> dt.date:
    try:
        nxt = day.replace(year=today.year)
    except ValueError:
        nxt = dt.date(today.year, 3, 1)
    if nxt < today - dt.timedelta(days=7):
        try:
            nxt = nxt.replace(year=today.year + 1)
        except ValueError:
            nxt = dt.date(today.year + 1, 3, 1)
    return nxt


def seasonal(site: str, project: str, watch: dict[str, dict], audience: dict[str, float],
             candidates: set[str], budget_s: float = 6 * 60, horizon: int = forecast.HORIZON_DAYS) -> list[dict]:
    """Works that peak around the same date every year, due back in the next six months.
    A work qualifies if its yearly peak was 2.5x+ its usual level in at least 2 of the last 3 years,
    within two weeks of the same date. Results per work are kept for 30 days."""
    path = os.path.join(site, "data", "calibration", "seasonal.json")
    store = _load(path, {})
    today = dt.date.today()
    hol = holiday_works(watch)
    titles = [t for t in sorted(set(candidates) | set(hol), key=lambda t: -audience.get(t, 0)) if t in watch]
    t0 = time.time()
    for title in titles:
        s = store.get(title)
        if s and today.toordinal() - dt.date.fromisoformat(s["checked"]).toordinal() < 30:
            continue
        if time.time() - t0 > budget_s:
            break
        series = radar.daily_views(project, title, today - dt.timedelta(days=3 * 365 + 7), today - dt.timedelta(days=1))
        if series is None:
            continue
        peaks = _yearly_peaks(series, today)
        strong = [(d, r) for d, r in peaks if r >= 2.5]
        rec = {"checked": today.isoformat(), "years": len(peaks), "regular": False}
        if len(strong) >= 2:
            ref = sorted(d.replace(year=2001) if not (d.month == 2 and d.day == 29) else dt.date(2001, 3, 1) for d, _ in strong)
            mid = ref[len(ref) // 2]
            close = [r for (d, r), x in zip(strong, ref) if abs((x - mid).days) <= 14 or abs((x - mid).days) >= 351]
            if len(close) >= 2:
                rec.update(regular=True, day=mid.strftime("%m-%d"), expected=round(statistics.median(close), 1),
                           hits=len(close))
        store[title] = rec
    _save(path, store)
    out = []
    for title, rec in store.items():
        if not rec.get("regular") or title not in watch:
            continue
        m, d = map(int, rec["day"].split("-"))
        nxt = _next_date(dt.date(2001, m, d), today)
        if nxt > today + dt.timedelta(days=horizon):
            continue
        w = watch[title]
        out.append({"title": title, "label": title.replace("_", " "), "qid": w["qid"], "kind": w["kind"],
                    "release": w.get("release", ""), "date": nxt.isoformat(), "holiday": hol.get(title),
                    "audience": round(audience.get(title, 0)),
                    "prediction": {"expected": rec["expected"], "chance": round(rec["hits"] / max(rec["years"], 1), 2),
                                   "n": rec["years"], "basis": f"Back {rec['hits']} of the last {rec['years']} years"}})
    out.sort(key=lambda x: (x["date"], -x["audience"]))
    log(f"      back every year: {len(out)} regulars due in the next {horizon} days ({len(titles)} candidates)")
    return out
