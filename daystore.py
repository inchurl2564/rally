"""
A small store kept in the repository, one gzipped file per day: store/<name>/<YYYY-MM-DD>.json.gz,
each {url: [date, ...]}. Past days rarely change, so the nightly commit adds about one new file
per store instead of re-saving everything (the repository grows by a few hundred KB a night).
Files are written byte-for-byte the same when nothing changed (sorted keys, no timestamp in the
gzip header), so an unchanged day never shows up in the commit. Days older than `keep` are deleted.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "store")


def _dir(name: str) -> str:
    return os.path.join(ROOT, name)


def _bytes(obj) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return buf.getvalue()


def load(name: str, keep: int) -> dict:
    out: dict = {}
    d = _dir(name)
    cutoff = (dt.date.today() - dt.timedelta(days=keep)).isoformat()
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not f.endswith(".json.gz") or f[:10] < cutoff:
            continue
        try:
            with gzip.open(os.path.join(d, f), "rt", encoding="utf-8") as fh:
                out.update(json.load(fh))
        except (OSError, json.JSONDecodeError, EOFError):
            continue
    return out


def save(name: str, items: dict, keep: int) -> None:
    d = _dir(name)
    os.makedirs(d, exist_ok=True)
    cutoff = (dt.date.today() - dt.timedelta(days=keep)).isoformat()
    by_day: dict[str, dict] = {}
    for url, row in items.items():
        if row and row[0] >= cutoff:
            by_day.setdefault(row[0][:10], {})[url] = row
    for day, rows in by_day.items():
        path = os.path.join(d, f"{day}.json.gz")
        data = _bytes(rows)
        try:
            with open(path, "rb") as fh:
                if fh.read() == data:
                    continue
        except OSError:
            pass
        with open(path, "wb") as fh:
            fh.write(data)
    for f in os.listdir(d):
        if f.endswith(".json.gz") and f[:10] < cutoff:
            os.remove(os.path.join(d, f))


def read_state(name: str) -> dict:
    try:
        with open(os.path.join(_dir(name), "state.json")) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(name: str, state: dict) -> None:
    os.makedirs(_dir(name), exist_ok=True)
    with open(os.path.join(_dir(name), "state.json"), "w") as f:
        json.dump(state, f, sort_keys=True)
