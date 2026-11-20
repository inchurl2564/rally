"""
The archive: a permanent page for every title The Rallyback has ever caught coming back,
plus the searchable index, leaderboards and the weekly roundup. Built each night from the
permanent record (site/data/history), today's edition and the forecast checks.

  site/data/works/<qid>.json   one title: every comeback (dates, size, causes), its chart,
                               what's coming for it, related titles
  site/data/works/index.json   every title, compact, for "Has it come back before?" search
  site/w/<qid>.html            a tiny share page per title (title, description and picture
                               for link previews), which opens the title page on the site
  site/data/leaders.json       biggest comebacks this month and year; decades and franchises
                               that are hot this week
  site/data/weekly/<week>.json "This week in comebacks", one file per ISO week
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import urllib.parse

EPISODE_GAP = 7          # days off the list before a return counts as a new comeback
UNEXPLAINED = {"unexplained", "weak link", "lookup failed", "common thread"}
SET_ASIDE = {"seasonal", "automated?", "front page"}


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


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def load_history(site: str) -> dict:
    """All months of the permanent record merged: works, names, and every day's rows (as dicts)."""
    hdir = os.path.join(site, "data", "history")
    works, names, days = {}, {}, {}
    for f in sorted(os.listdir(hdir)) if os.path.isdir(hdir) else []:
        m = _load(os.path.join(hdir, f), {})
        fields = m.get("fields", [])
        works.update(m.get("works", {}))
        names.update(m.get("names", {}))
        for run, rows in m.get("days", {}).items():
            days[run] = {q: dict(zip(fields, row)) for q, row in rows.items()}
    return {"works": works, "names": names, "days": days}


def episodes_of(qid: str, days: dict, runs: list[str]) -> list[dict]:
    """Group the days a title was on the list into separate comebacks."""
    seen = [(r, days[r][qid]) for r in runs if qid in days[r]]
    out, cur = [], None
    for run, row in seen:
        if cur and (_d(run) - _d(cur["last_seen"])).days <= EPISODE_GAP:
            cur["rows"].append((run, row))
            cur["last_seen"] = run
        else:
            cur = {"first_seen": run, "last_seen": run, "rows": [(run, row)]}
            out.append(cur)
    eps = []
    for e in out:
        rows = [r for _, r in e["rows"]]
        best = max(rows, key=lambda r: (r.get("rally_score") or 0, r.get("lift") or 0))
        eps.append({"start": min(str(r.get("spike_start") or e["first_seen"]) for r in rows)[:10],
                    "first_seen": e["first_seen"], "last_seen": e["last_seen"], "days": len(rows),
                    "peak_lift": max(r.get("lift") or 0 for r in rows), "score": best.get("rally_score"),
                    "verdict": best.get("verdict"), "causes": best.get("causes") or []})
    return eps


def _cause_text(c: list, names: dict, notes: dict) -> str | None:
    kind, qid, detail, date = (c + [None] * 4)[:4]
    who = names.get(qid) if qid else None
    when = f" ({dt.date.fromisoformat(date):%b %-d, %Y})" if date else ""
    if kind == "death" and who:
        return f"{who}{f', {detail},' if detail else ''} died{when}"
    if kind in ("derivative", "same-creator") and who:
        return f"{(detail or 'New release')[0].upper()}{(detail or 'new release')[1:]}: {who}{when}"
    if kind == "anniversary":
        return f"{(detail or 'Anniversary')[0].upper()}{(detail or 'anniversary')[1:]}{when}"
    if kind in ("ripple", "common thread") and who:
        return f"News about {who}{f' ({detail})' if detail and kind == 'ripple' else ''}{when}"
    if kind == "note":
        return notes.get(detail)
    if kind == "coverage" and detail:
        return f"Likely cause from news and edits: {detail}"
    return None


def _causes(eps_causes: list, names: dict, notes: dict) -> list[str]:
    seen, out = set(), []
    order = {"note": 0, "death": 1, "derivative": 2, "same-creator": 3, "ripple": 4, "coverage": 5, "anniversary": 6, "common thread": 7}
    for c in sorted(eps_causes, key=lambda c: order.get(c[0], 9)):
        t = _cause_text(c, names, notes)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:4]


