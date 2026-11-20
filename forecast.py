"""
"Coming up": older works likely to get attention soon. Forward-looking, which is
what rights holders, retailers and programmers need most.

  upcoming derivatives  sequels, adaptations, remakes and new series entries due in the
                        next ~5 months, whose source is a notable older work
                        (Wikidata, rebuilt weekly)
  anniversaries         round-number release anniversaries in the next 60 days for the
                        ~35k watched works, ranked by their usual daily audience
                        (computed locally; no extra queries)

Every forecast is saved with the run, so later runs can check whether it came true
(see evaluate.py).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics
import sys
import time

import radar

FORECAST_CACHE = os.path.join(radar.CACHE, "forecast_derivatives.json")

NEW_CLASSES = [
    ("film", "wd:Q11424"), ("film", "wd:Q24869"), ("TV series", "wd:Q5398426"),
    ("video game", "wd:Q7889"), ("book", "wd:Q7725634"), ("album", "wd:Q482994"),
]
RELATIONS = [
    ("adaptation of", "?new wdt:P144 ?old ."),
    ("sequel to", "?new wdt:P155 ?old ."),
    ("remake of", "?new wdt:P5059 ?old ."),
    ("new entry in the series of", "?new wdt:P179 ?s . ?old wdt:P179 ?s . FILTER(?old != ?new)"),
]


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def upcoming_derivatives(watch: dict[str, dict], horizon: int = 150, max_age_days: float = 7) -> list[dict]:
    """New works due soon that are based on, follow, remake or continue a watched older work."""
    today = dt.date.today()
    if os.path.exists(FORECAST_CACHE) and time.time() - os.path.getmtime(FORECAST_CACHE) < max_age_days * 86400:
        with open(FORECAST_CACHE) as f:
            rows = json.load(f)
    else:
        rows = []
        lo, hi = today.isoformat(), (today + dt.timedelta(days=horizon)).isoformat()
        for kind, cls in NEW_CLASSES:
            for rel, pat in RELATIONS:
                q = f"""
                SELECT DISTINCT ?new ?newLabel ?date ?old WHERE {{
                  ?new wdt:P31 {cls}; wdt:P577 ?date .
                  FILTER(?date > "{lo}T00:00:00Z"^^xsd:dateTime && ?date < "{hi}T00:00:00Z"^^xsd:dateTime)
                  {pat}
                  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
                }}"""
                try:
                    res = radar.sparql(q)
                except Exception as e:
                    log(f"      forecast query failed ({kind}, {rel}): {e}")
                    radar.HEALTH["lookups_failed"] += 1
                    continue
                for r in res:
                    rows.append({"new": radar.qid(radar.v(r, "new")),
                                 "new_label": radar.nice_label(radar.v(r, "newLabel")),
                                 "new_kind": kind, "date": radar.v(r, "date")[:10], "rel": rel,
                                 "old": radar.qid(radar.v(r, "old"))})
        if rows:
            os.makedirs(radar.CACHE, exist_ok=True)
            with open(FORECAST_CACHE, "w") as f:
                json.dump(rows, f)
    by_qid = {w["qid"]: (title, w) for title, w in watch.items()}
    out, seen = [], set()
    for r in rows:
        if r["old"] not in by_qid or r["date"] < today.isoformat():
            continue
        key = (r["new"], r["old"])
        if key in seen:
            continue
        seen.add(key)
        title, w = by_qid[r["old"]]
        out.append({**r, "old_title": title, "old_label": title.replace("_", " "), "old_kind": w["kind"],
                    "old_release": w["release"], "old_sitelinks": w.get("sitelinks", 0)})
    # A new series entry links to every earlier entry: keep the 4 best-known per new work.
    out.sort(key=lambda r: (r["date"], -r["old_sitelinks"]))
    per_new: dict[str, int] = {}
    kept = []
    for r in out:
        per_new[r["new"]] = per_new.get(r["new"], 0) + 1
        if per_new[r["new"]] <= 4:
            kept.append(r)
    return kept


def anniversaries(watch: dict[str, dict], audience: dict[str, float], horizon: int = 60,
                  top: int = 60) -> list[dict]:
    """Round-number anniversaries coming up. Jan 1 dates are skipped: in Wikidata
    they usually mean only the year is known."""
    today = dt.date.today()
    out = []
    for title, w in watch.items():
        try:
            r = dt.date.fromisoformat(w["release"])
        except ValueError:
            continue
        if (r.month, r.day) == (1, 1):
            continue
        for years in sorted(radar.ANNIVERSARIES):
            try:
                ann = r.replace(year=r.year + years)
            except ValueError:   # 29 Feb
                ann = dt.date(r.year + years, 3, 1)
            if today <= ann <= today + dt.timedelta(days=horizon):
                out.append({"title": title, "label": title.replace("_", " "), "qid": w["qid"],
                            "kind": w["kind"], "release": w["release"], "years": years,
                            "date": ann.isoformat(), "audience": round(audience.get(title, 0)),
                            "sitelinks": w.get("sitelinks", 0)})
    # Rank by usual audience; bigger anniversaries get a boost.
    out.sort(key=lambda a: -(a["audience"] or a["sitelinks"]) * (1 + a["years"] / 50))
    return out[:top]


def audience_from_bulk(days_data: list[dict]) -> dict[str, float]:
    """Median daily views per watched title over the stored bulk days."""
    if not days_data:
        return {}
    titles = set().union(*days_data)
    return {t: statistics.median([d.get(t, [0, 0])[0] for d in days_data]) for t in titles}
