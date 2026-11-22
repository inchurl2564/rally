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

import archive

MEDIUM = {"film": "Film", "TV series": "TV", "song": "Music", "album": "Music", "musical": "Music",
          "video game": "Games", "book": "Books", "manga/comic": "Books"}

FEEDS = {
    "all": ("The Rallyback: all new comebacks", lambda e: True),
    "unexplained": ("The Rallyback: unexplained comebacks",
                    lambda e: e["verdict"] in ("unexplained", "common thread", "coverage") or e["kind_of"] == "thread"),
    "coming-up": ("The Rallyback: coming up", lambda e: e["kind_of"] == "forecast"),
    "film-tv": ("The Rallyback: film & TV", lambda e: e.get("medium") in ("film", "TV series")),
    "music": ("The Rallyback: music", lambda e: e.get("medium") in ("song", "album", "musical")),
    "games": ("The Rallyback: video games", lambda e: e.get("medium") == "video game"),
    "books": ("The Rallyback: books & comics", lambda e: e.get("medium") in ("book", "manga/comic")),
}
KEEP = 300


def _x(s):
    return html.escape(str(s), quote=True)


def _entries_for_run(site: str, data: dict, prev: dict | None, site_url: str, labels: dict) -> list[dict]:
    run = data["meta"]["window_end"]
    prev_q = {r["qid"] for r in (prev or {}).get("results", [])}
    prev_events = {t["qid"] for t in (prev or {}).get("shared_triggers", [])} | \
                  {t["qid"] for t in (prev or {}).get("common_threads", [])}
    prev_fc = {(c.get("new"), c.get("old")) for c in (prev or {}).get("coming_up", {}).get("derivatives", [])}
    by_q = {r["qid"]: r for r in data["results"]}
    # The same plain-English reasons as the title pages, from tonight's permanent record.
    try:
        hist = archive.load_history(site)
        rows = hist["days"].get(run, {})
        notes = {n["id"]: n.get("note") for n in archive._load("annotations.json", []) if isinstance(n, dict) and n.get("id")}
        why_of = lambda q: archive._causes((rows.get(q) or {}).get("causes") or [], hist["names"], notes)
    except Exception:
        why_of = lambda q: []
    out = []
    for r in data["results"]:
        if r["qid"] in prev_q or r["verdict"] in ("seasonal", "automated?", "front page"):
            continue
        why = why_of(r["qid"])
        noun = archive.NOUN.get(r["kind"], r["kind"])
        conf = archive.CONFIDENCE.get(r["verdict"])
        summary = (f"{r['label']}, the {r['release_year']} {noun}, is drawing {r['lift']}× its usual interest "
                   f"since {archive._day(r['spike_start'])}. "
                   + (f"Why: {archive._sentence(why[0])}" + (f" How sure: {conf[0].lower()}." if conf else "")
                      if why and r["verdict"] not in archive.UNEXPLAINED
                      else "We don't know why yet." + (f" {archive._sentence(why[0])}" if why else "") + " Know why? Tell us on the site."))
        out.append({"id": f"work-{r['qid']}-{r['spike_start']}", "kind_of": "work", "verdict": r["verdict"],
                    "medium": r["kind"], "date": run,
                    "title": f"{r['label']} ({r['release_year']}) is back: {r['lift']}× its usual interest",
                    "summary": summary, "link": f"{site_url}w/{r['qid']}"})
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
        if len(t["works"]) < 3 and not (t.get("editor_note") or t.get("person_jump") or t.get("cause")):
            continue        # two titles sharing someone, unexplained: often coincidence
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
    for s_ in data.get("coming_up", {}).get("subjects", []):
        if s_["new"] in {x.get("new") for x in (prev or {}).get("coming_up", {}).get("subjects", [])}:
            continue
        works = ", ".join(w["label"] for w in s_["works"][:3])
        out.append({"id": f"subject-{s_['new']}-{s_['who']}", "kind_of": "forecast", "verdict": "forecast", "date": run,
                    "title": f"{s_['who_label']}'s work is due for a comeback: {s_['new_label']} arrives {s_['date']}",
                    "summary": f"A new film or series about {s_['who_label']}. Their best-known older work: {works}.",
                    "link": f"{site_url}?run={run}&tab=coming"})
    for m in data.get("measures_new", []):
        out.append({"id": f"measure-{m['key']}", "kind_of": "measure", "verdict": "measure", "date": run,
                    "title": f"New on The Rallyback: {m['title']}",
                    "summary": "We now have enough comebacks on record to publish this. See the Track record page.",
                    "link": f"{site_url}?tab=accuracy"})
    return out


def _link(e: dict, site_url: str) -> str:
    """A title's own page is the best home for an entry (served without ".html" on Cloudflare)."""
    if e.get("link", "").endswith(".html") and "/w/" in e["link"]:
        return e["link"][:-5]
    if e.get("kind_of") == "work" and "#w-" in e.get("link", ""):
        return f"{site_url}w/{e['link'].rsplit('#w-', 1)[1]}"
    return e["link"]


def _categories(e: dict) -> str:
    """Tags a feed reader can filter on: the medium, and why it's back."""
    tags = []
    if MEDIUM.get(e.get("medium")):
        tags.append(MEDIUM[e["medium"]])
    reason = {"forecast": "Coming up", "measure": "Track record", "shared": "New release"}.get(e.get("verdict")) \
        or archive.REASON.get(e.get("verdict"))
    if e.get("kind_of") == "thread":
        reason = "Unexplained"
    if reason and reason != "Set aside":
        tags.append(reason)
    return "".join(f'\n    <category term="{_x(t)}"/>' for t in tags)


def _atom(name: str, title: str, entries: list[dict], site_url: str) -> str:
    updated = (entries[0]["date"] if entries else dt.date.today().isoformat()) + "T06:00:00Z"
    items = "".join(f"""
  <entry>
    <id>{_x(site_url)}#{_x(e['id'])}</id>
    <title>{_x(e['title'])}</title>
    <link href="{_x(_link(e, site_url))}"/>
    <updated>{_x(e['date'])}T06:00:00Z</updated>{_categories(e)}
    <summary>{_x(e['summary'])}</summary>
  </entry>""" for e in entries)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{_x(title)}</title>
  <id>{_x(site_url)}feeds/{name}.xml</id>
  <link rel="self" href="{_x(site_url)}feeds/{name}.xml"/>
  <link href="{_x(site_url)}"/>
  <updated>{updated}</updated>
  <author><name>The Rallyback</name></author>{items}
</feed>
"""


def write(site: str, data: dict, prev: dict | None, site_url: str, labels: dict) -> list[dict]:
    store = os.path.join(site, "data", "feed_entries.json")
    try:
        with open(store) as f:
            old = json.load(f)
    except (OSError, json.JSONDecodeError):
        old = []
    new = _entries_for_run(site, data, prev, site_url, labels)
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
    lines = [f"The Rallyback, the comeback report, for **{run}**: {len(new)} new findings. "
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
