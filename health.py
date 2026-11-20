"""
Nightly health check. Prints one line per problem that needs a person, and nothing on a quiet
night. The workflow turns any output into a GitHub issue (an email to the repo owner).

  - the edition didn't move forward (the run finished but produced old data)
  - a source has been unavailable three nights in a row
  - the number of comebacks suddenly halved or doubled (usually a data problem, not news)
  - many Wikipedia pages skipped or Wikidata lookups failed

A failed run and reader tips waiting over a week are checked in the workflow itself.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics

# Sources known to be off for good; not worth an email every night.
KNOWN_OFF = {"Steam reviews"}


def _load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def check(site: str, today: dt.date | None = None) -> list[str]:
    today = today or dt.date.today()
    ddir = os.path.join(site, "data")
    runs = _load(os.path.join(ddir, "index.json"), {}).get("runs", [])
    if not runs:
        return ["No editions on record. The nightly run hasn't produced any data."]
    out = []
    latest = runs[0]
    age = (today - dt.date.fromisoformat(latest["id"])).days
    if age > 2:
        out.append(f"The latest edition is from {latest['id']}, {age} days ago. The run finished but didn't produce a new edition.")

    # Sources off three nights in a row.
    offs = []
    for r in runs[:3]:
        d = _load(os.path.join(ddir, "runs", f"{r['id']}.json"), {})
        offs.append(set((d.get("meta", {}).get("health", {}) or {}).get("sources_off", [])))
    if len(offs) == 3:
        down = (offs[0] & offs[1] & offs[2]) - KNOWN_OFF
        if down:
            out.append(f"Unavailable three nights in a row: {', '.join(sorted(down))}. The site still works without it, "
                       "but those confirmations or causes are missing.")

    # A sudden halving or doubling of comebacks.
    prev = [r["n"] for r in runs[1:8] if r.get("n")]
    if len(prev) >= 3 and latest.get("n") is not None:
        usual = statistics.median(prev)
        if latest["n"] < usual * 0.5 or latest["n"] > usual * 2:
            out.append(f"{latest['n']} comebacks in the latest edition, against a usual {round(usual)}. "
                       "A swing this big is usually a data problem (a source returning too little or too much).")

    # Many pages skipped or lookups failed.
    h = (_load(os.path.join(ddir, "runs", f"{latest['id']}.json"), {}).get("meta", {}) or {}).get("health", {}) or {}
    if (h.get("pages_skipped") or 0) > 300:
        out.append(f"{h['pages_skipped']} Wikipedia pages were skipped in the latest run (usually rate limits).")
    if (h.get("lookups_failed") or 0) > 25:
        out.append(f"{h['lookups_failed']} Wikidata lookups failed in the latest run.")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="site")
    args = ap.parse_args()
    for line in check(args.site):
        print(f"- {line}")