def build(site: str, site_url: str = "") -> None:
    hist = load_history(site)
    runs = sorted(hist["days"])
    if not runs:
        return
    latest = _load(os.path.join(site, "data", "latest.json"), {})
    R = {r["qid"]: r for r in latest.get("results", [])}
    names, works = hist["names"], hist["works"]
    notes = {n["id"]: n.get("note") for n in _load("annotations.json", []) if isinstance(n, dict) and n.get("id")}
    wdir = os.path.join(site, "data", "works")
    today_run = runs[-1]
    cu = latest.get("coming_up", {})
    coming: dict[str, list] = {}
    for c in cu.get("derivatives", []):
        coming.setdefault(c["old"], []).append({"type": "release", "date": c["date"], "text": f"{c['rel']} {c['new_label']}",
                                                 "prediction": c.get("prediction")})
    for a in cu.get("anniversaries", []):
        coming.setdefault(a["qid"], []).append({"type": "anniversary", "date": a["date"], "text": f"{a['years']}th anniversary",
                                                "prediction": a.get("prediction")})
    for a in cu.get("seasonal", []):
        coming.setdefault(a["qid"], []).append({"type": "seasonal", "date": a["date"],
                                                "text": "back every year" + (f" ({a['holiday']})" if a.get("holiday") else ""),
                                                "prediction": a.get("prediction")})
    # Who is related to whom: same franchise, or the same person / release behind a comeback.
    by_franchise: dict[str, set] = {}
    by_cause: dict[str, set] = {}
    for q, w in works.items():
        for f in (w[3] if len(w) > 3 else []) or []:
            by_franchise.setdefault(f, set()).add(q)
    for run in runs[-120:]:
        for q, row in hist["days"][run].items():
            for c in row.get("causes") or []:
                if c[1] and c[0] != "anniversary":
                    by_cause.setdefault(c[1], set()).add(q)

    index, written = [], 0
    for q, w in works.items():
        label, kind, year = w[0], w[1], w[2]
        fr = (w[3] if len(w) > 3 else []) or []
        eps = episodes_of(q, hist["days"], runs)
        if not eps:
            continue
        best = max((e["score"] or 0) for e in eps)
        index.append([q, label, str(year), kind, len(eps), eps[-1]["last_seen"], best])
        path = os.path.join(wdir, f"{q}.json")
        on_today = q in R
        if not on_today and q not in coming and os.path.exists(path):
            continue                                  # nothing new for this title tonight
        old = _load(path, {})
        r = R.get(q, {})
        rel: dict[str, str] = {}
        for f in fr:
            for o in by_franchise.get(f, ()):
                if o != q:
                    rel.setdefault(o, f"Also in {names.get(f, 'the same series')}")
        for e in eps[-2:]:
            for c in e["causes"]:
                if c[1] and c[0] != "anniversary":
                    for o in by_cause.get(c[1], ()):
                        if o != q:
                            rel.setdefault(o, f"Also back with {names.get(c[1], 'the same story')}")
        related = sorted(rel.items(), key=lambda kv: kv[0] not in R)[:8]        # titles back right now first
        doc = {
            "qid": q, "label": label, "kind": kind, "year": str(year),
            "title": r.get("title") or old.get("title"),
            "image": r.get("image") or old.get("image"), "image_of": r.get("image_of") if r else old.get("image_of"),
            "franchises": [{"qid": f, "name": names.get(f)} for f in fr if names.get(f)],
            "episodes": [{**{k: e[k] for k in ("start", "first_seen", "last_seen", "days", "peak_lift", "score", "verdict")},
                          "causes": _causes(e["causes"], names, notes)} for e in eps],
            "on_today": on_today,
            "spark": r.get("spark") or old.get("spark"), "spark_start": r.get("spark_start") or old.get("spark_start"),
            "baseline": r.get("baseline") or old.get("baseline"),
            "coming": sorted(coming.get(q, []), key=lambda x: x["date"]),
            "related": [{"qid": o, "label": works[o][0], "year": str(works[o][2]), "why": why} for o, why in related if o in works],
            "updated": today_run,
        }
        _save(path, doc)
        _stub(site, site_url, doc)
        written += 1
    index.sort(key=lambda x: (-x[4], -(x[6] or 0)))
    _save(os.path.join(wdir, "index.json"), {"fields": ["qid", "label", "year", "kind", "comebacks", "last_seen", "best_score"],
                                            "works": index, "updated": today_run})
    leaders(site, hist, runs)
    weekly(site, hist, runs, latest)
    log(f"      archive: {len(index)} titles ({written} pages updated)")


