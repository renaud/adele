"""Per-dataset state that the data can't give: fetch times, status, problems.

Stored in <data_dir>/<dataset>/state.json, written to a temp file and renamed. Coverage, row
counts and types are not stored: they are computed from the Parquet files on each request.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

UTC = dt.timezone.utc
TIME_KEYS = ("last_attempt_at", "last_fetched_at", "last_changed_at")


def now() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


def path(data_dir: Path, ds_id: str) -> Path:
    return data_dir / ds_id / "state.json"


def load(data_dir: Path, ds_id: str) -> dict:
    p = path(data_dir, ds_id)
    if not p.exists():
        return {"status": "failing", "problems": ["never fetched"]}
    s = json.loads(p.read_text())
    for k in TIME_KEYS:
        if s.get(k):
            s[k] = dt.datetime.fromisoformat(s[k])
    return s


def save(data_dir: Path, ds_id: str, s: dict) -> None:
    p = path(data_dir, ds_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = {k: (v.isoformat() if isinstance(v, dt.datetime) else v) for k, v in s.items()}
    tmp = p.with_name(f".state.json.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, p)


def next_fetch_eta(s: dict, every: dt.timedelta) -> dt.datetime | None:
    last = s.get("last_attempt_at")
    return last + every if last else None
