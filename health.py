"""
Nightly health check, in two parts.

  python health.py --site site --gate   before publishing: is tonight's edition complete? Prints one line
                                        per problem and exits 1 if there is any, so the workflow stops
                                        before saving: yesterday's edition stays up and the owner is emailed.
  python health.py --site site          after publishing: problems that need a person but don't make the
                                        edition wrong (a source down for days, many lookups failing).
                                        Quiet nights print nothing.

Stops publishing (--gate):
  - an edition file is missing or unreadable, or has no comebacks
  - the edition didn't move forward (the run finished but produced old data)
  - the number of comebacks halved (usually a source returning too little)
  - title pages missing for titles the site links to
  - many comebacks lost their reason to failed Wikidata lookups

Warns (after publishing):
  - a source has been unavailable three nights in a row
  - the number of comebacks doubled
  - many Wikipedia pages skipped, lookups or picture lookups failed
  - many more comebacks than usual without a picture
  - some comebacks with "lookup failed"

A failed run is reported by the workflow itself.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys

# Sources known to be off for good; not worth an email every night.
KNOWN_OFF = {"Steam reviews"}


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _edition(ddir: str, run_id: str) -> dict:
    return _load(os.path.join(ddir, "runs", f"{run_id}.json"), {}) or {}


def gate(site: str, today: dt.date | None = None) -> list[str]:
    """Problems that make tonight's edition wrong or incomplete. Any one stops publishing."""
    today = today or dt.date.today()
    ddir = os.path.join(site, "data")
    runs = _load(os.path.join(ddir, "index.json"), {}).get("runs", [])
    if not runs:
        return ["No editions on record (data/index.json missing or unreadable)."]
    latest = runs[0]
    out = []
    age = (today - dt.date.fromisoformat(latest["id"])).days
    if age > 2:
        out.append(f"The latest edition is from {latest['id']}, {age} days ago: the run produced no new edition.")
    ed = _edition(ddir, latest["id"])
    res = ed.get("results")
    if not res:
        out.append(f"Tonight's edition file (runs/{latest['id']}.json) is missing, unreadable or has no comebacks.")
        return out
    lj = _load(os.path.join(ddir, "latest.json"), {}) or {}
    if (lj.get("meta") or {}).get("window_end") != (ed.get("meta") or {}).get("window_end"):
        out.append("latest.json and tonight's edition file disagree on the date: the edition was only half written.")

    prev = [r["n"] for r in runs[1:8] if r.get("n")]
    if len(prev) >= 3 and latest.get("n") is not None and latest["n"] < statistics.median(prev) * 0.5:
        out.append(f"{latest['n']} comebacks tonight, against a usual {round(statistics.median(prev))}. "
                   "A drop this big is usually a source returning too little.")

    # Every title the site lists needs its page (search results and Share buttons link to them).
    ix = _load(os.path.join(ddir, "works", "index.json"), {}) or {}
    titles = [w[0] for w in ix.get("works", [])]
    if not titles:
        out.append("The title index (data/works/index.json) is missing or empty.")
    else:
        missing = [q for q in titles if not os.path.exists(os.path.join(site, "w", f"{q}.html"))]
        if len(missing) > max(5, len(titles) * 0.02):
            out.append(f"{len(missing)} of {len(titles)} title pages are missing (e.g. {', '.join(missing[:3])}).")

    failed = sum(1 for r in res if r.get("verdict") == "lookup failed")
    if failed > max(40, len(res) * 0.15):
        out.append(f"{failed} of {len(res)} comebacks lost their reason to failed Wikidata lookups.")
    return out


def check(site: str, today: dt.date | None = None) -> list[str]:
    """Problems worth a person's attention that don't stop publishing."""
    ddir = os.path.join(site, "data")
    runs = _load(os.path.join(ddir, "index.json"), {}).get("runs", [])
    if not runs:
        return []
    out = []
    latest = runs[0]

    # Sources off three nights in a row.
    offs = [set(((_edition(ddir, r["id"]).get("meta") or {}).get("health") or {}).get("sources_off", []))
            for r in runs[:3]]
    if len(offs) == 3:
        down = (offs[0] & offs[1] & offs[2]) - KNOWN_OFF
        if down:
            out.append(f"Unavailable three nights in a row: {', '.join(sorted(down))}. The site still works without it, "
                       "but those confirmations or causes are missing.")

    prev = [r["n"] for r in runs[1:8] if r.get("n")]
    if len(prev) >= 3 and latest.get("n") is not None and latest["n"] > statistics.median(prev) * 2:
        out.append(f"{latest['n']} comebacks in the latest edition, against a usual {round(statistics.median(prev))}. "
                   "A jump this big is sometimes real news, sometimes a source returning too much.")

    ed = _edition(ddir, latest["id"])
    h = (ed.get("meta") or {}).get("health") or {}
    if (h.get("pages_skipped") or 0) > 300:
        out.append(f"{h['pages_skipped']} Wikipedia pages were skipped in the latest run (usually rate limits).")
    if (h.get("lookups_failed") or 0) > 25:
        out.append(f"{h['lookups_failed']} Wikidata lookups failed in the latest run.")
    if (h.get("picture_lookups_failed") or 0) > 3:
        out.append(f"{h['picture_lookups_failed']} picture lookups failed in the latest run: some stories have no picture.")

    res = ed.get("results") or []
    failed = sum(1 for r in res if r.get("verdict") == "lookup failed")
    if failed > 10:
        out.append(f"{failed} comebacks show \"lookup failed\" instead of a reason (Wikidata trouble that the retry "
                   "and the past week's reasons didn't cover).")

    # Pictures: compare tonight's share without one to the past week's.
    def no_pic(results):
        return sum(1 for r in results if not r.get("image")) / len(results) if results else None
    tonight = no_pic(res)
    before = [x for x in (no_pic(_edition(ddir, r["id"]).get("results") or []) for r in runs[1:8]) if x is not None]
    if tonight is not None and len(before) >= 3 and tonight > statistics.median(before) + 0.15:
        out.append(f"{round(tonight * 100)}% of comebacks have no picture tonight, against a usual "
                   f"{round(statistics.median(before) * 100)}%.")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    ap.add_argument("--gate", action="store_true", help="check tonight's edition before publishing; exit 1 on a problem")
    args = ap.parse_args()
    problems = gate(args.site) if args.gate else check(args.site)
    for line in problems:
        print(f"- {line}")
    if args.gate and problems:
        sys.exit(1)
