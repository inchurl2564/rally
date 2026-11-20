"""
How often is the radar right? Published on the site's Accuracy tab.

  forecasts       For each "coming up" item whose date has passed, did the older work's
                  attention actually rise (≥ 2× its usual level within a week of the
                  date)? Checked once, stored, and accumulated across runs.
  corroboration   For explained spikes, did independent evidence (edit bursts, edit
                  summaries, news) agree with the Wikidata trigger?
  persistence     How many daily runs revivals stay on the radar.
  reader reports  GitHub issues readers filed with the "Report a correction" link,
                  once a maintainer labels them `verified-correct` or `verified-wrong`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics

import radar

MAX_CHECKS_PER_RUN = 40


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def check_forecasts(site: str, project: str) -> dict:
    ddir = os.path.join(site, "data")
    path = os.path.join(ddir, "forecast_checks.json")
    checks = _load(path, {})
    today = dt.date.today()
    rdir = os.path.join(ddir, "runs")
    pending = {}
    for f in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []:
        run = _load(os.path.join(rdir, f), {})
        cu = run.get("coming_up", {})
        for kind, items in (("derivative", cu.get("derivatives", [])), ("anniversary", cu.get("anniversaries", [])),
                            ("seasonal", cu.get("seasonal", []))):
            for it in items:
                title = it.get("old_title") or it.get("title")
                key = f"{kind}|{title}|{it['date']}"
                d = dt.date.fromisoformat(it["date"])
                if key not in checks and today - dt.timedelta(days=60) <= d <= today - dt.timedelta(days=8):
                    pending[key] = (kind, title, d, it)
    for key, (kind, title, d, it) in list(pending.items())[:MAX_CHECKS_PER_RUN]:
        series = radar.daily_views(project, title, d - dt.timedelta(days=60), d + dt.timedelta(days=7))
        if series is None:
            continue
        base = [series.get(d - dt.timedelta(days=i), 0) for i in range(14, 61)]
        near = [series.get(d + dt.timedelta(days=i), 0) for i in range(-7, 8)]
        med = max(statistics.median(base), 1)
        best3 = max(sum(near[i:i + 3]) / 3 for i in range(len(near) - 2))
        ratio = round(best3 / med, 1)
        checks[key] = {"kind": kind, "title": title, "date": d.isoformat(), "ratio": ratio,
                       "hit": ratio >= 2.0, "label": it.get("old_label") or it.get("label"),
                       "detail": (f"{it['rel']} {it['new_label']}" if kind == "derivative"
                                  else f"{it['years']}th anniversary" if kind == "anniversary"
                                  else "back every year"),
                       # Kept for "expected bump" research: what kind of release, how old the original,
                       # and the Wikidata IDs to look up series order later.
                       "rel": it.get("rel"), "new_kind": it.get("new_kind"), "new": it.get("new"),
                       "old": it.get("old") or it.get("qid"), "old_kind": it.get("old_kind") or it.get("kind"),
                       "old_year": (it.get("old_release") or it.get("release") or "")[:4],
                       "years": it.get("years"), "audience": it.get("audience"), "baseline": round(med),
                       # what we predicted at the time, so the result can be shown next to it
                       "predicted": {k: (it.get("prediction") or {}).get(k) for k in ("expected", "chance")} if it.get("prediction") else None}
    with open(path, "w") as f:
        json.dump(checks, f, separators=(",", ":"))
    return checks


def summarize(site: str, project: str) -> dict:
    ddir = os.path.join(site, "data")
    checks = check_forecasts(site, project)

    def rate(items):
        n = len(items)
        hits = sum(1 for x in items if x["hit"])
        return {"checked": n, "hits": hits, "rate": round(hits / n, 2) if n else None}

    fc = list(checks.values())
    forecasts = {"all": rate(fc),
                 "derivative": rate([x for x in fc if x["kind"] == "derivative"]),
                 "anniversary": rate([x for x in fc if x["kind"] == "anniversary"]),
                 "seasonal": rate([x for x in fc if x["kind"] == "seasonal"]),
                 "recent": sorted(fc, key=lambda x: x["date"], reverse=True)[:30]}

    # Corroboration and persistence from the archive of runs.
    rdir = os.path.join(ddir, "runs")
    runs = sorted(os.listdir(rdir)) if os.path.isdir(rdir) else []
    corr: dict[str, list[bool]] = {}
    appearances: dict[str, list[str]] = {}
    for f in runs:
        run = _load(os.path.join(rdir, f), {})
        for r in run.get("results", []):
            appearances.setdefault(r["qid"], []).append(f[:-5])
            if r.get("corroborated") is not None and r.get("triggers"):
                corr.setdefault(r["triggers"][0]["type"], []).append(r["corroborated"])
    corroboration = {t: {"checked": len(v), "agree": sum(v), "rate": round(sum(v) / len(v), 2)}
                     for t, v in corr.items() if v}
    allv = [b for v in corr.values() for b in v]
    corroboration["all"] = {"checked": len(allv), "agree": sum(allv),
                            "rate": round(sum(allv) / len(allv), 2) if allv else None}

    def longest_streak(dates):
        ds = sorted(dt.date.fromisoformat(x) for x in set(dates))
        best = cur = 1
        for a, b in zip(ds, ds[1:]):
            cur = cur + 1 if (b - a).days == 1 else 1
            best = max(best, cur)
        return best

    streaks = [longest_streak(v) for v in appearances.values()]
    persistence = {"runs": len(runs), "works_seen": len(appearances),
                   "median_days": statistics.median(streaks) if streaks else None,
                   "share_over_7_days": round(sum(s > 7 for s in streaks) / len(streaks), 2) if streaks else None}

    feedback = _load(os.path.join(ddir, "feedback.json"), {"correct": 0, "wrong": 0, "open": 0})
    out = {"generated": dt.date.today().isoformat(), "forecasts": forecasts,
           "corroboration": corroboration, "persistence": persistence, "reader_reports": feedback}
    with open(os.path.join(ddir, "accuracy.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    return out
