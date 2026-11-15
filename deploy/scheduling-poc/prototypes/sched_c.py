"""Candidate C: a scheduler that stays running.

Every minute (on the minute): for each dataset of the catalog that is due and has no fetch
running, start one child process `adele-server fetch <id>`, at most --cap children at once.
The children are the real CLI of the copied server code. Usage:

    cd server && uv run python <this file> --root <run folder> --ticks 14 [--cap 3] [--rule slot|elapsed]

Due rules:
  slot    : due when the tick falls in a later period of `every` than the last start
            (periods counted from the epoch: floor(t / every)). Uses the planned tick time.
  elapsed : the rule of today, ingest.is_due: now >= last_attempt_at + every, with the state file.
Both are computed and logged at every tick; --rule picks the one that acts.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

PROOF = common.use_copy()
from adele_server import config as config_mod  # noqa: E402
from adele_server import ingest, state  # noqa: E402
from adele_server.catalog import CatalogError, load_catalog  # noqa: E402


def signature(dirs: list[Path]) -> tuple:
    """Changes when a descriptor, a fetch.py or a checks.yaml is added, removed or edited."""
    sig = []
    for d in dirs:
        for p in sorted(d.glob("**/datapackage.yaml")) + sorted(d.glob("**/fetch.py")) + sorted(d.glob("**/checks.yaml")):
            st = p.stat()
            sig.append((str(p), st.st_mtime_ns, st.st_size))
    return tuple(sig)


def lock_held(data_dir: Path, ds_id: str) -> bool:
    """True if another process holds the dataset's lock (a fetch started by hand, or by a
    scheduler that died). Same file and same call as ingest.dataset_lock; nothing is written."""
    p = data_dir / ds_id / ".lock"
    if not p.exists():
        return False
    with open(p, "r") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--ticks", type=int, default=14)
    ap.add_argument("--cap", type=int, default=3)
    ap.add_argument("--rule", choices=("slot", "elapsed"), default="slot")
    args = ap.parse_args()
    root = args.root.resolve()
    ev = common.Events(root)
    cfg_path = root / "adele-server.toml"
    cfg = config_mod.load(cfg_path)
    env = common.child_env(root)

    t0 = time.perf_counter()
    catalog = load_catalog(cfg.datasets_dirs)
    sig = signature(cfg.datasets_dirs)
    ev("scheduler_start", pid=os.getpid(), code=PROOF, rule=args.rule, cap=args.cap,
       catalog_load_s=round(time.perf_counter() - t0, 3), datasets=sorted(catalog))

    running: dict[str, dict] = {}   # dataset --> {proc, started, tick}
    last_start: dict[str, float] = {}  # dataset --> tick time of the last start by this scheduler
    queue: list[tuple[str, float]] = []  # (dataset, tick) waiting for a free place
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))

    def reap() -> None:
        for ds_id, r in list(running.items()):
            pid, status, ru = os.wait4(r["proc"].pid, os.WNOHANG)
            if pid == 0:
                continue
            r["proc"].returncode = os.waitstatus_to_exitcode(status)
            del running[ds_id]
            st = state.load(cfg.data_dir, ds_id)
            ev("child_exit", ds=ds_id, pid=pid, rc=r["proc"].returncode, tick=r["tick"],
               wall_s=round(time.time() - r["started"], 3), cpu_s=round(ru.ru_utime + ru.ru_stime, 3),
               status=st.get("status"), last_error=st.get("last_error"),
               last_attempt_at=st["last_attempt_at"].isoformat() if st.get("last_attempt_at") else None)

    def start(ds_id: str, tick: float) -> None:
        log = open(root / "logs" / f"fetch-{ds_id}.log", "a")
        log.write(f"--- {common.stamp()} start (tick {common.stamp(tick)})\n")
        log.flush()
        proc = subprocess.Popen([sys.executable, "-m", "adele_server.cli", "--config", str(cfg_path), "fetch", ds_id],
                                stdout=log, stderr=subprocess.STDOUT, env=env, cwd=root)
        log.close()
        now = time.time()
        running[ds_id] = {"proc": proc, "started": now, "tick": tick}
        last_start[ds_id] = tick
        ev("child_start", ds=ds_id, pid=proc.pid, tick=tick, late_s=round(now - tick, 3), running=len(running))

    def slot_due(ds, tick: float) -> bool:
        every = ds.refresh.every.total_seconds()
        last = last_start.get(ds.id)
        st = state.load(cfg.data_dir, ds.id).get("last_attempt_at")
        if st is not None:
            last = max(last or 0.0, st.timestamp())
        return last is None or int(tick // every) > int(last // every)

    def tick(planned: float) -> None:
        nonlocal catalog, sig
        t_start = time.perf_counter()
        new_sig = signature(cfg.datasets_dirs)
        if new_sig != sig:
            t1 = time.perf_counter()
            try:
                catalog = load_catalog(cfg.datasets_dirs)
                ev("catalog_reloaded", seconds=round(time.perf_counter() - t1, 3), datasets=sorted(catalog))
            except CatalogError as e:  # keep the last valid catalog; the children will refuse too
                ev("catalog_invalid", error=str(e)[:300])
            sig = new_sig
        now_s = state.now()
        decisions = {}
        for ds in catalog.values():
            by_slot = slot_due(ds, planned)
            by_elapsed = ingest.is_due(ds, state.load(cfg.data_dir, ds.id), now_s)
            due = by_slot if args.rule == "slot" else by_elapsed
            what = "not_due"
            if due:
                if ds.id in running:
                    what = "running"       # the previous fetch has not finished: no second one
                elif any(q[0] == ds.id for q in queue):
                    what = "queued"
                elif lock_held(cfg.data_dir, ds.id):
                    what = "locked"        # a fetch that this scheduler did not start
                else:
                    queue.append((ds.id, planned))
                    what = "start"
            decisions[ds.id] = {"slot": by_slot, "elapsed": by_elapsed, "do": what}
        ev("tick", planned=planned, woke_late_s=round(time.time() - planned, 3), decisions=decisions,
           decide_s=round(time.perf_counter() - t_start, 4), running=sorted(running))

    def start_queued() -> None:
        # shortest period first: a dataset due every minute must not wait behind slower ones
        queue.sort(key=lambda q: catalog[q[0]].refresh.every if q[0] in catalog else 0)
        while queue and len(running) < args.cap:
            ds_id, planned = queue.pop(0)
            start(ds_id, planned)

    planned = common.next_minute(time.time())
    done = 0
    waiting_logged: set = set()
    while not stop["now"]:
        reap()
        now = time.time()
        if now >= planned:
            if now - planned >= 60:  # the scheduler overslept (suspended machine, clock step)
                skipped = int((now - planned) // 60)
                ev("ticks_lost", count=skipped, first=planned)
                planned += 60 * skipped
            tick(planned)
            planned += 60
            done += 1
        start_queued()
        for ds_id, p in queue:
            if (ds_id, p) not in waiting_logged:
                waiting_logged.add((ds_id, p))
                ev("waiting_for_place", ds=ds_id, tick=p, running=sorted(running))
        if done >= args.ticks and not running and not queue:
            break
        if done >= args.ticks and time.time() > planned - 60 + 45:  # 45 s after the last tick: stop
            break
        time.sleep(max(0.0, min(0.2, planned - time.time())))

    # Stopping: SIGTERM to the children (what a service manager would do to the whole group).
    for ds_id, r in running.items():
        ev("stopping_child", ds=ds_id, pid=r["proc"].pid)
        r["proc"].terminate()
    ev("scheduler_stop", ticks=done, left_running=sorted(running), reason="signal" if stop["now"] else "end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
