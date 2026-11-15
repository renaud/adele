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
# last_scheduled_at: the `now` of the last scheduled run that succeeded. The next scheduled window
# starts at last_scheduled_at - lookback (ingest.scheduled_window). last_fetched_at can't serve
# for that: every window of a backfill sets it, also a window of 2015.
# failing_since: the `now` of the first scheduled run that failed since the last one that
# succeeded. When it is older than the lookback, the scheduled window is [now - lookback, ...)
# again. `given_up` then holds the stretch that was left out, [start, end) as ISO strings.
# versions_since (append-only): the first time that `last_scheduled_at` was set, written once; an
# `as_of` before it is refused (D30).
TIME_KEYS = ("last_attempt_at", "last_fetched_at", "last_changed_at", "last_scheduled_at", "failing_since",
             "versions_since")


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


# The periods of `every` are counted on the clock (UTC) from a Monday at 00:00: PT1M starts on
# the minute, PT1H on the hour, P1D at midnight, P1W on Monday.
PERIOD_ORIGIN = dt.datetime(1970, 1, 5, tzinfo=UTC)


def period(t: dt.datetime, every: dt.timedelta) -> int:
    """The number of the period of `every` that holds `t`."""
    return (t - PERIOD_ORIGIN) // every


def is_due(s: dict, every: dt.timedelta, now: dt.datetime) -> bool:
    """A scheduled run is due when `now` lies in a later period of `every` than the last attempt.

    Not when `every` has passed since the last attempt: a timer ticks at 12:00:00, the attempt is
    stamped 12:00:01, and with `every: PT1M` the tick of 12:01:00 would come 1 s too early, so
    every second run would be skipped. Due also without an attempt, and when the last attempt
    is later than `now` (a clock that was set back).
    """
    last = s.get("last_attempt_at")
    return last is None or last > now or period(now, every) > period(last, every)


def next_fetch_eta(s: dict, every: dt.timedelta) -> dt.datetime | None:
    """The start of the period after the one of the last attempt: from then on, the dataset is due."""
    last = s.get("last_attempt_at")
    return PERIOD_ORIGIN + (period(last, every) + 1) * every if last else None
