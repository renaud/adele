"""Shared setup of the scheduler prototypes (not part of the repo).

Every prototype runs against the COPY of the server code in ../code (taken at the start of the
investigation), never against server/src, which another agent edits. `use_copy()` puts the copy
first on sys.path and in PYTHONPATH (for child processes) and returns the proof.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parent / "code"


def use_copy() -> str:
    sys.path.insert(0, str(CODE))
    old = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(CODE) + (os.pathsep + old if old else "")
    os.environ["UV_OFFLINE"] = "1"  # no network from these prototypes, whatever uv is asked to do
    import adele_server

    assert Path(adele_server.__file__).resolve().is_relative_to(CODE), adele_server.__file__
    return adele_server.__file__


DESCRIPTOR = """\
name: {name}
title: Synthetic {name}
resources:
  - name: ticks
    schema:
      primaryKey: [zone, delivery_start]
      fields:
        - {{name: zone, type: string, categories: [{{value: A, label: Zone A}}, {{value: B, label: Zone B}}]}}
        - {{name: delivery_start, type: datetime}}
        - {{name: resolution, type: duration}}
        - {{name: value, type: number, unit: MW}}
adele:
  format_version: 1
  secrets: [ADELE_POC_LOG]
  refresh: {{every: {every}, lookback: PT15M, horizon: PT0S}}
  revisions: overwrite
  partition: day
  warnings: ["Synthetic data, do not use."]
  examples:
    - question: Average value per zone?
      sql: SELECT zone, avg(value) FROM {name}.ticks GROUP BY zone ORDER BY zone
"""

PEP723 = """\
# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "duckdb>=2.0"]
# ///
"""

# One row per minute and zone over [start, end). Each call appends a line to $ADELE_POC_LOG when
# fetch() starts and when it returns: that is how the prototypes measure the lateness.
FETCH = '''\
import json
import os
import sys
import time

import pandas as pd

NAME, MODE, SLEEP = "{name}", "{mode}", {sleep}


def _log(event, **kw):
    path = os.environ.get("ADELE_POC_LOG")
    if path:
        with open(path, "a") as fh:
            fh.write(json.dumps({{"t": time.time(), "ds": NAME, "event": event, "pid": os.getpid(),
                                 "prefix": sys.prefix, **kw}}) + "\\n")


def fetch(start, end):
    _log("fetch_start", window=[start.isoformat(), end.isoformat()])
    if MODE == "error":
        raise RuntimeError("source down")
    if SLEEP:
        time.sleep(SLEEP)
    idx = pd.date_range(pd.Timestamp(start).ceil("min"), end, freq="min", inclusive="left")
    df = pd.DataFrame([(z, t, pd.Timedelta(minutes=1), float(t.minute) + (0.5 if z == "B" else 0.0))
                       for z in ("A", "B") for t in idx], columns=["zone", "delivery_start", "resolution", "value"])
    _log("fetch_end", rows=len(df))
    return df
'''

# name: (every, mode, sleep seconds)
STANDARD = {
    "fast": ("PT1M", "ok", 0),
    "slow": ("PT3M", "ok", 150),       # a fetch of 2.5 minutes, due every 3 minutes
    "failing": ("PT2M", "error", 0),   # the source is down
    "hanging": ("PT5M", "ok", 100000),  # never returns: stopped at the time limit
}


def build(root: Path, datasets: dict | None = None, fetch_timeout_s: float = 180, pep723: tuple = ()) -> Path:
    """Create <root>/datasets/*, <root>/adele-server.toml, data, logs, tmp. Returns the config path."""
    root.mkdir(parents=True, exist_ok=True)
    for name, (every, mode, sleep) in (datasets or STANDARD).items():
        d = root / "datasets" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "datapackage.yaml").write_text(DESCRIPTOR.format(name=name, every=every))
        body = FETCH.format(name=name, mode=mode, sleep=sleep)
        (d / "fetch.py").write_text((PEP723 if name in pep723 else "") + body)
    for sub in ("data", "logs", "tmp"):
        (root / sub).mkdir(exist_ok=True)
    cfg = root / "adele-server.toml"
    cfg.write_text(textwrap.dedent(f"""\
        datasets_dirs = ["datasets"]
        data_dir = "data"
        log_dir = "logs"
        fetch_timeout_s = {fetch_timeout_s}
        [query]
        max_rows = 10
        timeout_s = 5
        memory_limit = "500MB"
        threads = 2
        [keys]
        tester = "k"
        """))
    return cfg


def child_env(root: Path) -> dict:
    """Environment of the processes that a prototype starts: the copy of the code, a temp folder
    inside the run folder (so that every process of a run has the run folder in its command
    line), the log of the fetch.py calls."""
    env = dict(os.environ)
    env["TMPDIR"] = str(root / "tmp")
    env["ADELE_POC_LOG"] = str(root / "fetch_calls.jsonl")
    env["PYTHONUNBUFFERED"] = "1"
    return env


class Events:
    def __init__(self, root: Path):
        self.path = root / "events.jsonl"

    def __call__(self, event: str, **kw) -> None:
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"t": round(time.time(), 3), "event": event, **kw}) + "\n")


def next_minute(t: float, offset: float = 0.0) -> float:
    """The next time after t that is `offset` seconds past a full minute."""
    return (int(t - offset) // 60 + 1) * 60.0 + offset


def stamp(t: float | None = None) -> str:
    t = time.time() if t is None else t
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"
