"""
The numbers for the morning report on a nightly edition, computed the same way every day.

  python tools/nightly_report.py [YYYY-MM-DD]      (default: the latest edition in site/data/runs)

Prints the explained-share row (counted the way the site shows it: a comeback in a shared-person
group counts as explained when its group has a reason), the trend over the last 7 editions, which
sources supplied evidence, the stories with a reason read from news/edits (to check for wrong
matches), and privacy checks (no saved Currents headlines or Bluesky post text).
"""

from __future__ import annotations

import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(HERE, "site", "data", "runs")
ASIDE = {"seasonal", "automated?", "front page"}
UNEXPLAINED = {"unexplained", "weak link", "lookup failed", "common thread"}


def row(day: str) -> dict:
    d = json.load(open(os.path.join(RUNS, f"{day}.json")))
    rs, threads = d["results"], d.get("common_threads") or []
    told = [t for t in threads if t.get("editor_note") or t.get("person_jump") or t.get("cause")]
    in_told = {w.get("qid") for t in told for w in t.get("works") or []}
    aside = sum(r["verdict"] in ASIDE for r in rs)
    unexpl = sum(r["verdict"] in UNEXPLAINED and not (r["verdict"] == "common thread" and r["qid"] in in_told) for r in rs)
    explained = len(rs) - aside - unexpl
    return {"day": day, "total": len(rs), "aside": aside, "unexplained": unexpl, "explained": explained,
            "share": round(100 * explained / max(len(rs) - aside, 1)),
            "threads": f"{sum(1 for t in threads if t.get('cause'))} of {len(threads)}",
            "editor": sum(r["verdict"].startswith("editor") for r in rs),
            "verdicts": collections.Counter(r["verdict"] for r in rs), "data": d}


def main() -> None:
    days = sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(RUNS, "*.json")))
    day = sys.argv[1] if len(sys.argv) > 1 else days[-1]
    recent = [x for x in days if x <= day][-7:]
    print("| Edition | Comebacks | Set aside | Unexplained | Explained | Groups with a reason | Editor's notes |")
    print("|---|---|---|---|---|---|---|")
    for x in recent:
        r = row(x)
        b = "**" if x == day else ""
        print(f"| {b}{x}{b} | {r['total']} | {r['aside']} | {r['unexplained']} | {b}{r['share']}%{b} | {r['threads']} | {r['editor']} |")
    r = row(day)
    d = r["data"]
    print("\nVerdicts:", dict(r["verdicts"]))
    print("Health:", json.dumps((d.get("meta") or {}).get("health")))
    src = collections.Counter()
    for item in d["results"] + (d.get("common_threads") or []):
        for e in item.get("evidence") or []:
            src[e["source"].split(" ·")[0]] += 1
    print("Evidence by source:", dict(src.most_common()))
    print("\nReasons read from news and edits (check each for a wrong match):")
    for x in d["results"]:
        if x["verdict"] in ("coverage", "honor", "public domain") or (x["verdict"] == "ripple" and x.get("cause")):
            first = (x.get("evidence") or [{}])[0]
            trig = (x.get("triggers") or [{}])[0].get("text", "")
            print(f"  - {x['label']} ({x['kind']}): {x['verdict']} / {x.get('cause') or trig} | {first.get('source', '')}: {first.get('text', '')[:110]}")
    for t in d.get("common_threads") or []:
        if t.get("cause"):
            first = (t.get("evidence") or [{}])[0]
            print(f"  - group: {t['name']}: {t['cause']} | {first.get('source', '')}: {first.get('text', '')[:90]}")
    bad = []
    for item in d["results"] + (d.get("common_threads") or []):
        for e in item.get("evidence") or []:
            if e.get("credit") and not e.get("text", "").startswith("Report on"):
                bad.append(f"Currents headline saved: {item.get('label') or item.get('name')}")
        top = (item.get("chatter") or {}).get("top") or {}
        if top.get("text") or top.get("handle"):
            bad.append(f"Bluesky post text saved: {item.get('label')}")
    print("\nPrivacy checks:", "OK" if not bad else bad[:10])


if __name__ == "__main__":
    main()
