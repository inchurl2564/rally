"""
Posts the day's story to Bluesky (therallyback.bsky.social) after each nightly edition.

  Daily      (quiet days skipped: Rallyback Score under 50) the top comeback we can explain, as a question and its answer, with a link card
             (title page, picture from Wikimedia Commons). Not the same title, or the same
             reason (one sequel lifting a whole series), twice within 14 days.
  Tue, Thu   a mystery instead: a big comeback we can't explain, asking readers if they know why.
  Friday     also the week's roundup.

Off unless BLUESKY_POST=on (then it signs in with BLUESKY_HANDLE / BLUESKY_APP_PASSWORD). Otherwise,
or with --dry-run, it prints what it would post. What was posted is kept in site/data/social.json.

Bluesky developer guidelines: no automated replies, follows, likes or bulk posting; a few posts a day
from our own account is ordinary use.

  python bluesky_post.py --dry-run [--day YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
STATE = os.path.join(SITE, "data", "social.json")
BASE = "https://therallyback.com"
PDS = "https://bsky.social/xrpc"
UA = {"User-Agent": "Rallyback/1.0 (+https://therallyback.com/?tab=about)"}
VERB = {"film": "watching", "TV series": "watching", "song": "listening to", "album": "listening to",
        "book": "reading", "manga/comic": "reading", "video game": "playing", "musical": "listening to"}
NOUN = {"film": "film", "TV series": "series", "song": "song", "album": "album", "book": "book",
        "manga/comic": "comic", "video game": "game", "musical": "musical"}
CAUSE = {"death": "a death in the news", "legal": "legal headlines", "streaming": "a streaming debut",
         "broadcast": "a TV airing", "viral": "a viral moment online", "sync placement": "a placement in a show, ad or trailer",
         "award": "awards buzz", "re-release": "a re-release or restoration", "remake/sequel news": "remake or sequel news",
         "new season": "a new season or special", "anniversary": "an anniversary", "auction/sale": "a big auction or sale",
         "sports/event": "a big live event", "politics": "politics"}
SKIP = {"seasonal", "automated?", "front page", "lookup failed"}


def _mult(r: dict) -> str:
    m = max(r.get("lift") or 0, r.get("lift3") or 0)
    return f"{round(m)}×" if m >= 10 else f"{m:.1f}".rstrip("0").rstrip(".") + "×"


def _year(r: dict) -> str:
    return str(r.get("release") or "")[:4]


def _date(s: str) -> str:
    d = dt.date.fromisoformat(s[:10])
    return f"{d:%B} {d.day}"


def _new_work(text: str) -> str:
    return re.sub(r"\s*\((upcoming|attention rose before release)\)$", "", text.split(": ", 1)[-1]).strip()


def reason(r: dict, today: dt.date) -> str | None:
    """Why it's back, in one plain sentence (None when we don't know)."""
    t = (r.get("triggers") or [{}])[0]
    v, text = r["verdict"], t.get("text") or ""
    if r.get("editor_note") and v.startswith("editor"):
        return r["editor_note"]["text"].rstrip(".")
    if v == "derivative":
        new, d = _new_work(text), t.get("date", "")
        norm = lambda x: re.sub(r"[^a-z0-9]+", " ", re.sub(r"\s*\([^)]*\)", "", x.lower())).strip()
        if norm(new) == norm(r["label"]):
            new = "A new version of the same name"           # a remake that reuses the title
        return f"{new} {'is due ' + _date(d) if d and d > today.isoformat() else 'just came out'}, and people are going back to the original"
    if v == "same-creator":
        m = re.match(r"new work by (.+?): (.+)$", text)
        if m:
            return f"{m.group(1)} has something new out, {_new_work(m.group(2))}"
    if v == "death":
        m = re.match(r"(.+?) \(([^)]+)\) died", text)
        if m:
            return f"{m.group(1)}, its {m.group(2)}, died on {_date(t['date'])}"
    if v == "anniversary":
        m = re.match(r"(\d+)", text)
        return f"It turns {m.group(1)}" if m else None
    if v == "honor":
        m = re.match(r"(.+?) \(([^)]+)\): (.+)$", text)
        if m:
            return f"{m.group(1)}, its {m.group(2)}, received the {m.group(3)}"
        return f"It was {text.replace('received the', 'awarded the')}"
    if v == "public domain":
        return "On January 1 it entered the public domain, free for anyone to publish or adapt"
    if v == "ripple" and r.get("ripple"):
        rp = r["ripple"]
        return f"Interest in {rp['name']} jumped {rp['ratio']}× at the same time"
    if r.get("cause") in CAUSE:
        return f"It looks like {CAUSE[r['cause']]}"
    return None


def _state() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"posted": []}


def _recent_keys(state: dict, today: dt.date, days: int = 14) -> set[str]:
    cut = (today - dt.timedelta(days=days)).isoformat()
    return {k for p in state["posted"] if p["date"] >= cut for k in p.get("keys", [])}


def choose(latest: dict, today: dt.date, state: dict) -> list[dict]:
    """The posts for today: [{kind, text, card: {uri, title, description, image}, keys}]."""
    seen = _recent_keys(state, today)
    # A title in a group with a known reason (an editor's note, news about the shared person) isn't a mystery.
    group_of = {}
    for t in latest.get("common_threads") or []:
        if t.get("editor_note") or t.get("cause"):
            for w in t.get("works") or []:
                group_of.setdefault(w.get("qid"), t)
    rs = [r for r in latest["results"] if r["verdict"] not in SKIP and (r.get("baseline") or 0) >= 100]
    # Like the front page: new comebacks (on the list today or yesterday) first, then the biggest.
    rs.sort(key=lambda r: (not (r.get("days_on") and r["days_on"] <= 2), -(r.get("rally_score") or 0)))
    posts = []

    def keys(r):
        t = (r.get("triggers") or [{}])[0]
        return [r["qid"]] + ([f"{t.get('type')}:{t.get('qid')}"] if t.get("qid") else [])

    mystery_day = today.weekday() in (1, 3)                      # Tuesday, Thursday
    for r in rs:
        if any(k in seen for k in keys(r)):
            continue
        # Quiet days get no post: only a strong story (Rallyback Score 50+, about the top sixth) or a
        # big mystery (45+ and at least 10x its usual interest) is worth a follower's attention.
        big = max(r.get("lift") or 0, r.get("lift3") or 0)
        if (r.get("rally_score") or 0) < (45 if mystery_day else 50) or (mystery_day and big < 10):
            continue
        why = reason(r, today)
        g = group_of.get(r["qid"]) if r["verdict"] == "common thread" else None
        if g and not why:
            why = (g["editor_note"]["text"].rstrip(".") if g.get("editor_note")
                   else f"{g['name']} is in the news ({CAUSE.get(g.get('cause'), 'details on the page')})")
        label, yr, n = r["label"], _year(r), NOUN.get(r.get("kind"), "title")
        verb = VERB.get(r.get("kind"), "into")
        if mystery_day and why is None and r["verdict"] in ("unexplained", "common thread") and not g:
            text = (f"{label} ({yr}) is suddenly drawing {_mult(r)} its usual interest, and we can't work out why. "
                    f"Do you know? Tell us on the page.")
        elif not mystery_day and why:
            text = f"Why is everyone suddenly {verb} {label} ({yr})? {why}. The {n} is drawing {_mult(r)} its usual interest."
        else:
            continue
        if len(text) > 290:
            continue
        posts.append({"kind": "mystery" if mystery_day else "story", "text": text, "keys": keys(r),
                      "card": {"uri": f"{BASE}/w/{r['qid']}", "title": f"Why is {label} ({yr}) trending again?",
                               "description": why + "." if why else "We don't know yet. Do you?",
                               "image": r.get("image")}})
        break
    if today.weekday() == 4:                                       # Friday: the week's roundup
        iso = (today - dt.timedelta(days=1)).isocalendar()
        week = f"{iso[0]}-W{iso[1]:02d}"
        if os.path.exists(os.path.join(SITE, "week", f"{week}.html")) and f"week:{week}" not in seen:
            posts.append({"kind": "week", "keys": [f"week:{week}"],
                          "text": "This week's comebacks: the old films, shows, songs, games and books people suddenly went back to, and why.",
                          "card": {"uri": f"{BASE}/week/{week}", "title": f"The week in comebacks ({week})",
                                   "description": "Every comeback this week, with the reasons we found.", "image": None}})
    return posts


# ---------- posting ----------

def _call(method: str, token: str | None = None, body: dict | bytes | None = None, ctype="application/json"):
    data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    headers = {**UA, "Content-Type": ctype, **({"Authorization": f"Bearer {token}"} if token else {})}
    with urllib.request.urlopen(urllib.request.Request(f"{PDS}/{method}", data=data, headers=headers), timeout=30) as r:
        return json.load(r)


def _thumb(token: str, image: str | None):
    if not image:
        return None
    url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(image)}?width=800"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            raw, ctype = r.read(), r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if len(raw) > 950_000 or not ctype.startswith("image/"):
            return None
        return _call("com.atproto.repo.uploadBlob", token, raw, ctype)["blob"]
    except Exception:
        return None


def post(posts: list[dict]) -> list[str]:
    s = _call("com.atproto.server.createSession", body={"identifier": os.environ["BLUESKY_HANDLE"],
                                                         "password": os.environ["BLUESKY_APP_PASSWORD"]})
    token, did, uris = s["accessJwt"], s["did"], []
    for p in posts:
        c = p["card"]
        ext = {"uri": c["uri"], "title": c["title"], "description": c["description"]}
        blob = _thumb(token, c.get("image"))
        if blob:
            ext["thumb"] = blob
        rec = {"$type": "app.bsky.feed.post", "text": p["text"], "langs": ["en"],
               "createdAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
               "embed": {"$type": "app.bsky.embed.external", "external": ext}}
        uris.append(_call("com.atproto.repo.createRecord", token, {"repo": did, "collection": "app.bsky.feed.post",
                                                                    "record": rec})["uri"])
    return uris


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--day", help="pretend today is this date (for samples)")
    ap.add_argument("--week", action="store_true", help="samples for 7 days from --day, as if each was posted")
    a = ap.parse_args()
    if a.week:
        with open(os.path.join(SITE, "data", "latest.json")) as f:
            latest = json.load(f)
        state, start = {"posted": []}, dt.date.fromisoformat(a.day) if a.day else dt.date.today()
        for i in range(7):
            day = start + dt.timedelta(days=i)
            print(f"===== {day:%A %b %-d}")
            for p in choose(latest, day, state):
                print(f"[{p['kind']}] {p['text']}\n   link card: {p['card']['title']} / {p['card']['description']}")
                state["posted"].append({"date": day.isoformat(), "keys": p["keys"]})
        return
    today = dt.date.fromisoformat(a.day) if a.day else dt.date.today()
    with open(os.path.join(SITE, "data", "latest.json")) as f:
        latest = json.load(f)
    state = _state()
    posts = choose(latest, today, state)
    live = os.environ.get("BLUESKY_POST") == "on" and not a.dry_run
    for p in posts:
        print(f"--- {p['kind']} ({len(p['text'])} chars){'' if live else ' [not posted: dry run]'}\n{p['text']}\n"
              f"   card: {p['card']['title']} | {p['card']['description']} | {p['card']['uri']} | picture: {p['card']['image']}")
    if not live or not posts:
        return
    try:
        uris = post(posts)
    except Exception as e:
        print(f"Bluesky post failed: {e}")
        return
    state["posted"] = [p for p in state["posted"] if p["date"] >= (today - dt.timedelta(days=60)).isoformat()]
    state["posted"].append({"date": today.isoformat(), "keys": [k for p in posts for k in p["keys"]], "uris": uris})
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)
    print(f"Posted {len(uris)} to Bluesky")


if __name__ == "__main__":
    main()
