#!/usr/bin/env python3
"""Backfill datasets one window at a time, and wait when a source's call budget is spent (WP5.10).

`adele-server backfill` fetches every window of a range in one go. When a fetch.py runs out of
calls (the openmeteo_* datasets share one budget per machine and raise BudgetSpent), every later
window fails too, and a second backfill would fetch again the windows that succeeded. This script
runs `adele-server backfill` on one window at a time, in the order of the plan:

- a window that fails with "budget spent until <UTC time>" is tried again from that time on;
- one that fails because another fetch of its dataset holds the lock, 2 minutes later;
- one that Open-Meteo refused for the day or the month (429), an hour later;
- one that fails otherwise, 10 minutes later, 3 tries in all; then it is listed at the end.

One lock per window: the scheduled fetches of a dataset run between two of its windows, with the
larger budget (DAY_CAP against BACKFILL_DAY_CAP in the openmeteo client).

Usage, on the server as the user adele in the sandbox of the fetch unit (deploy/wp5.10-backfill.sh):

  backfill_by_window.py --bin /opt/adele/server/.venv/bin/adele-server \\
      --config /etc/adele/adele-server.toml openmeteo_previous_runs,2024-01-18,today,13 ...

A plan item is `dataset,start,end,days per window`; the end `today` is 00:00 UTC of the day on
which the script started (the scheduled fetches cover the days since: their lookback). Prints one
line per window, for the journal of the unit, and a summary. Exit code 1 if a window failed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
import time
from pathlib import Path

UTC = dt.timezone.utc
BUDGET = re.compile(r"budget spent until (\d{4}-\d\d-\d\dT\d\d:\d\dZ)")
LOCK = "another fetch of"
REFUSED = "refused the request (429)"
TRIES = 3


def say(msg: str) -> None:
    print(f"{dt.datetime.now(UTC):%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def plan_item(text: str, today: dt.datetime) -> tuple[str, dt.datetime, dt.datetime, int]:
    ds, start, end, days = text.split(",")
    s = dt.datetime.fromisoformat(start).replace(tzinfo=UTC)
    e = today if end == "today" else dt.datetime.fromisoformat(end).replace(tzinfo=UTC)
    return ds, s, e, int(days)


def windows(start: dt.datetime, end: dt.datetime, days: int) -> list[tuple[dt.datetime, dt.datetime]]:
    out, s = [], start
    while s < end:
        out.append((s, min(s + dt.timedelta(days=days), end)))
        s += dt.timedelta(days=days)
    return out


def wait_for(out: str, now: dt.datetime) -> tuple[float, str] | None:
    """Seconds to wait before the same window is tried again, and why; None: a failure of its own."""
    m = BUDGET.search(out)
    if m:
        until = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
        return max(60.0, (until - now).total_seconds() + 60), f"budget spent until {m.group(1)}"
    if LOCK in out:
        return 120.0, "another fetch holds the lock"
    if REFUSED in out:
        return 3600.0, "Open-Meteo refused the day or the month (429)"
    return None


def last_line(out: str) -> str:
    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    return lines[-1][-400:] if lines else "no output"


def main(argv: list[str] | None = None, sleep=time.sleep, run=subprocess.run) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--bin", default="adele-server")
    p.add_argument("--config")
    p.add_argument("--done", help="file of the windows done: each success adds a line, a restart skips them")
    p.add_argument("plan", nargs="+", help="dataset,start,end,days per window")
    args = p.parse_args(argv)
    today = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    plan = [plan_item(x, today) for x in args.plan]
    base = [args.bin] + (["--config", args.config] if args.config else [])
    done: set[str] = set()
    if args.done:
        Path(args.done).parent.mkdir(parents=True, exist_ok=True)
        if Path(args.done).exists():
            done = set(Path(args.done).read_text().splitlines())
    failed = []
    for ds, start, end, days in plan:
        todo = windows(start, end, days)
        key = {w: f"{ds}\t{w[0]:%Y-%m-%dT%H:%M}\t{w[1]:%Y-%m-%dT%H:%M}" for w in todo}
        left = [w for w in todo if key[w] not in done]
        say(f"{ds}: {len(todo)} windows of {days} days from {start:%Y-%m-%d} to {end:%Y-%m-%d}, "
            f"{len(todo) - len(left)} done before")
        for s, e in left:
            tries = 0
            while True:
                cmd = base + ["backfill", ds, "--start", s.isoformat(), "--end", e.isoformat(),
                              "--step-days", str(days)]
                r = run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
                out = (r.stdout or "") + (r.stderr or "")
                if r.returncode == 0:
                    first = ((r.stdout or "").strip().splitlines() or ["no output"])[0]
                    say(f"{ds} [{s:%Y-%m-%d}, {e:%Y-%m-%d}): {first}")
                    if args.done:
                        with open(args.done, "a") as f:
                            f.write(key[(s, e)] + "\n")
                    break
                why = wait_for(out, dt.datetime.now(UTC))
                if why:
                    say(f"{ds} [{s:%Y-%m-%d}, {e:%Y-%m-%d}): {why[1]}; again in {why[0] / 60:.0f} min")
                    sleep(why[0])
                    continue
                tries += 1
                if tries >= TRIES:
                    say(f"{ds} [{s:%Y-%m-%d}, {e:%Y-%m-%d}): failed {TRIES} times, left: {last_line(out)}")
                    failed.append((ds, s, e, last_line(out)))
                    break
                say(f"{ds} [{s:%Y-%m-%d}, {e:%Y-%m-%d}): failed ({tries} of {TRIES}), again in 10 min: "
                    f"{last_line(out)}")
                sleep(600)
    say(f"done: {len(failed)} windows failed")
    for ds, s, e, err in failed:
        say(f"  {ds} --start {s:%Y-%m-%dT%H:%M} --end {e:%Y-%m-%dT%H:%M}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
