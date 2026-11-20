"""
Per-comeback checks and the Rallyback Score.

  global_reach   Is it rising on Wikipedia in other languages too? (pageviews API, 12 big editions)
  chatter        How many Bluesky posts mention it this week, versus the weeks before (public search)
  rally_score    One 0-100 number per comeback: size of the jump, everyday audience, how many
                 independent places confirm it, and how long it has lasted
  record         A compact permanent history: site/data/history/YYYY-MM.json, one row per comeback
                 per day (lift, score, reason, stage, sources), kept forever. This is what later
                 lets The Rallyback say how long each kind of comeback lasts and how big it tends to be.

No API keys. Every lookup is best-effort: a source that fails is skipped, never fatal.
"""

from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

import radar

LANGS = {"de": "German", "fr": "French", "es": "Spanish", "ja": "Japanese", "it": "Italian",
         "pt": "Portuguese", "ru": "Russian", "zh": "Chinese", "ko": "Korean", "pl": "Polish",
         "nl": "Dutch", "sv": "Swedish"}
TOP_N = 150             # strongest comebacks checked per run (keeps the run short)
LANG_UP = 2.0           # a language edition counts as "rising" at 2x its usual views…
LANG_MIN = 20           # …with at least this many views a day
BSKY = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
BUDGET_S = 12 * 60      # time limit for each check; strongest comebacks go first
UA = {"User-Agent": "Rallyback/0.4 (open-data research; +https://github.com/inchurl2564/rally)"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------- other-language Wikipedia ----------

def _sitelinks(qids: list[str]) -> dict[str, dict[str, str]]:
    """{qid: {lang: title}} for the editions in LANGS."""
    out: dict[str, dict] = {}
    sites = " ".join(f"<https://{l}.wikipedia.org/>" for l in LANGS)
    for i in range(0, len(qids), 60):
        values = " ".join(f"wd:{q}" for q in qids[i:i + 60])
        q = f"""SELECT ?item ?site ?name WHERE {{
          VALUES ?item {{ {values} }} VALUES ?site {{ {sites} }}
          ?a schema:about ?item ; schema:isPartOf ?site ; schema:name ?name . }}"""
        try:
            rows = radar.sparql(q)
        except Exception as e:
            log(f"      sitelinks lookup failed for a batch: {e}")
            continue
        for r in rows:
            lang = radar.v(r, "site").split("//")[1].split(".")[0]
            out.setdefault(radar.qid(radar.v(r, "item")), {})[lang] = radar.v(r, "name").replace(" ", "_")
    return out


def _lang_lift(lang: str, title: str, end: dt.date) -> tuple[float, int] | None:
    s = radar.daily_views(f"{lang}.wikipedia", title, end - dt.timedelta(days=120), end)
    if not s:
        return None
    vals = [s.get(end - dt.timedelta(days=i), 0) for i in range(120)][::-1]
    recent, base = vals[-14:], [x for x in vals[:-30] if x > 0]
    if len(base) < 30:
        return None
    usual = max(statistics.median(base), 1)
    now = max(sum(recent) / 14, sum(vals[-3:]) / 3)
    return round(now / usual, 1), int(now)


def global_reach(results: list[dict], end: dt.date) -> None:
    """r["global"] = {"checked": n, "up": [{"lang", "name", "lift", "views"}]}"""
    top = sorted(results, key=lambda r: -r.get("score_hint", 0))[:TOP_N]
    links = _sitelinks([r["qid"] for r in top])
    jobs = [(r, lang, title) for r in top for lang, title in links.get(r["qid"], {}).items()]
    deadline = time.monotonic() + BUDGET_S

    def job(j):
        r, lang, title = j
        if time.monotonic() > deadline:
            return r, lang, None
        try:
            return r, lang, _lang_lift(lang, title, end)
        except Exception:
            return r, lang, None
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        for r, lang, res in ex.map(job, jobs):
            g = r.setdefault("global", {"checked": 0, "up": []})
            if res is None:
                continue
            g["checked"] += 1
            lift, views = res
            if lift >= LANG_UP and views >= LANG_MIN:
                g["up"].append({"lang": lang, "name": LANGS[lang], "lift": lift, "views": views})
    for r in top:
        if r.get("global"):
            r["global"]["up"].sort(key=lambda x: -x["lift"])
    n = sum(1 for r in top if (r.get("global") or {}).get("up"))
    log(f"      other languages: {n} of {len(top)} comebacks are rising elsewhere too ({len(jobs)} pages checked)")


# ---------- Bluesky ----------

def _bsky(params: dict) -> dict | None:
    url = f"{BSKY}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _rate(q: str, since: dt.datetime, until: dt.datetime) -> tuple[float, int] | None:
    """Posts a day mentioning q between since and until, from one page of the latest posts.
    Search returns at most 100 posts, so when a page is full the rate comes from the time
    those 100 posts span rather than from a count (which would hit the cap)."""
    d = _bsky({"q": q, "limit": 100, "sort": "latest", "since": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "until": until.strftime("%Y-%m-%dT%H:%M:%SZ")})
    time.sleep(0.3)
    if d is None:
        return None
    posts = d.get("posts", [])
    window = (until - since).total_seconds() / 86400
    full = bool(d.get("cursor")) or len(posts) >= 90       # pages can come back a few short of 100
    if not full or not posts:
        return len(posts) / window, len(posts)
    times = sorted(dt.datetime.fromisoformat(p["indexedAt"].replace("Z", "+00:00")).replace(tzinfo=None) for p in posts)
    span = min(max((until - times[0]).total_seconds() / 86400, 1 / 24), window)
    return len(posts) / span, round(len(posts) / span * window)


def _searchable(label: str) -> bool:
    """Skip one-word, generic titles ("Heist", "Life"): their mentions are mostly about other things."""
    return " " in label.strip() or len(label) >= 9


def chatter(results: list[dict], end: dt.date) -> None:
    """r["chatter"] = {"week": n, "usual": per-week before, "ratio", "top": {url, text, likes}}"""
    top = [r for r in sorted(results, key=lambda r: -r.get("score_hint", 0)) if _searchable(r["label"])][:TOP_N]
    fails, deadline = 0, time.monotonic() + BUDGET_S
    for r in top:
        if time.monotonic() > deadline:
            log("      Bluesky: time limit reached")
            break
        if fails >= 5:
            log("      Bluesky: switching off for this run (repeated errors)")
            break
        q = f'"{r["label"]}"'
        # Since the comeback began (at least the last 7 days), versus the four weeks before it began.
        now = dt.datetime.combine(end + dt.timedelta(days=1), dt.time())
        start = r["spike_start"] if isinstance(r["spike_start"], dt.date) else dt.date.fromisoformat(r["spike_start"])
        wk = min(dt.datetime.combine(start, dt.time()), now - dt.timedelta(days=7))
        this = _rate(q, wk, now)
        if this is None:
            fails += 1
            continue
        fails = 0
        before = _rate(q, wk - dt.timedelta(days=35), wk - dt.timedelta(days=7)) if this[1] else (0.0, 0)
        per_day, _ = this
        week = round(per_day * 7)                       # posts in a typical week since it began
        usual = (before or (0.0, 0))[0]
        best = None
        if week:
            d = _bsky({"q": q, "limit": 1, "sort": "top", "since": wk.strftime("%Y-%m-%dT%H:%M:%SZ")})
            post = ((d or {}).get("posts") or [None])[0]
            if post:
                rkey = post["uri"].rsplit("/", 1)[-1]
                best = {"url": f"https://bsky.app/profile/{post['author']['handle']}/post/{rkey}",
                        "text": (post.get("record") or {}).get("text", "")[:240],
                        "likes": post.get("likeCount", 0), "handle": post["author"]["handle"]}
        r["chatter"] = {"week": week, "usual": round(usual * 7, 1),
                        "ratio": round(per_day / max(usual, 1 / 7), 1) if week else 0, "top": best}
    n = sum(1 for r in top if (r.get("chatter") or {}).get("ratio", 0) >= 2 and r["chatter"]["week"] >= 10)
    log(f"      Bluesky: {n} of {len(top)} comebacks have at least 2x their usual posts")


# ---------- the Rallyback Score ----------

def confirmations(r: dict) -> float:
    """How many independent places confirm the comeback, beyond English Wikipedia."""
    sig = r.get("signals") or []
    n = sum(1.0 if x["strong"] else 0.5 for x in sig)
    n += min(len((r.get("global") or {}).get("up", [])), 6) / 3          # 3 languages = one confirmation
    c = r.get("chatter") or {}
    if c.get("ratio", 0) >= 2 and c.get("week", 0) >= 10:
        n += 1
    return n


def rally_score(r: dict, end: dt.date) -> int:
    """0-100. Size of the jump 40%, everyday audience 25%, confirmations 20%, staying power 15%."""
    size = min(1.0, math.log2(max(r["lift"], r.get("lift3") or 0, 1.0)) / 6)          # 64x and up = full
    audience = min(1.0, max(0.0, (math.log10(max(r.get("recent_mean", 1), 1)) - 1) / 4))   # 10/day → 0, 100k → 1
    confirmed = min(1.0, confirmations(r) / 3)
    days = (end - r["spike_start"]).days if isinstance(r["spike_start"], dt.date) else 0
    staying = min(1.0, max(0, days) / 14) * (0.6 if r.get("stage") == "fading" else 1.0)
    return round(100 * (0.40 * size + 0.25 * audience + 0.20 * confirmed + 0.15 * staying))


# ---------- the permanent record ----------

HISTORY_FIELDS = ["lift", "lift3", "rally_score", "verdict", "stage", "baseline", "spike_start", "confirmations", "causes"]


def _role(text: str | None) -> str | None:
    """'Patrick Stewart (cast member) died' -> 'cast member'."""
    m = re.search(r"\(([^()]+)\)", text or "")
    return m.group(1) if m else None


def causes_of(r: dict) -> list[list]:
    """What brought a comeback back, compactly, for the permanent record: [kind, qid, detail, date].
    kind: a trigger type (death, derivative, same-creator, anniversary, common thread), "ripple"
    (a related page jumped), "note" (editor's note) or "coverage" (cause read from news/edits).
    The qid is the person, new work or related entity, so later analysis can ask
    "whose news moves catalogs most" (star power) or "how big is a sequel bump"."""
    out = []
    for t in r.get("triggers") or []:
        detail = t.get("text") if t.get("type") == "anniversary" else _role(t.get("text"))
        if t.get("type") in ("derivative", "same-creator"):
            detail = (t.get("text") or "").split(":")[0]       # "new entry in same series", "new work by X"
        out.append([t.get("type"), t.get("qid"), detail, str(t.get("date") or "")[:10]])
    rp = r.get("ripple")
    if rp:
        out.append(["ripple", rp.get("qid"), rp.get("relation"), str(rp.get("date") or "")[:10]])
    if r.get("editor_note"):
        out.append(["note", None, r["editor_note"].get("id"), None])
    if r.get("cause"):
        out.append(["coverage", None, r["cause"], None])
    return out


FRANCHISE_PROPS = ("P179", "P8345")    # part of the series, media franchise


def franchises(qids: list[str], batch: int = 150) -> dict[str, list[str]]:
    """{work qid: [series/franchise qids]} plus their labels, for franchise-level rollups."""
    out: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    looked: set[str] = set()        # works whose lookup actually ran (a failed batch is retried next run)
    qids = [q for q in qids if q]
    for i in range(0, len(qids), batch):
        values = " ".join(f"wd:{q}" for q in qids[i:i + batch])
        q = f"""SELECT ?item ?f ?fLabel WHERE {{
          VALUES ?item {{ {values} }}
          VALUES ?p {{ {" ".join("wdt:" + p for p in FRANCHISE_PROPS)} }}
          ?item ?p ?f .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
        }}"""
        try:
            rows = radar.sparql(q)
        except Exception as e:
            log(f"      franchise lookup failed for a batch: {e}")
            continue
        looked.update(qids[i:i + batch])
        for row in rows:
            w, f = radar.qid(radar.v(row, "item")), radar.qid(radar.v(row, "f"))
            if f not in out.setdefault(w, []):
                out[w].append(f)
            names[f] = radar.nice_label(radar.v(row, "fLabel"))
    return {"of": out, "names": names, "looked": looked}


def record(site: str, results: list[dict], run: str) -> None:
    """Append today's comebacks to site/data/history/YYYY-MM.json (kept forever, compact).
    works[qid] = [label, kind, year, franchise qids]; days[run][qid] = values in `fields` order;
    names[qid] = label for every franchise, person or work referred to, so the file reads on its own."""
    path = os.path.join(site, "data", "history", f"{run[:7]}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path) as f:
            month = json.load(f)
    except (OSError, json.JSONDecodeError):
        month = {"fields": HISTORY_FIELDS, "works": {}, "days": {}}
    month["fields"] = HISTORY_FIELDS          # older days simply have fewer values
    names = month.setdefault("names", {})
    try:
        fr = franchises([r["qid"] for r in results if len(month["works"].get(r["qid"], [])) < 4])
    except Exception as e:
        log(f"      franchise lookup failed: {e}")
        fr = {"of": {}, "names": {}, "looked": set()}
    names.update(fr["names"])
    for r in results:
        year = r["release"].year if hasattr(r["release"], "year") else str(r["release"])[:4]
        w = month["works"].setdefault(r["qid"], [r["label"], r["kind"], year])
        if len(w) < 4 and r["qid"] in fr["looked"]:
            w.append(fr["of"].get(r["qid"], []))
        for t in r.get("triggers") or []:
            if t.get("qid") and t.get("type") != "anniversary":
                text = t.get("text") or ""
                if t.get("type") in ("derivative", "same-creator") and ": " in text:
                    name = re.sub(r" \((upcoming|attention rose before release)\)$", "", text.split(": ", 1)[1])
                else:
                    name = text.split(" (")[0]
                names.setdefault(t["qid"], name[:120])
        if r.get("ripple") and r["ripple"].get("qid"):
            names.setdefault(r["ripple"]["qid"], r["ripple"].get("name"))
    month["days"][run] = {r["qid"]: [r["lift"], r.get("lift3"), r.get("rally_score"), r["verdict"], r.get("stage"),
                                     r["baseline"], str(r["spike_start"]), round(confirmations(r), 1), causes_of(r)] for r in results}
    with open(path, "w") as f:
        json.dump(month, f, separators=(",", ":"))
