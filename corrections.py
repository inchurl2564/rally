"""
Corrections: take a story down, or fix its picture, without waiting for a full run.

corrections.json (repo root) is a list of entries, applied by the nightly run and by quickfix.py:

  {"id": "short-name", "qid": "Q123", "action": "take down", "why": "what was wrong", "date": "2026-11-27"}
      removes the title from the edition: stories, groups, shared triggers, feeds (its title page stays,
      without today's reason; delete the entry to bring the story back)
  {"id": "...", "qid": "Q123", "action": "picture", "image": "File name on Wikimedia Commons.jpg",
   "image_of": "Who or what it shows", "why": "...", "date": "..."}
      uses that free Commons picture instead
  {"id": "...", "qid": "Q123", "action": "picture", "image": null, "why": "...", "date": "..."}
      shows no picture

Wrong reasons and headlines are fixed with an editor's note in annotations.json instead.
"""

from __future__ import annotations

import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corrections.json")


def load(path: str = PATH) -> list[dict]:
    try:
        with open(path) as f:
            data = json.load(f)
        return [c for c in data if isinstance(c, dict) and c.get("qid")]
    except (OSError, json.JSONDecodeError):
        return []


def taken_down(items: list[dict] | None = None) -> set[str]:
    return {c["qid"] for c in (load() if items is None else items) if c.get("action") == "take down"}


def take_down(results: list[dict], threads: list[dict] | None = None, shared: list[dict] | None = None,
              items: list[dict] | None = None) -> list[str]:
    """Remove taken-down titles in place. Works on the pipeline's lists and on a saved edition alike:
    threads' works are (work, role) pairs in the pipeline and {"qid", "role"} in an edition;
    shared triggers' works are work dicts in the pipeline and qids in an edition."""
    gone = taken_down(items)
    if not gone:
        return []
    removed = [r["qid"] for r in results if r["qid"] in gone]
    results[:] = [r for r in results if r["qid"] not in gone]

    def qid_of(w):
        if isinstance(w, str):
            return w
        if isinstance(w, (list, tuple)):
            w = w[0]
        return w.get("qid") if isinstance(w, dict) else None

    for group in (threads or []) + (shared or []):
        group["works"] = [w for w in group["works"] if qid_of(w) not in gone]
    if threads is not None:
        threads[:] = [t for t in threads if len(t["works"]) >= 2]
    if shared is not None:
        shared[:] = [s for s in shared if s["works"]]
    return removed


def pictures(results: list[dict], items: list[dict] | None = None) -> list[str]:
    """Apply picture corrections in place."""
    fixes = {c["qid"]: c for c in (load() if items is None else items) if c.get("action") == "picture"}
    changed = []
    for r in results:
        c = fixes.get(r["qid"])
        if c:
            r["image"], r["image_of"] = c.get("image") or None, (c.get("image_of") if c.get("image") else None)
            changed.append(r["qid"])
    return changed
