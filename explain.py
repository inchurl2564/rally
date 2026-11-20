"""
Explain spikes that Wikidata can't, using open signals from the days the spike began.

  edit burst     daily edit counts for the article (Wikimedia Analytics API). Editors
                 update an article when something happens, so a burst of edits right
                 at the spike start means a real-world event, even if we can't name it.
  edit summaries the text editors wrote for those edits (MediaWiki API). Often names
                 the event: "died 3 November", "added to Netflix", "verdict".
  news           headlines from the GDELT DOC API (free, no key).

All three are best-effort. Shared IPs (like CI runners) are sometimes rate-limited,
so each source backs off and switches itself off for the run after repeated 429s.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import radar

MW_API = "https://en.wikipedia.org/w/api.php"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"

# Keyword → likely cause. Checked against edit summaries and headlines.
CAUSES = [
    ("death", r"\b(died|dies|death of|passed away|obituar|funeral|RIP)\b"),
    ("legal", r"\b(trial|court|verdict|lawsuit|sued|charged|sentenc|convict|acquit|arrest|allegation)"),
    ("streaming", r"\b(netflix|prime video|amazon prime|hulu|disney\+|max\b|hbo max|peacock|paramount\+|apple tv|streaming|now streaming|added to)"),
    ("broadcast", r"\b(aired|airs|broadcast|television premiere|tv premiere|bbc|itv|channel 4|tcm|pbs|christmas special|marathon)"),
    ("viral", r"\b(tiktok|viral|meme|trend(ing)?|instagram|reels|youtube shorts|x\.com|twitter)"),
    ("sync placement", r"\b(featured in|used in|appears in|soundtrack|commercial|advert|ad campaign|trailer for|super bowl ad)"),
    ("award", r"\b(award|oscar|academy award|grammy|emmy|golden globe|bafta|hall of fame|inducted|nominat)"),
    ("re-release", r"\b(re-?release|remaster|reissue|restoration|restored|4k|anniversary edition|box set|re-?issue)"),
    ("remake/sequel news", r"\b(remake|reboot|sequel|prequel|adaptation|announced|casting|cast as|greenlit|in development)"),
    ("anniversary", r"\b(anniversary|years since|years ago)\b"),
    ("auction/sale", r"\b(auction|sold for|record price|copy sold)"),
    ("sports/event", r"\b(halftime|world cup|olympic|super bowl|eurovision|coronation)"),
    ("politics", r"\b(election|president|campaign|rally|senator|prime minister)"),
]
_CAUSE_RE = [(name, re.compile(rx, re.I)) for name, rx in CAUSES]
# Edit summaries that tell us nothing.
_NOISE = re.compile(r"(revert|undid|undo|rv\b|vandal|bot\b|typo|copyedit|\bce\b|clean ?up|format|"
                    r"ref(erence)?s? (fix|format)|wikilink|short description|category|disambig|"
                    r"^\s*$|^/\*.*\*/\s*$)", re.I)


class _Source:
    """Rate limiter + circuit breaker for one API."""

    def __init__(self, name, min_interval):
        self.name, self.min_interval, self.last, self.fails, self.off = name, min_interval, 0.0, 0, False

    def get(self, url, headers=None):
        if self.off:
            return None
        wait = self.min_interval - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": radar.UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
            self.fails = 0
            return json.loads(raw) if raw.strip() else None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError,
                json.JSONDecodeError) as e:
            self.fails += 1
            if self.fails >= 3:
                print(f"      {self.name}: switching off for this run after repeated errors ({e})",
                      file=sys.stderr)
                self.off = True
                radar.HEALTH.setdefault("sources_off", []).append(self.name)
            return None


MW = _Source("Wikipedia edit summaries", 1.0)
NEWS = _Source("GDELT news", 6.0)


def _edits_available_through(today: dt.date | None = None) -> dt.date:
    """Edit counts come from a monthly snapshot published in the first days of the next month."""
    today = today or dt.date.today()
    first = today.replace(day=1)
    if today.day < 6:
        first = (first - dt.timedelta(days=1)).replace(day=1)
    return first - dt.timedelta(days=1)


def edit_burst(project: str, title: str, around: dt.date) -> dict | None:
    """Edits in the 4 days from the spike start vs. the usual rate over the previous 60 days.
    None when that period isn't published yet."""
    if around + dt.timedelta(days=3) > _edits_available_through():
        return None
    t = urllib.parse.quote(title, safe="")
    base = radar.PV.rsplit("/pageviews", 1)[0]
    url = (f"{base}/edits/per-page/{project}/{t}/all-editor-types/daily/"
           f"{(around - dt.timedelta(days=61)):%Y%m%d}/{(around + dt.timedelta(days=4)):%Y%m%d}")
    try:
        res = radar.http_json(url, max_age_h=24 * 7)   # None on 404 = no edits at all
    except Exception:
        return None
    items = (res or {}).get("items", [{}])[0].get("results", [])   # days without edits are omitted
    by_day = {dt.date.fromisoformat(x["timestamp"][:10]): x["edits"] for x in items}
    window = sum(n for d, n in by_day.items() if around - dt.timedelta(days=1) <= d <= around + dt.timedelta(days=3))
    before = sum(n for d, n in by_day.items() if d < around - dt.timedelta(days=1)) / 60
    return {"edits": window, "usual_per_5_days": round(before * 5, 1),
            "burst": window >= 3 and window >= 4 * max(before * 5, 0.5)}


