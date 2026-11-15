"""Numbers of one prototype run: lateness of the fast dataset, missed minutes, double fetches, cost per tick.

    python analyze.py <run folder> [<run folder> ...]
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
from pathlib import Path

EVERY = {"fast": 60, "failing": 120, "slow": 180, "hanging": 300}


def load(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def fmt(xs: list[float]) -> str:
    if not xs:
        return "none"
    xs = sorted(xs)
    return f"n={len(xs)} min={xs[0]:.2f} median={st.median(xs):.2f} max={xs[-1]:.2f}"


def analyze(root: Path) -> None:
    ev = load(root / "events.jsonl")
    calls = load(root / "fetch_calls.jsonl")
    print(f"\n================ {root.name}")
    ticks = sorted({e["planned"] for e in ev if e["event"] == "tick"} |
                   {e["tick"] for e in ev if e["event"] in ("unit_start", "tick_dropped")})
    if not ticks:
        print("no tick")
        return
    t0 = ticks[0]
    all_ticks = [t0 + 60 * k for k in range(int(round((ticks[-1] - t0) / 60)) + 1)]
    print(f"ticks: {len(all_ticks)} planned (minute 0 to {len(all_ticks) - 1}), {len(ticks)} seen by the scheduler; "
          f"missing in its log: {[k for k, t in enumerate(all_ticks) if t not in ticks]}")
    end = all_ticks[-1] + 60

    starts = {ds: sorted(c["t"] for c in calls if c["ds"] == ds and c["event"] == "fetch_start") for ds in EVERY}
    ends = {ds: sorted(c["t"] for c in calls if c["ds"] == ds and c["event"] == "fetch_end") for ds in EVERY}

    # the fast dataset, minute by minute
    late, missed, twice = [], [], []
    for k, t in enumerate(all_ticks):
        inside = [s for s in starts["fast"] if t <= s < t + 60]
        if not inside:
            missed.append(k)
        else:
            late.append(inside[0] - t)
            if len(inside) > 1:
                twice.append(k)
    print(f"fast: fetch() started in {len(late)} of {len(all_ticks)} minutes; lateness after the tick (s): {fmt(late)}")
    print(f"      minutes without a fetch of fast: {missed}; minutes with two: {twice}")
    gaps = [b - a for a, b in zip(starts["fast"], starts["fast"][1:])]
    print(f"      longest gap between two fetches of fast: {max(gaps):.0f} s" if gaps else "      one fetch only")

    for ds, every in EVERY.items():
        n = len(starts[ds])
        expected = len([t for t in all_ticks if int((t - t0) // every) != int((t - 60 - t0) // every) or t == t0])
        per_period: dict[int, int] = {}
        for s in starts[ds]:
            per_period[int((s - t0) // every)] = per_period.get(int((s - t0) // every), 0) + 1
        redundant = {k: v for k, v in per_period.items() if v > 1}
        print(f"{ds:8} every {every:3d} s: {n} fetches started, {len(ends[ds])} returned; periods of `every` with a "
              f"tick: {expected}; periods with more than one fetch: {redundant or 'none'}")

    # two fetches of the same dataset at the same time (the lock must make this impossible)
    logs = "".join(p.read_text(errors="replace") for p in sorted((root / "logs").glob("*.log")))
    print(f"lock refusals in the logs ('another fetch of ... is running'): {len(re.findall(r'another fetch of', logs))}")
    print(f"time limit hits ('did not finish within'): {len(re.findall(r'FetchError: fetch did not finish within', logs)) }"
          f" log lines; 'source down' failures: {len(re.findall(r'RuntimeError: source down', logs))} log lines")

    # cost
    if any(e["event"] == "tick" for e in ev):  # candidate C
        dec = [e["decide_s"] * 1000 for e in ev if e["event"] == "tick"]
        woke = [e["woke_late_s"] * 1000 for e in ev if e["event"] == "tick"]
        print(f"scheduler: woke after the minute (ms): {fmt(woke)}; decision per tick, in process (ms): {fmt(dec)}")
        print(f"scheduler: child started after the tick (s), by dataset: "
              + "; ".join(f"{ds}: {fmt([e['late_s'] for e in ev if e['event'] == 'child_start' and e['ds'] == ds])}" for ds in EVERY))
        for ds in EVERY:
            ex = [e for e in ev if e["event"] == "child_exit" and e["ds"] == ds]
            print(f"  child `fetch {ds}`: wall s {fmt([e['wall_s'] for e in ex])}; cpu s {fmt([e['cpu_s'] for e in ex])}; "
                  f"exit codes {sorted({e['rc'] for e in ex})}")
        would_skip = [int(round((e["planned"] - t0) / 60)) for e in ev if e["event"] == "tick"
                      and e["decisions"].get("fast", {}).get("slot") and not e["decisions"]["fast"]["elapsed"]]
        print(f"  ticks where today's rule (elapsed) would have said 'fast is not due' while the slot rule said due: {would_skip}")
        waits = [e for e in ev if e["event"] == "waiting_for_place"]
        print(f"  waits for a free place (cap): {[(e['ds'], int(round((e['tick'] - t0) / 60))) for e in waits]}")
        states = {}
        for e in ev:
            if e["event"] == "tick":
                for ds, d in e["decisions"].items():
                    states.setdefault(ds, {}).setdefault(d["do"], 0)
                    states[ds][d["do"]] += 1
        print(f"  decisions per dataset: {states}")
    else:
        for unit in sorted({e["unit"] for e in ev if e["event"] == "unit_start"}):
            runs = [e for e in ev if e["event"] == "unit_exit" and e["unit"] == unit]
            dropped = [int(round((e["tick"] - t0) / 60)) for e in ev if e["event"] == "tick_dropped" and e["unit"] == unit]
            started = [e for e in ev if e["event"] == "unit_start" and e["unit"] == unit]
            # a run that fetched nothing: no fetch_start between its start and its end
            empty = []
            for r in runs:
                a = r["t"] - r["wall_s"]
                if not any(a <= c["t"] <= r["t"] for c in calls if c["event"] == "fetch_start"):
                    empty.append(r)
            print(f"unit {unit}: started {len(started)} times, {len(dropped)} ticks dropped because it was still running "
                  f"(minutes {dropped}); exit codes {sorted({e['rc'] for e in runs})}")
            print(f"  runs: wall s {fmt([e['wall_s'] for e in runs])}; cpu s {fmt([e['cpu_s'] for e in runs])}")
            print(f"  runs that fetched nothing (cost of an empty tick): wall s {fmt([e['wall_s'] for e in empty])}; "
                  f"cpu s {fmt([e['cpu_s'] for e in empty])}")
            print(f"  started after the tick (ms): {fmt([e['late_s'] * 1000 for e in started])}; "
                  f"at most {max([e['also_running'] for e in started] or [0]) + 1} runs of the unit at once")
    left = sorted(p.name for p in (root / "tmp").iterdir()) if (root / "tmp").exists() else []
    print(f"left in the temp folder: {left or 'nothing'}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        analyze(Path(arg).resolve())
