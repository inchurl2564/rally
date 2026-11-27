"""
Regression tests: each one pins a rule that fixed a real wrong reason or bug (see HANDOFF.md section 6).
They need no network. Run with:  python -m pytest -q tests
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import annotations  # noqa: E402
import archive  # noqa: E402
import explain  # noqa: E402
import health  # noqa: E402
import newsfeeds  # noqa: E402
import radar  # noqa: E402
import youtube  # noqa: E402


# ---------- news headlines (GDELT files, Currents) ----------

def headline(title: str, text: str, person: bool = False) -> bool:
    return newsfeeds._matches(newsfeeds._pattern(title), person, text)


def test_title_must_be_in_quotes():
    assert headline("Lost in Translation", "'Lost in Translation' returns to theaters")
    assert not headline("Lost in Translation", "Something got lost in translation at the summit")


def test_other_words_in_the_quotes_mean_a_different_phrase():
    assert not headline("May", "Pope: 'May God forgive you'")


def test_title_with_subtitle_counts():
    assert headline("Wicked", "'Wicked: For Good' tops the box office")


def test_comparisons_dont_count():
    assert not headline("Minority Report", "'Minority Report' Meets 'Looper' in new thriller")
    assert not headline("Heist", "A 'Heist'-style plot for the new season")


def test_people_by_full_name_only():
    assert headline("Russell Brand", "Russell Brand convicted", person=True)
    assert not headline("Madonna", "Madonna tours again", person=True)


def test_year_in_brackets_is_dropped_from_the_title():
    assert newsfeeds._pattern("Heist (2001 film)") == "Heist"


# ---------- YouTube ----------

def test_trending_title_must_be_a_whole_part():
    assert youtube._segment_match("Shutter", "Shutter | Official Trailer")
    assert not youtube._segment_match("Shutter", "Shutter Island explained")
    assert not youtube._segment_match("Arthur", "James Arthur - Impossible")


def test_search_result_must_say_what_it_is():
    assert youtube._matches("Looker", "Looker (1981) official trailer", "film")
    assert not youtube._matches("Lost in Translation", "lost in translation moments", "film")


# ---------- Wikipedia edits and sentences ----------

def test_noise_edit_summaries_are_ignored():
    for c in ["Reverted edits by Someone", "typo", "fixed grammar", "removed unsourced claim", "Bot: cleanup"]:
        assert explain._NOISE.search(c), c
    assert not explain._NOISE.search("Added the sequel announcement")


def test_legal_needs_sentencing_not_sentence():
    legal = dict(explain._CAUSE_RE)["legal"]
    assert legal.search("Actor sentenced to five years")
    assert not legal.search("A sentence about the plot was added")


def test_sentences_dated_only_in_the_past_are_old_news():
    around = dt.date(2026, 11, 20)
    assert annotations._old_news("In 1960, the film was re-released.", around)
    assert annotations._old_news("It premiered on 3 May 1999.", around)
    assert not annotations._old_news("A sequel was announced on 18 November 2026.", around)
    assert not annotations._old_news("The film was a hit.", around)       # undated: not old news


def test_wikipedia_slow_down_waits_and_retries(monkeypatch):
    import io
    import urllib.error
    calls, slept = [], []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "5"}, None)
        return io.BytesIO(b'{"ok": true}')

    monkeypatch.setattr(explain.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(explain.time, "sleep", lambda s: slept.append(s))
    src = explain._Source("test", 1.0)
    assert src.get("https://example.org/x") == {"ok": True}       # waited, slowed down, then got it
    assert 5 in slept and src.min_interval == 2 and not src.off and src.fails == 0


# ---------- Wikidata reasons ----------

def test_year_only_honors_move_to_their_usual_month():
    assert radar._honor_date("2026-01-01", 9, "Nobel Prize in Literature") == ("2026-10-01", True)
    assert radar._honor_date("2026-03-15", 11, "Some award") == ("2026-03-15", False)


def test_failed_lookup_is_retried_in_smaller_pieces(monkeypatch):
    calls = []

    def flaky(chunk, since):
        calls.append(len(chunk))
        if len(chunk) > 3:
            raise TimeoutError("60s limit")
        for w in chunk:
            w["triggers"].append({"type": "derivative", "date": "2026-11-19", "weight": 3, "text": "x"})

    def ok(chunk, since):
        return None

    monkeypatch.setattr(radar, "_derivatives", flaky)
    for name in ("_deaths", "_same_creator", "_honors", "_public_domain_people"):
        monkeypatch.setattr(radar, name, ok)
    works = [{"qid": f"Q{i}"} for i in range(12)]
    radar.find_triggers(works, dt.date(2026, 10, 1), retry_pause=0)
    assert calls == [12, 3, 3, 3, 3]
    assert all(w["triggers"] for w in works) and not any(w.get("lookup_failed") for w in works)


def test_a_known_reason_survives_a_failed_lookup():
    start = dt.date(2026, 11, 12)
    old = {"type": "derivative", "date": "2026-11-19", "weight": 3, "qid": "Q23648408", "lead_days": -7,
           "text": "new entry in same series: Grand Theft Auto VI (attention rose before release)"}
    editions = [[{"qid": "Q1", "spike_start": "2026-11-12", "triggers": []}],          # last night: lost it
                [{"qid": "Q1", "spike_start": "2026-11-12", "triggers": [old]}]]       # the night before
    w = {"qid": "Q1", "spike_start": start, "triggers": [], "lookup_failed": ["derivatives"]}
    assert radar.carry_over_triggers([w], editions) == 1
    assert w["triggers"][0]["text"] == "new entry in same series: Grand Theft Auto VI"   # suffix re-added later
    other = {"qid": "Q1", "spike_start": dt.date(2026, 11, 20), "triggers": [], "lookup_failed": ["derivatives"]}
    assert radar.carry_over_triggers([other], editions) == 0                             # a different comeback


# ---------- pictures ----------

def test_headline_person():
    death = {"verdict": "death", "triggers": [{"text": "Victor Miller (screenwriter) died", "qid": "Q7926158"}]}
    assert radar.headline_person(death) == ("Q7926158", "Victor Miller")
    creator = {"verdict": "same-creator",
               "triggers": [{"text": "new work by Martin Campbell: Just Play Dead", "qid": "Q9", "person": "Q282033"}]}
    assert radar.headline_person(creator) == ("Q282033", "Martin Campbell")        # the creator, not the new work
    studio = {"verdict": "same-creator", "triggers": [{"text": "new work by Rockstar Games: GTA VI", "qid": "Q9"}]}
    assert radar.headline_person(studio) == (None, "Rockstar Games")                # no photo of an office


# ---------- editor's notes ----------

def test_note_on_a_qid_catches_only_that_title(monkeypatch):
    notes = [{"id": "n", "status": "published", "source": "https://example.com", "note": "x", "cause": "release",
              "works": [], "qids": ["Q1747227"], "from": "2026-11-12", "to": "2026-12-15", "entity_title": "Someone"}]
    monkeypatch.setattr(annotations, "load", lambda: notes)
    film = {"qid": "Q1747227", "label": "Grand Theft Auto", "verdict": "unexplained", "spike_start": dt.date(2026, 11, 15)}
    game = {"qid": "Q94501", "label": "Grand Theft Auto", "verdict": "derivative", "spike_start": dt.date(2026, 11, 15)}
    annotations.apply([film, game], [])
    assert film["verdict"] == "editor-release" and film["editor_note"]["entity_title"] == "Someone"
    assert "editor_note" not in game


# ---------- storage ----------

def test_title_bundles_round_trip(tmp_path):
    site = str(tmp_path)
    os.makedirs(os.path.join(site, "data", "works"))
    with open(os.path.join(site, "data", "works", "Q102225.json"), "w") as f:      # old one-file-per-title layout
        json.dump({"qid": "Q102225", "label": "Goblet of Fire"}, f)
    store = archive.Works(site)
    store.put("Q591272", {"qid": "Q591272", "label": "Casino Royale"})
    store.save()
    files = sorted(os.listdir(os.path.join(site, "data", "works")))
    assert files == sorted([f"{archive.shard_of('Q102225')}.json", f"{archive.shard_of('Q591272')}.json"])
    again = archive.Works(site)
    assert again.get("Q102225")["label"] == "Goblet of Fire" and again.get("Q591272")["label"] == "Casino Royale"


def test_site_and_pipeline_agree_on_bundle_count():
    js = open(os.path.join(ROOT, "site", "app.js")).read()
    assert int(re.search(r"const WORK_SHARDS = (\d+);", js).group(1)) == archive.SHARDS


# ---------- the check before publishing ----------

def _site(tmp_path, n_today=500, pages=True, failed=0):
    site = tmp_path / "site"
    (site / "data" / "runs").mkdir(parents=True)
    (site / "data" / "works").mkdir()
    (site / "w").mkdir()
    days = [(dt.date(2026, 11, 25) - dt.timedelta(days=i)).isoformat() for i in range(5)]
    (site / "data" / "index.json").write_text(json.dumps({"runs": [{"id": d, "n": n_today if i == 0 else 500}
                                                                    for i, d in enumerate(days)]}))
    res = [{"qid": f"Q{i}", "verdict": "lookup failed" if i < failed else "unexplained", "image": "x.jpg"}
           for i in range(n_today)]
    ed = {"meta": {"window_end": days[0], "health": {}}, "results": res}
    (site / "data" / "runs" / f"{days[0]}.json").write_text(json.dumps(ed))
    (site / "data" / "latest.json").write_text(json.dumps(ed))
    (site / "data" / "works" / "index.json").write_text(json.dumps({"works": [[f"Q{i}"] for i in range(50)]}))
    if pages:
        for i in range(50):
            (site / "w" / f"Q{i}.html").write_text("page")
    return str(site)


def test_gate_passes_a_complete_edition(tmp_path):
    assert health.gate(_site(tmp_path), dt.date(2026, 11, 26)) == []


def test_gate_holds_back_broken_editions(tmp_path):
    today = dt.date(2026, 11, 26)
    assert health.gate(_site(tmp_path / "a", n_today=100), today)           # comebacks halved
    assert health.gate(_site(tmp_path / "b", pages=False), today)           # title pages missing
    assert health.gate(_site(tmp_path / "c", failed=200), today)            # reasons lost to lookups
    assert health.gate(_site(tmp_path / "d"), dt.date(2026, 12, 5))         # edition didn't move forward


def test_band_member_death_reads_naturally():
    import bluesky_post
    r = {"verdict": "death", "label": "Seven and the Ragged Tiger",
         "triggers": [{"type": "death", "date": "2026-11-26", "qid": "Q1", "text": "Andy Taylor (member of Duran Duran) died"}]}
    assert bluesky_post.reason(r, dt.date(2026, 11, 27)).startswith("Andy Taylor, a member of Duran Duran, died")
    assert radar.headline_person(r) == ("Q1", "Andy Taylor")


# ---------- quick fixes ----------

def test_take_down_works_on_pipeline_and_saved_shapes():
    import corrections
    items = [{"qid": "Q2", "action": "take down"}]
    # a saved edition: thread works are {"qid", "role"}, shared trigger works are qids
    res = [{"qid": "Q1"}, {"qid": "Q2"}, {"qid": "Q3"}]
    threads = [{"works": [{"qid": "Q1"}, {"qid": "Q2"}]}, {"works": [{"qid": "Q1"}, {"qid": "Q3"}, {"qid": "Q2"}]}]
    shared = [{"works": ["Q2"]}, {"works": ["Q1", "Q2", "Q3"]}]
    assert corrections.take_down(res, threads, shared, items) == ["Q2"]
    assert [r["qid"] for r in res] == ["Q1", "Q3"]
    assert threads == [{"works": [{"qid": "Q1"}, {"qid": "Q3"}]}]          # a group left with one title goes
    assert shared == [{"works": ["Q1", "Q3"]}]
    # the pipeline: thread works are (work, role) pairs, shared works are work dicts
    res2 = [{"qid": "Q1"}, {"qid": "Q2"}]
    th2 = [{"works": [({"qid": "Q1"}, "cast"), ({"qid": "Q2"}, "cast"), ({"qid": "Q4"}, "cast")]}]
    corrections.take_down(res2, th2, [], items)
    assert [w[0]["qid"] for w in th2[0]["works"]] == ["Q1", "Q4"]


def test_picture_correction():
    import corrections
    res = [{"qid": "Q1", "image": "a.jpg", "image_of": "A"}, {"qid": "Q2", "image": "b.jpg", "image_of": None}]
    corrections.pictures(res, [{"qid": "Q1", "action": "picture", "image": None},
                               {"qid": "Q2", "action": "picture", "image": "c.jpg", "image_of": "C"}])
    assert res == [{"qid": "Q1", "image": None, "image_of": None}, {"qid": "Q2", "image": "c.jpg", "image_of": "C"}]


def test_quickfix_fixes_the_live_edition(tmp_path, monkeypatch):
    import corrections
    import quickfix
    site = tmp_path / "site"
    for d in ("runs", "history", "works"):
        (site / "data" / d).mkdir(parents=True)
    (site / "feeds").mkdir()
    res = [{"qid": "Q1", "label": "A", "verdict": "unexplained", "spike_start": "2026-11-20", "triggers": []},
           {"qid": "Q2", "label": "B", "verdict": "unexplained", "spike_start": "2026-11-20", "triggers": []}]
    ed = {"meta": {"window_end": "2026-11-26"}, "results": res, "common_threads": [], "shared_triggers": []}
    for p in (site / "data" / "runs" / "2026-11-26.json", site / "data" / "latest.json"):
        p.write_text(json.dumps(ed))
    (site / "data" / "index.json").write_text(json.dumps({"runs": [{"id": "2026-11-26", "n": 2}]}))
    row = [1, 1, 50, "unexplained", "emerging", 10, "2026-11-20", 0, []]
    (site / "data" / "history" / "2026-11.json").write_text(json.dumps({"days": {"2026-11-26": {"Q1": list(row), "Q2": list(row)}}}))
    monkeypatch.setattr(annotations, "load", lambda: [{"id": "n1", "status": "published", "source": "https://x", "note": "Why.",
                                                       "cause": "release", "works": [], "qids": ["Q1"], "from": "2026-11-18"}])
    monkeypatch.setattr(corrections, "load", lambda path=None: [{"qid": "Q2", "action": "take down"}])
    out = quickfix.fix_edition(str(site))
    assert out["changed"] == ["Q1"] and out["taken_down"] == ["Q2"]
    saved = json.loads((site / "data" / "runs" / "2026-11-26.json").read_text())
    assert [r["qid"] for r in saved["results"]] == ["Q1"] and saved["results"][0]["verdict"] == "editor-release"
    assert saved["results"][0]["spike_start"] == "2026-11-20"                    # dates saved back as text
    assert json.loads((site / "data" / "latest.json").read_text()) == saved
    day = json.loads((site / "data" / "history" / "2026-11.json").read_text())["days"]["2026-11-26"]
    assert "Q2" not in day and day["Q1"][3] == "editor-release" and ["note", None, "n1", None] in day["Q1"][8]


def test_note_explains_a_group_made_mostly_of_its_titles(monkeypatch):
    notes = [{"id": "at", "status": "published", "source": "https://x", "note": "Andy Taylor has died.", "cause": "death",
              "works": [], "qids": ["Q1", "Q2", "Q3"], "from": "2026-11-20"}]
    monkeypatch.setattr(annotations, "load", lambda: notes)
    day = dt.date(2026, 11, 25)
    res = [{"qid": q, "label": q, "verdict": "common thread", "spike_start": day} for q in ("Q1", "Q2", "Q3", "Q9")]
    mostly = {"name": "Colin Thurston", "around": day, "works": [{"qid": "Q1"}, {"qid": "Q2"}, {"qid": "Q9"}]}
    barely = {"name": "Someone Else", "around": day, "works": [{"qid": "Q3"}, {"qid": "Q8"}, {"qid": "Q9"}]}
    annotations.apply(res, [mostly, barely])
    assert mostly.get("editor_note", {}).get("id") == "at" and "editor_note" not in barely