def edit_summaries(title: str, around: dt.date, limit: int = 30) -> list[dict]:
    start = (around + dt.timedelta(days=4)).isoformat() + "T00:00:00Z"
    end = (around - dt.timedelta(days=2)).isoformat() + "T00:00:00Z"
    q = urllib.parse.urlencode({"action": "query", "prop": "revisions", "titles": title.replace("_", " "),
                                "rvprop": "timestamp|comment|size", "rvstart": start, "rvend": end,
                                "rvlimit": limit, "format": "json", "formatversion": 2, "maxlag": 5})
    d = MW.get(f"{MW_API}?{q}", {"Api-User-Agent": radar.UA})
    pages = (d or {}).get("query", {}).get("pages", [])
    out = []
    for rev in (pages[0].get("revisions", []) if pages else []):
        c = (rev.get("comment") or "").strip()
        c = re.sub(r"/\*\s*(.*?)\s*\*/", r"\1:", c).strip(" :")
        if c and not _NOISE.search(c) and len(c) > 8:
            out.append({"source": "Wikipedia edit", "date": rev["timestamp"][:10], "text": c[:200],
                        "url": f"https://en.wikipedia.org/w/index.php?title={urllib.parse.quote(title)}&action=history"})
    return out


def news(query: str, around: dt.date, n: int = 6) -> list[dict]:
    params = {"query": f'"{query}" sourcelang:english', "mode": "artlist", "format": "json",
              "maxrecords": n, "sort": "hybridrel",
              "startdatetime": f"{(around - dt.timedelta(days=2)):%Y%m%d}000000",
              "enddatetime": f"{(around + dt.timedelta(days=4)):%Y%m%d}235959"}
    d = NEWS.get(f"{GDELT}?{urllib.parse.urlencode(params)}")
    return [{"source": a.get("domain", "news"), "date": f"{a['seendate'][:4]}-{a['seendate'][4:6]}-{a['seendate'][6:8]}",
             "text": a.get("title", "")[:200], "url": a.get("url")}
            for a in (d or {}).get("articles", [])]


def likely_cause(evidence: list[dict]) -> str | None:
    scores: dict[str, int] = {}
    for e in evidence:
        for name, rx in _CAUSE_RE:
            if rx.search(e["text"]):
                scores[name] = scores.get(name, 0) + 1
    return max(scores, key=scores.get) if scores else None


def explain(project: str, title: str, query: str, around: dt.date, with_news: bool = True) -> dict:
    """Evidence for one spike. `query` is what to search news for (a work's or person's name)."""
    import annotations   # local import: annotations imports this module
    burst = edit_burst(project, title, around)
    ev = annotations.added_text(title, around)        # sentences added, with the news source cited
    ev += edit_summaries(title, around)
    if with_news:
        ev += news(query, around)
    return {"edit_burst": burst, "evidence": ev[:10], "cause": likely_cause(ev)}


def corroborates(trigger: dict, evidence: list[dict]) -> bool | None:
    """Does the evidence agree with a Wikidata trigger? None when there's no evidence to judge."""
    if not evidence:
        return None
    text = " ".join(e["text"] for e in evidence).lower()
    name = trigger["text"].split(":")[-1].split(" (")[0].replace(" died", "").strip().lower()
    if name and len(name) > 3 and name in text:
        return True
    want = {"death": "death", "anniversary": "anniversary", "derivative": "remake/sequel news",
            "same-creator": "remake/sequel news"}.get(trigger["type"])
    return bool(want and likely_cause(evidence) == want)


# ---------- Wikipedia's front page ----------
# A Main Page feature (Today's featured article, Did you know, On this day) sends tens of
# thousands of readers to an article for a day. That's Wikipedia's doing, not a comeback.

FRONT = _Source("Wikipedia front page", 1.0)
_BOLD_LINK = re.compile(r"'''+\s*\[\[([^\]|#]+)")


def _wikitext(page: str) -> str:
    q = urllib.parse.urlencode({"action": "parse", "page": page, "prop": "wikitext", "format": "json",
                                "formatversion": 2, "maxlag": 5})
    d = FRONT.get(f"{MW_API}?{q}", {"Api-User-Agent": radar.UA})
    return (d or {}).get("parse", {}).get("wikitext", "")


def front_page(days: set[dt.date]) -> dict[str, list[tuple[dt.date, str]]]:
    """{article title (underscored): [(date, feature)]} for front-page features on these days."""
    out: dict[str, list] = {}

    def add(title, d, kind):
        t = title.strip().replace(" ", "_")
        if t:
            out.setdefault(t[0].upper() + t[1:], []).append((d, kind))

    for d in sorted(days):
        tfa = _wikitext(f"Wikipedia:Today's featured article/{d.strftime('%B')} {d.day}, {d.year}")
        m = _BOLD_LINK.search(tfa)
        if m:
            add(m.group(1), d, "Today's featured article")
        for t in _BOLD_LINK.findall(_wikitext(f"Wikipedia:Selected anniversaries/{d.strftime('%B')} {d.day}")):
            add(t, d, "On this day")
    # Did you know: hooks for the current month are on Recent additions, older ones in monthly archives.
    months = {(d.year, d.month) for d in days}
    pages = ["Wikipedia:Recent additions"] + [f"Wikipedia:Recent additions/{y}/{dt.date(y, m, 1):%B}" for y, m in months]
    for page in pages:
        day = None
        for line in _wikitext(page).splitlines():
            h = re.match(r"\s*(?:=+|''')[^=\n]*?(\d{1,2} [A-Z][a-z]+ \d{4})", line)
            if h:
                try:
                    day = dt.datetime.strptime(h.group(1), "%d %B %Y").date()
                except ValueError:
                    day = None
                continue
            if day and day in days and line.lstrip().startswith("*"):
                for t in _BOLD_LINK.findall(line):
                    add(t, day, "Did you know")
    return out
