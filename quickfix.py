"""
Quick fix: re-apply editor's notes (annotations.json) and corrections (corrections.json) to the edition
that's already live, and rebuild the pages, without gathering any new data. Takes seconds, not the
90 minutes of a full run. Run by the "Quick fix" workflow (Actions tab → Quick fix → Run workflow).

  python quickfix.py --site site [--site-url https://therallyback.com] [--delete-bluesky URL]

What it can change: reasons and headlines (editor's notes), taking a story down, a story's picture.
What needs a full run: anything that needs new data (a new kind of reason, new numbers).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

import annotations
import corrections


def _load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _save(path, obj, pretty=False):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1 if pretty else None, separators=None if pretty else (",", ":"), default=str)


def fix_edition(site: str) -> dict:
    """Apply notes and corrections to the latest edition's files. Returns what changed."""
    ddir = os.path.join(site, "data")
    ix = _load(os.path.join(ddir, "index.json"), {})
    run = ix["runs"][0]["id"]
    path = os.path.join(ddir, "runs", f"{run}.json")
    ed = _load(path)
    results, threads = ed["results"], ed.get("common_threads", [])
    before = {r["qid"]: (r["verdict"], (r.get("editor_note") or {}).get("id"), r.get("image")) for r in results}

    # Photos the nightly run attached to notes (Robert Pattinson for the Bond casting): re-applying a note
    # rebuilds it from annotations.json, which has no photo, so keep the ones the edition already has.
    pics = {}
    for x in results + threads:
        n = x.get("editor_note") or {}
        if n.get("image"):
            pics[n["id"]] = (n["image"], n.get("image_of"))

    # Editor's notes: the matching code compares dates, so lend it date objects for a moment.
    for r in results:
        r["spike_start"] = dt.date.fromisoformat(str(r["spike_start"])[:10])
    for t in threads:
        t["around"] = dt.date.fromisoformat(str(t["around"])[:10])
    annotations.apply(results, threads)
    for r in results:
        r["spike_start"] = r["spike_start"].isoformat()
    for t in threads:
        t["around"] = t["around"].isoformat()

    for x in results + threads:
        n = x.get("editor_note")
        if n and n.get("id") in pics and not n.get("image"):
            n["image"], n["image_of"] = pics[n["id"]]

    removed = corrections.take_down(results, threads, ed.get("shared_triggers"))
    pictured = corrections.pictures(results)

    changed = [q for q, b in before.items() if q in {r["qid"] for r in results}
               and b != (lambda r: (r["verdict"], (r.get("editor_note") or {}).get("id"), r.get("image")))(
                   next(x for x in results if x["qid"] == q))]
    _save(path, ed)
    lj = _load(os.path.join(ddir, "latest.json"), {})
    if (lj.get("meta") or {}).get("window_end") == (ed.get("meta") or {}).get("window_end"):
        _save(os.path.join(ddir, "latest.json"), ed)

    # The edition list: counts per reason.
    ix["runs"][0]["n"] = len(results)
    ix["runs"][0]["counts"] = dict(collections.Counter(r["verdict"] for r in results))
    _save(os.path.join(ddir, "index.json"), ix)

    # The permanent record for this day: reason and causes, and taken-down titles removed.
    import enrich
    hpath = os.path.join(ddir, "history", f"{run[:7]}.json")
    month = _load(hpath)
    if month and run in month.get("days", {}):
        day = month["days"][run]
        by_q = {r["qid"]: r for r in results}
        for q in list(day):
            if q in removed:
                del day[q]
            elif q in by_q and len(day[q]) >= 9:
                day[q][3] = by_q[q]["verdict"]
                day[q][8] = enrich.causes_of(by_q[q])
        with open(hpath, "w") as f:
            json.dump(month, f, separators=(",", ":"))

    # Feeds: drop entries for taken-down titles.
    if removed:
        import feeds
        store = os.path.join(ddir, "feed_entries.json")
        entries = [e for e in (_load(store, []) or []) if not any(f"-{q}-" in e.get("id", "") or e.get("id", "").endswith(f"-{q}")
                                                                   or f"/w/{q}" in e.get("link", "") for q in removed)]
        _save(store, entries)
        fdir = os.path.join(site, "feeds")
        site_url = os.environ.get("SITE_URL", "https://therallyback.com/")
        for name, (title, keep) in feeds.FEEDS.items():
            with open(os.path.join(fdir, f"{name}.xml"), "w") as f:
                f.write(feeds._atom(name, title, [e for e in entries if keep(e)][:100], site_url))
    return {"run": run, "changed": changed, "taken_down": removed, "pictures": pictured}


def delete_bluesky(url: str) -> str:
    """Delete one of our Bluesky posts, given its bsky.app link or at:// address."""
    import bluesky_post
    m = re.search(r"post/([a-z0-9]+)", url)
    if not m:
        return f"Not a Bluesky post link: {url}"
    s = bluesky_post._call("com.atproto.server.createSession", body={"identifier": os.environ["BLUESKY_HANDLE"],
                                                                       "password": os.environ["BLUESKY_APP_PASSWORD"]})
    bluesky_post._call("com.atproto.repo.deleteRecord", s["accessJwt"],
                       {"repo": s["did"], "collection": "app.bsky.feed.post", "rkey": m.group(1)})
    return f"Deleted Bluesky post {m.group(1)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    ap.add_argument("--site-url", default="https://therallyback.com/")
    ap.add_argument("--delete-bluesky", default="")
    a = ap.parse_args()
    os.environ["SITE_URL"] = a.site_url
    out = fix_edition(a.site)
    print(f"Edition {out['run']}: {len(out['changed'])} stories changed {out['changed'][:20]}; "
          f"taken down: {out['taken_down'] or 'none'}; pictures fixed: {out['pictures'] or 'none'}")
    import archive          # title pages, weekly and monthly pages, homepage, sitemap
    archive.build(a.site, a.site_url)
    if a.delete_bluesky.strip():
        print(delete_bluesky(a.delete_bluesky.strip()))


if __name__ == "__main__":
    sys.exit(main())
