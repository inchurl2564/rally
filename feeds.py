"""
Alerts: Atom feeds and a daily email digest.

  site/feeds/*.xml   Atom feeds (any feed reader, or an RSS-to-email service):
                     all, unexplained (journalists), coming-up, and one per medium.
                     Each feed item is a *new* finding: a work not on the radar the
                     previous day, a new shared trigger or common thread.
  site/data/digest.md  Markdown digest the workflow posts as a GitHub issue. Anyone who
                     watches the repo (Watch → Custom → Issues) gets it by email.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re

FEEDS = {
    "all": ("Rally: all new comebacks", lambda e: True),
    "unexplained": ("Rally: unexplained comebacks",
                    lambda e: e["verdict"] in ("unexplained", "common thread", "coverage") or e["kind_of"] == "thread"),
    "coming-up": ("Rally: coming up", lambda e: e["kind_of"] == "forecast"),
    "film-tv": ("Rally: film & TV", lambda e: e.get("medium") in ("film", "TV series")),
    "music": ("Rally: music", lambda e: e.get("medium") in ("song", "album", "musical")),
    "games": ("Rally: video games", lambda e: e.get("medium") == "video game"),
    "books": ("Rally: books & comics", lambda e: e.get("medium") in ("book", "manga/comic")),
}
KEEP = 300


def _x(s):
    return html.escape(str(s), quote=True)


def _entries_for_run(data: dict, prev: dict | None, site_url: str, labels: dict) -> list[dict]:
    run = data["meta"]["window_end"]
    prev_q = {r["qid"] for r in (prev or {}).get("results", [])}
    prev_events = {t["qid"] for t in (prev or {}).get("shared_triggers", [])} | \
                  {t["qid"] for t in (prev or {}).get("common_threads", [])}
    prev_fc = {(c.get("new"), c.get("old")) for c in (prev or {}).get("coming_up", {}).get("derivatives", [])}
    by_q = {r["qid"]: r for r in data["results"]}
    out = []
    for r in data["results"]:
        if r["qid"] in prev_q or r["verdict"] in ("seasonal", "automated?", "front page"):
            continue
        why = r["triggers"][0]["text"] if r["triggers"] else (
            f"Likely cause from coverage: {r['cause']}" if r.get("cause") else "No recorded cause yet")
        stage = f" · {r['stage']}" if r.get("stage") else ""
        out.append({"id": f"work-{r['qid']}-{r['spike_start']}", "kind_of": "work", "verdict": r["verdict"],
                    "medium": r["kind"], "date": run,
                    "title": f"{r['label']} ({r['release_year']}) is back: {r['lift']}× usual attention",
                    "summary": f"{labels.get(r['verdict'], r['verdict'])}{stage}. {why}. "
                               f"Spike began {r['spike_start']}; usual {r['baseline']:,} views/day.",
                    "link": f"{site_url}?run={run}#w-{r['qid']}"})
    for t in data.get("shared_triggers", []):
        if t["qid"] in prev_events:
            continue
        names = ", ".join(by_q[q]["label"] for q in t["works"] if q in by_q)
        out.append({"id": f"shared-{t['qid']}-{run}", "kind_of": "shared", "verdict": "shared", "date": run,
                    "title": f"{len(t['works'])} older works are back: " + ", ".join(by_q[q]["label"] for q in t["works"][:3] if q in by_q)
                             + f"{', …' if len(t['works']) > 3 else ''} ({t['text']})",
                    "summary": names, "link": f"{site_url}?run={run}"})
    for t in data.get("common_threads", []):
        if t["qid"] in prev_events:
            continue
        names = ", ".join(by_q[w["qid"]]["label"] for w in t["works"] if w["qid"] in by_q)
        out.append({"id": f"thread-{t['qid']}-{t['around']}", "kind_of": "thread", "verdict": "common thread",
                    "date": run, "title": f"{len(t['works'])} works with {t['name']} are back at once, from {t['around']}",
                    "summary": f"{names}. {t.get('cause') and 'Likely cause: ' + t['cause'] + '.' or 'No recorded cause.'}",
                    "link": f"{site_url}?run={run}"})
    for c in data.get("coming_up", {}).get("derivatives", []):
        if (c["new"], c["old"]) in prev_fc:
            continue
        out.append({"id": f"fc-{c['new']}-{c['old']}", "kind_of": "forecast", "verdict": "forecast",
                    "medium": c["old_kind"], "date": run,
                    "title": f"{re.sub(r' [(][^)]*[)]$', '', c['old_label'])} ({c['old_release'][:4]}) is due for a comeback",
                    "summary": f"{c['new_label']}, {c['rel']} it, arrives {c['date']}.",
                    "link": f"{site_url}?run={run}&tab=coming"})
    return out


def _atom(name: str, title: str, entries: list[dict], site_url: str) -> str:
    updated = (entries[0]["date"] if entries else dt.date.today().isoformat()) + "T06:00:00Z"
    items = "".join(f"""
  <entry>
    <id>{_x(site_url)}#{_x(e['id'])}</id>
    <title>{_x(e['title'])}</title>
    <link href="{_x(e['link'])}"/>
    <updated>{_x(e['date'])}T06:00:00Z</updated>
    <summary>{_x(e['summary'])}</summary>
  </entry>""" for e in entries)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{_x(title)}</title>
  <id>{_x(site_url)}feeds/{name}.xml</id>
  <link rel="self" href="{_x(site_url)}feeds/{name}.xml"/>
  <link href="{_x(site_url)}"/>
  <updated>{updated}</updated>
  <author><name>Rally</name></author>{items}
</feed>
"""


def write(site: str, data: dict, prev: dict | None, site_url: str, labels: dict) -> list[dict]:
    store = os.path.join(site, "data", "feed_entries.json")
    try:
        with open(store) as f:
            old = json.load(f)
    except (OSError, json.JSONDecodeError):
        old = []
    new = _entries_for_run(data, prev, site_url, labels)
    ids = {e["id"] for e in old}
    merged = ([e for e in new if e["id"] not in ids] + old)[:KEEP]
    with open(store, "w") as f:
        json.dump(merged, f, separators=(",", ":"))
    fdir = os.path.join(site, "feeds")
    os.makedirs(fdir, exist_ok=True)
    for name, (title, keep) in FEEDS.items():
        with open(os.path.join(fdir, f"{name}.xml"), "w") as f:
            f.write(_atom(name, title, [e for e in merged if keep(e)][:100], site_url))
    _digest(site, data, new, site_url)
    return new


def _digest(site: str, data: dict, new: list[dict], site_url: str) -> None:
    run = data["meta"]["window_end"]
    sections = [("Shared triggers", "shared"), ("Common threads", "thread"), ("New comebacks", "work"),
                ("Coming up", "forecast")]
    lines = [f"Rally, the comeback report, for **{run}**: {len(new)} new findings. "
             f"[Open the site]({site_url}?run={run}).", ""]
    for head, k in sections:
        items = [e for e in new if e["kind_of"] == k][:12]
        if not items:
            continue
        lines += [f"### {head}", ""]
        lines += [f"- [{e['title']}]({e['link']})  \n  {e['summary']}" for e in items]
        lines.append("")
    lines += ["---", "Leads, not conclusions: verify before publishing. "
              "To get this by email, **Watch** this repo → **Custom** → **Issues**."]
    with open(os.path.join(site, "data", "digest.md"), "w") as f:
        f.write("\n".join(lines))
