"""A stand-in for systemd timers that start oneshot services, for the Mac.

Every minute (on the minute) each "unit" is started, unless its previous run is still going:
then the tick is dropped and logged, which is what systemd.timer documents ("it is not
restarted, but simply left running"). With --overlap the unit is started anyway (what cron
does, and what a transient unit per run would do).

    --mode today   : one unit, `adele-server fetch --due` (the draft of deploy/)
    --mode lanes   : two units: every <= 60 s, and the rest (candidate L)
    --mode overlap : one unit, started every minute whatever is still running
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

PROOF = common.use_copy()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--ticks", type=int, default=14)
    ap.add_argument("--mode", choices=("today", "lanes", "overlap"), required=True)
    ap.add_argument("--offset", type=float, default=0.0, help="tick at this second of each minute (keeps parallel prototypes apart)")
    args = ap.parse_args()
    root = args.root.resolve()
    ev = common.Events(root)
    cfg = str(root / "adele-server.toml")
    env = common.child_env(root)
    here = Path(__file__).resolve().parent
    cli = [sys.executable, "-m", "adele_server.cli", "--config", cfg, "fetch", "--due"]
    lane = [sys.executable, str(here / "lane_fetch.py"), "--config", cfg]
    units = {"fetch": cli} if args.mode != "lanes" else {
        "fetch-fast": lane + ["--max-every", "60"], "fetch-rest": lane + ["--min-every", "61"]}
    ev("timer_start", pid=os.getpid(), code=PROOF, mode=args.mode, units=sorted(units))

    running: list[dict] = []
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))

    def reap() -> None:
        for r in list(running):
            pid, status, ru = os.wait4(r["proc"].pid, os.WNOHANG)
            if pid == 0:
                continue
            r["proc"].returncode = os.waitstatus_to_exitcode(status)
            running.remove(r)
            ev("unit_exit", unit=r["unit"], pid=pid, rc=r["proc"].returncode, tick=r["tick"],
               wall_s=round(time.time() - r["started"], 3), cpu_s=round(ru.ru_utime + ru.ru_stime, 3))

    planned = common.next_minute(time.time(), args.offset)
    done = 0
    while not stop["now"]:
        reap()
        now = time.time()
        if now >= planned:
            for unit, cmd in units.items():
                active = [r for r in running if r["unit"] == unit]
                if active and args.mode != "overlap":
                    ev("tick_dropped", unit=unit, tick=planned, active_since=active[0]["tick"])
                    continue
                log = open(root / "logs" / f"{unit}.log", "a")
                log.write(f"--- {common.stamp()} start (tick {common.stamp(planned)})\n")
                log.flush()
                proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=root)
                log.close()
                t = time.time()
                running.append({"unit": unit, "proc": proc, "started": t, "tick": planned})
                ev("unit_start", unit=unit, pid=proc.pid, tick=planned, late_s=round(t - planned, 3),
                   also_running=len(active))
            planned += 60
            done += 1
        if done >= args.ticks and (not running or time.time() > planned - 60 + 45):
            break
        time.sleep(max(0.0, min(0.2, planned - time.time())))
    for r in running:
        ev("stopping_unit", unit=r["unit"], pid=r["proc"].pid)
        r["proc"].terminate()
    ev("timer_stop", ticks=done, left_running=[r["unit"] for r in running])
    return 0


if __name__ == "__main__":
    sys.exit(main())