def _stub(site: str, site_url: str, doc: dict) -> None:
    """A tiny page per title so a shared link shows the title, a line and the picture, then opens the site."""
    eps = doc["episodes"]
    last = eps[-1]
    times = f"{len(eps)} comebacks" if len(eps) > 1 else "a comeback"
    why = (last["causes"] or ["Reason unknown yet"])[0]
    title = f"{doc['label']} ({doc['year']}) on The Rallyback"
    desc = f"{times.capitalize()} tracked. Latest: {last['peak_lift']}× its usual interest from {dt.date.fromisoformat(last['start']):%b %-d, %Y}. {why}."
    img = (f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(doc['image'])}?width=1200"
           if doc.get("image") else "")
    target = f"../?work={doc['qid']}"
    e = html.escape
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(title)}</title><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(desc)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="The Rallyback">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}">
{f'<meta property="og:image" content="{e(img)}"><meta name="twitter:card" content="summary_large_image">' if img else '<meta name="twitter:card" content="summary">'}
{f'<link rel="canonical" href="{e(site_url.rstrip("/"))}/w/{doc["qid"]}.html">' if site_url else ''}
<meta http-equiv="refresh" content="0; url={e(target)}">
</head><body><p><a href="{e(target)}">{e(title)}</a></p></body></html>
"""
    os.makedirs(os.path.join(site, "w"), exist_ok=True)
    with open(os.path.join(site, "w", f"{doc['qid']}.html"), "w") as f:
        f.write(page)


def _cause_key(causes: list) -> str | None:
    """The person or release behind a comeback, so one story isn't listed once per title."""
    for c in causes or []:
        if c[1] and c[0] not in ("anniversary",):
            return c[1]
        if c[0] == "note":
            return f"note:{c[2]}"
    return None


def _one_per_story(items: list[dict], n: int) -> list[dict]:
    """Keep the best title per cause; the rest are counted on it ('and 11 more')."""
    out, by_key = [], {}
    for it in items:
        k = it.pop("_key", None)
        if k and k in by_key:
            by_key[k]["more"] = by_key[k].get("more", 0) + 1
            continue
        if k:
            by_key[k] = it
        if len(out) < n:
            out.append(it)
    return out


def leaders(site: str, hist: dict, runs: list[str]) -> None:
    """Biggest comebacks this month and this year; decades and franchises hot this week."""
    works, names, days = hist["works"], hist["names"], hist["days"]
    end = _d(runs[-1])
    eps_all = []
    for q in works:
        for e in episodes_of(q, days, runs):
            eps_all.append((q, e))

    def top(since: dt.date, n=20):
        xs = [(q, e) for q, e in eps_all if _d(e["first_seen"]) >= since]
        xs.sort(key=lambda qe: (-(qe[1]["score"] or 0), -qe[1]["peak_lift"]))
        return _one_per_story([{"qid": q, "label": works[q][0], "year": str(works[q][2]), "kind": works[q][1], "score": e["score"],
                                "peak_lift": e["peak_lift"], "start": e["start"], "verdict": e["verdict"],
                                "_key": _cause_key(e["causes"])} for q, e in xs], n)

    week = [r for r in runs if (end - _d(r)).days < 7]
    before = [r for r in runs if 7 <= (end - _d(r)).days < 35]

    def decade_counts(rs):
        seen, c = set(), {}
        for r in rs:
            for q in days[r]:
                if q in works and q not in seen and str(works[q][2])[:3].isdigit():
                    seen.add(q)
                    d = f"{str(works[q][2])[:3]}0s"
                    c[d] = c.get(d, 0) + 1
        return c

    cw, cb = decade_counts(week), decade_counts(before)
    tw, tb = sum(cw.values()) or 1, sum(cb.values()) or 1
    decades = sorted([{"decade": d, "this_week": n, "share": round(n / tw, 3),
                       "usual_share": round(cb.get(d, 0) / tb, 3) if before else None} for d, n in cw.items()],
                     key=lambda x: -x["this_week"])
    fr: dict[str, set] = {}
    for r in week:
        for q in days[r]:
            for f in ((works.get(q) or [None] * 4)[3] if len(works.get(q) or []) > 3 else []) or []:
                fr.setdefault(f, set()).add(q)
    by_name: dict[str, set] = {}        # Wikidata sometimes has two items for one franchise: merge by name
    for f, qs in fr.items():
        if names.get(f):
            by_name.setdefault(names[f], set()).update(qs)
    franchises = sorted([{"name": n, "titles": len(qs),
                          "top": sorted(({"qid": q, "label": works[q][0]} for q in qs), key=lambda x: x["label"])[:5]}
                         for n, qs in by_name.items() if len(qs) >= 2], key=lambda x: -x["titles"])[:12]
    _save(os.path.join(site, "data", "leaders.json"), {
        "month": top(end.replace(day=1)), "year": top(end.replace(month=1, day=1)),
        "decades": decades, "franchises": franchises, "updated": runs[-1],
        "covers_from": runs[0]})


