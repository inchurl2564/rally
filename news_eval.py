"""One-off: how many of today's unexplained comebacks each news layer finds articles for."""
import datetime as dt, json, newsfeeds, gdeltfiles
d = json.load(open("site/data/latest.json"))
todo = sorted((r for r in d["results"] if r["verdict"] in ("unexplained", "coverage", "common thread", "ripple", "weak link")),
              key=lambda r: -(r.get("rally_score") or 0))[:30]
newsfeeds.refresh(budget=300); gdeltfiles.refresh(limit=96)
rows, tally = [], {"library": 0, "gdelt": 0, "google": 0, "none": 0, "had_wiki_cause": 0}
for r in todo:
    around = dt.date.fromisoformat(r["spike_start"])
    rip = r.get("ripple"); person = bool(rip and rip.get("relation") not in ("franchise", "series", "character", "source material", "sequel or adaptation"))
    q = rip["name"] if rip else r["label"]
    a = newsfeeds.library_search(q, around, person=person)
    b = [] if a or person else gdeltfiles.search(q, around)
    c = [] if a or b else newsfeeds.google_search(q, around, person=person, kind=None if rip else r["kind"])
    layer = "library" if a else "gdelt" if b else "google" if c else "none"
    tally[layer] += 1; tally["had_wiki_cause"] += bool(r.get("cause"))
    hit = (a or b or c or [{}])[0]
    rows.append(f"{layer:8} {r['label'][:34]:34} ({r['verdict']}) q={q[:24]!r}  {hit.get('source','')}: {hit.get('text','')[:80]}")
print("\n".join(rows)); print(json.dumps(tally))
