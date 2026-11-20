"""
The ripple effect: is a spike riding a bigger story about something connected to it?

When news breaks about a person (a conviction, a casting announcement) or a franchise
(a new film, a reboot), their own Wikipedia page spikes first and hardest, and older
works connected to them rise in its wake. Wikidata won't record that event for days,
if ever, but the pageviews show it straight away.

For each unexplained spike we look up what's connected to the work — stars and
creators, franchise, series, characters, source material — and check whether any of
their pages jumped at the same time.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import math
import statistics
import sys
import time

import radar

LINK_PROPS = {
    **{p: role for p, (role, _) in radar.CREDIT_PROPS.items()},
    "P8345": "franchise", "P179": "series", "P674": "character", "P144": "source material",
}
PEOPLE_PER_WORK = 12      # best-known credited people checked per work
MIN_RATIO = 4.0           # the connected page must jump at least this much…
MIN_VIEWS = 300           # …and reach at least this many views/day
MAX_WORKS = 120          # strongest unexplained spikes checked per run
BUDGET_S = 20 * 60       # time budget for fetching connected pages


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def connected(works: list[dict], batch: int = 6) -> dict[str, list[dict]]:
    """{work qid: [{"qid","name","title","relation","sitelinks"}]} — only things with an enwiki article."""
    props = " ".join(f"wdt:{p}" for p in LINK_PROPS)
    out: dict[str, list[dict]] = {}
    for i in range(0, len(works), batch):
        chunk = works[i:i + batch]
        values = " ".join(f"wd:{w['qid']}" for w in chunk)
        q = f"""
        SELECT ?item ?prop ?e ?eLabel ?article ?sl WHERE {{
          VALUES ?item {{ {values} }}
          VALUES ?prop {{ {props} }}
          ?item ?prop ?e .
          ?article schema:about ?e; schema:isPartOf <https://en.wikipedia.org/> .
          OPTIONAL {{ ?e wikibase:sitelinks ?sl }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        try:
            rows = radar.sparql(q)
        except Exception as e:
            log(f"      connections lookup failed for a batch: {e}")
            radar.HEALTH["lookups_failed"] += 1
            continue
        for r in rows:
            item = radar.qid(radar.v(r, "item"))
            out.setdefault(item, []).append({
                "qid": radar.qid(radar.v(r, "e")), "name": radar.nice_label(radar.v(r, "eLabel")),
                "title": radar.urllib.parse.unquote(radar.v(r, "article").split("/wiki/", 1)[1]),
                "relation": LINK_PROPS[radar.qid(radar.v(r, "prop"))], "sitelinks": int(radar.v(r, "sl") or 0)})
    # Adaptations, sequels and remakes OF the work or of one of its parts (a film of book 1
    # of a series): their own pages spike when they're announced or released.
    for i in range(0, len(works), batch):
        values = " ".join(f"wd:{w['qid']}" for w in works[i:i + batch])
        q = f"""
        SELECT DISTINCT ?item ?e ?eLabel ?article ?sl WHERE {{
          VALUES ?item {{ {values} }}
          {{ ?e wdt:P144|wdt:P155|wdt:P5059 ?item . }}
          UNION {{ ?part wdt:P179|wdt:P361 ?item . ?e wdt:P144 ?part . }}
          UNION {{ ?item wdt:P527 ?part . ?e wdt:P144 ?part . }}
          ?article schema:about ?e; schema:isPartOf <https://en.wikipedia.org/> .
          OPTIONAL {{ ?e wikibase:sitelinks ?sl }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        try:
            rows = radar.sparql(q)
        except Exception as e:
            log(f"      adaptations lookup failed for a batch: {e}")
            continue
        for r in rows:
            out.setdefault(radar.qid(radar.v(r, "item")), []).append({
                "qid": radar.qid(radar.v(r, "e")), "name": radar.nice_label(radar.v(r, "eLabel")),
                "title": radar.urllib.parse.unquote(radar.v(r, "article").split("/wiki/", 1)[1]),
                "relation": "sequel or adaptation", "sitelinks": int(radar.v(r, "sl") or 0)})
    # People credited on several spiking works go first (one story behind many spikes),
    # then the best known.
    shared: dict[str, int] = {}
    for ents in out.values():
        for q in {e["qid"] for e in ents}:
            shared[q] = shared.get(q, 0) + 1
    for item, ents in out.items():
        seen, people, other = set(), [], []
        for e in sorted(ents, key=lambda e: (-shared[e["qid"]], -e["sitelinks"])):
            if e["qid"] in seen:
                continue
            seen.add(e["qid"])
            (other if e["relation"] in ("franchise", "series", "character", "source material", "sequel or adaptation") else people).append(e)
        out[item] = other + people[:PEOPLE_PER_WORK]
    return out


def jump(series: dict[dt.date, int], around: dt.date) -> tuple[float, int, dt.date | None]:
    """How far a page jumped within 3 days of `around`, vs its median over the month before."""
    base = [series.get(around - dt.timedelta(days=i), 0) for i in range(7, 41)]
    med = max(statistics.median(base), 20)
    best, best_day = 0.0, None
    for i in range(-3, 4):
        d = around + dt.timedelta(days=i)
        two = (series.get(d, 0) + series.get(d + dt.timedelta(days=1), 0)) / 2
        if two > best:
            best, best_day = two, d
    return best / med, int(best), best_day


_views_cache: dict[str, dict] = {}


def _views(project, title, start, end):
    if title not in _views_cache:
        _views_cache[title] = radar.daily_views(project, title, start, end) or {}
    return _views_cache[title]


def ripple(project: str, works: list[dict], end: dt.date) -> None:
    """Attach r["ripple"] = strongest connected page that jumped with the work, if any."""
    if not works:
        return
    spiking = {w["qid"] for w in works}   # another spiking work is a fellow traveller, not a cause
    works = sorted(works, key=lambda w: -w.get("score_hint", 0))[:MAX_WORKS]
    links = connected(works)
    start = min(w["spike_start"] for w in works) - dt.timedelta(days=45)
    # Fetch every connected page once, two at a time, within a time budget.
    titles = list(dict.fromkeys(e["title"] for w in works for e in links.get(w["qid"], [])
                                if e["qid"] not in spiking and e["title"] not in _views_cache))
    deadline = time.monotonic() + BUDGET_S
    def fetch(t):
        if time.monotonic() < deadline:
            _views(project, t, start, end)
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(fetch, titles))
    if time.monotonic() >= deadline:
        log(f"      ripple: time budget reached; {sum(t in _views_cache for t in titles)} of {len(titles)} pages fetched")
    checked = 0
    for w in works:
        best = None
        for e in links.get(w["qid"], []):
            if e["qid"] in spiking or e["title"] not in _views_cache:
                continue
            series = _views_cache[e["title"]]
            checked += 1
            ratio, peak, day = jump(series, w["spike_start"])
            # A cause should be bigger news than its effect.
            if ratio >= MIN_RATIO and peak >= max(MIN_VIEWS, w.get("peak", 0)):
                score = ratio * math.log10(peak)
                if not best or score > best["score"]:
                    best = {**e, "ratio": round(ratio, 1), "peak": peak, "date": day.isoformat(), "score": score}
        if best:
            best.pop("score")
            w["ripple"] = best
    log(f"      ripple: {sum(1 for w in works if w.get('ripple'))} of {len(works)} spikes ride a connected story "
        f"({checked} connected pages checked)")


def person_jump(project: str, title: str, around: dt.date, end: dt.date) -> dict | None:
    series = _views(project, title, around - dt.timedelta(days=45), end)
    ratio, peak, day = jump(series, around)
    if ratio >= MIN_RATIO and peak >= MIN_VIEWS:
        return {"ratio": round(ratio, 1), "peak": peak, "date": day.isoformat()}
    return None