def weekly(site: str, hist: dict, runs: list[str], latest: dict) -> None:
    """'This week in comebacks' for the ISO week of the latest edition."""
    works, days = hist["works"], hist["days"]
    end = _d(runs[-1])
    y, w, _ = end.isocalendar()
    monday = end - dt.timedelta(days=end.weekday())
    wk_runs = [r for r in runs if monday <= _d(r) <= end]
    best: dict[str, dict] = {}
    for r in wk_runs:
        for q, row in days[r].items():
            if q in works and row.get("verdict") not in SET_ASIDE:
                if (row.get("rally_score") or 0) > (best.get(q, {}).get("rally_score") or -1):
                    best[q] = {**row, "run": r}
    ranked = sorted(best.items(), key=lambda kv: -(kv[1].get("rally_score") or 0))
    pick = lambda q, row: {"qid": q, "label": works[q][0], "year": str(works[q][2]), "kind": works[q][1],
                           "score": row.get("rally_score"), "lift": row.get("lift"), "verdict": row.get("verdict"),
                           "start": str(row.get("spike_start"))[:10], "_key": _cause_key(row.get("causes")),
                           "why": (_causes(row.get("causes") or [], hist["names"], notes) or [None])[0]}
    notes = {n["id"]: n.get("note") for n in _load("annotations.json", []) if isinstance(n, dict) and n.get("id")}
    top5 = _one_per_story([pick(q, row) for q, row in ranked if row.get("verdict") not in UNEXPLAINED], 5)
    mystery = next((pick(q, row) for q, row in ranked if row.get("verdict") in UNEXPLAINED), None)
    if mystery:
        mystery.pop("_key", None)
    cu = latest.get("coming_up", {})
    nxt = (end + dt.timedelta(days=8)).isoformat()
    soon = []
    for c in cu.get("derivatives", []):
        if end.isoformat() < c["date"] <= nxt:
            soon.append({"qid": c["old"], "label": c["old_label"], "date": c["date"], "what": f"{c['rel']} {c['new_label']}",
                         "prediction": c.get("prediction")})
    for a in cu.get("anniversaries", []) + cu.get("seasonal", []):
        if end.isoformat() < a["date"] <= nxt:
            soon.append({"qid": a["qid"], "label": a["label"], "date": a["date"],
                         "what": f"{a['years']}th anniversary" if a.get("years") else "back every year",
                         "prediction": a.get("prediction")})
    soon.sort(key=lambda x: -((x.get("prediction") or {}).get("expected") or 0))
    checks = _load(os.path.join(site, "data", "forecast_checks.json"), {})
    results = sorted([x for x in checks.values() if (end - dt.timedelta(days=14)).isoformat() <= x["date"] <= end.isoformat()],
                     key=lambda x: x["date"], reverse=True)[:8]
    # New comebacks each day of the week, by reason (for the week chart). The record's first
    # day has nothing to compare with, so it isn't counted as "new".
    reason = {"ripple": "news", "editor": "news", "coverage": "news", "derivative": "release", "same-creator": "release",
              "unexplained": "unexplained", "weak link": "unexplained", "lookup failed": "unexplained",
              "common thread": "unexplained", "death": "memoriam", "anniversary": "anniversary"}
    per_day = []
    for i in range(7):
        day = (monday + dt.timedelta(days=i)).isoformat()
        prev = [r for r in runs if r < day]
        if day not in days:
            per_day.append({"date": day, "edition": False})
            continue
        if not prev:
            per_day.append({"date": day, "edition": True, "first": True})
            continue
        before = set(days[prev[-1]])
        groups: dict[str, list] = {}
        for q, row in days[day].items():
            k = reason.get(row.get("verdict"))
            if k and q not in before and q in works:
                groups.setdefault(k, []).append((row.get("rally_score") or 0, works[q][0]))
        per_day.append({"date": day, "edition": True,
                        "counts": {k: len(v) for k, v in groups.items()},
                        "titles": {k: [t for _, t in sorted(v, reverse=True)[:5]] for k, v in groups.items()}})
    key = f"{y}-W{w:02d}"
    doc = {"week": key, "from": monday.isoformat(), "to": (monday + dt.timedelta(days=6)).isoformat(), "updated": runs[-1],
           "editions": len(wk_runs), "comebacks": len(best), "top": top5, "mystery": mystery,
           "coming": soon[:6], "results": results, "days": per_day}
    wdir = os.path.join(site, "data", "weekly")
    _save(os.path.join(wdir, f"{key}.json"), doc)
    idx = sorted({f[:-5] for f in os.listdir(wdir) if f.endswith(".json") and f != "index.json"}, reverse=True)
    _save(os.path.join(wdir, "index.json"), idx)
