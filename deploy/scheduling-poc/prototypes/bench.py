"""Costs and edge cases, measured with the copy of the server code (no scheduler involved).

    cd server && uv run python <this file> <run folder> [<real datasets folder, read only>]
"""
from __future__ import annotations

import datetime as dt
import os
import resource
import shutil
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

t_imp = time.perf_counter()
print("adele_server from:", common.use_copy())
from adele_server import checks, cli, ingest, state, storage  # noqa: E402,F401
from adele_server import config as config_mod  # noqa: E402
from adele_server.catalog import CatalogError, load_catalog  # noqa: E402

t_imp = time.perf_counter() - t_imp
UTC = dt.timezone.utc
root = Path(sys.argv[1]).resolve()
if root.exists():
    shutil.rmtree(root)
ds_def = {"fast": ("PT1M", "ok", 0), "slow": ("PT1H", "ok", 0), "other": ("PT1H", "ok", 0)}
cfg_path = common.build(root, ds_def, fetch_timeout_s=60)
env = common.child_env(root)
os.environ.update({k: env[k] for k in ("TMPDIR", "ADELE_POC_LOG")})
cfg = config_mod.load(cfg_path)


def med(xs):
    return f"median {st.median(xs):.3f} (min {min(xs):.3f}, max {max(xs):.3f}, n={len(xs)})"


def run_cli(*args) -> tuple[int, float, float, str]:
    """rc, wall s, cpu s (the process and the children it waited for), output."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    t = time.perf_counter()
    p = subprocess.run([sys.executable, "-m", "adele_server.cli", "--config", str(cfg_path), *args],
                       env=env, cwd=root, capture_output=True, text=True)
    wall = time.perf_counter() - t
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return p.returncode, wall, (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime), p.stdout + p.stderr


print("\n== (a) one tick through the CLI, 3 synthetic datasets (their fetch.py has no script block: the catalog imports them, pandas included)")
for name in ds_def:
    rc, wall, cpu, out = run_cli("fetch", name)
    assert rc == 0, out
r = [run_cli("fetch", "--due") for _ in range(10)]
r = [x for x in r if "fast [" not in x[3]]  # keep the runs in which nothing was due
print(f"`fetch --due` with nothing due: wall s {med([x[1] for x in r])}; cpu s {med([x[2] for x in r])}")
r = [run_cli("fetch", "fast") for _ in range(10)]
print(f"`fetch fast`, nothing new (rows unchanged): wall s {med([x[1] for x in r])}; cpu s {med([x[2] for x in r])}")
bare = []
for _ in range(10):
    t = time.perf_counter()
    subprocess.run([sys.executable, "-c", "pass"], env=env)
    bare.append(time.perf_counter() - t)
print(f"for scale, `python -c pass`: wall s {med(bare)}")

print("\n== (b) the parts, in this process")
print(f"import of adele_server (cli, ingest, checks, storage, catalog): {t_imp:.3f} s (first import, includes duckdb and yaml)")
ts = []
for _ in range(5):
    t = time.perf_counter()
    catalog = load_catalog(cfg.datasets_dirs)
    ts.append(time.perf_counter() - t)
print(f"load_catalog, 3 synthetic datasets: first {ts[0]:.3f} s (imports frictionless and pandas), then {med(ts[1:])} s")
if len(sys.argv) > 2:
    real = Path(sys.argv[2])
    ts = []
    for _ in range(5):
        t = time.perf_counter()
        real_catalog = load_catalog([real])
        ts.append(time.perf_counter() - t)
    print(f"load_catalog, the {len(real_catalog)} real datasets (read only, nothing fetched): {med(ts)} s")

print("\n== (c) fetch_window of `fast` when nothing changed, by part, as the stored history grows")
parts: dict[str, float] = {}


def timed(mod, name):
    orig = getattr(mod, name)

    def wrapper(*a, **k):
        t = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            parts[name] = parts.get(name, 0.0) + time.perf_counter() - t
    setattr(mod, name, wrapper)


for mod, name in ((ingest, "call_fetch"), (ingest, "windows_to_fetch"), (ingest, "_stage"), (checks, "run_checks"),
                  (storage, "merge_overwrite"), (state, "save")):
    timed(mod, name)
fast = catalog["fast"]
t_fast = catalog["fast"].tables["ticks"]


def measure(label: str) -> None:
    rows = []
    for _ in range(5):
        parts.clear()
        now = state.now()
        t = time.perf_counter()
        o = ingest.fetch_window(cfg, catalog, fast, *ingest.scheduled_window(fast, now))
        total = time.perf_counter() - t
        assert o.ok, o.error
        rows.append((total, dict(parts), o.rows_changed))
    con = storage.connect()
    s = storage.table_stats(con, cfg.data_dir, t_fast)
    con.close()
    tot = st.median(r[0] for r in rows)
    line = ", ".join(f"{k} {st.median(r[1].get(k, 0) for r in rows):.3f}" for k in ("call_fetch", "_stage", "merge_overwrite", "run_checks", "save"))
    print(f"{label}: {s.rows} rows in {s.files} files: fetch_window {tot:.3f} s = {line}")


measure("15 minutes stored")
for days in (30, 365):
    # history written straight into the partitions (one file per day), with the storage functions of the server
    con = storage.connect()
    end = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE _batch AS
        SELECT z AS zone, t AS delivery_start, INTERVAL 1 MINUTE AS resolution,
               CAST(minute(t) AS DOUBLE) + CASE WHEN z = 'B' THEN 0.5 ELSE 0 END AS value
        FROM generate_series(TIMESTAMPTZ '{start.isoformat()}', TIMESTAMPTZ '{end.isoformat()}' - INTERVAL 1 MINUTE, INTERVAL 1 MINUTE) g(t),
             (VALUES ('A'), ('B')) v(z)""")
    t = time.perf_counter()
    m = storage.merge_overwrite(con, cfg.data_dir, t_fast, "_batch", fast.window, fast.partition)
    con.close()
    print(f"   (history of {days} days written: {m.rows_changed} rows, {len(m.partitions_written)} files, {time.perf_counter() - t:.1f} s)")
    measure(f"{days} days stored")

print("\n== (f) one invalid descriptor in the catalog: what happens to `fetch fast`")
bad = root / "datasets" / "broken"
bad.mkdir()
(bad / "datapackage.yaml").write_text("name: broken\nresources: []\n")
(bad / "fetch.py").write_text("def fetch(start, end):\n    return None\n")
rc, wall, cpu, out = run_cli("fetch", "fast")
print(f"`fetch fast` with a broken dataset next to it: rc={rc}; {out.strip().splitlines()[0][:160]}")
shutil.rmtree(bad)

print("\n== (g) the rule of today, is_due: now >= last_attempt_at + every, with times cut to the second")
base = dt.datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)
for stamp_s, now_s in ((0, 0), (0, 1), (1, 0), (2, 1), (1, 1)):
    due = ingest.is_due(fast, {"last_attempt_at": base + dt.timedelta(seconds=stamp_s)}, base + dt.timedelta(seconds=60 + now_s))
    print(f"attempt stamped at 12:00:{stamp_s:02d}, next tick reads the clock at 12:01:{now_s:02d} --> due: {due}")

print("\n== (h) a step of the clock backwards (the last attempt lies in the future)")
for back in (0, 30, 3600):
    now = base + dt.timedelta(seconds=60) - dt.timedelta(seconds=back)
    print(f"clock set back by {back:4d} s after an attempt at 12:00:00 --> due at the next tick: "
          f"{ingest.is_due(fast, {'last_attempt_at': base}, now)}; due again only at {base + fast.refresh.every:%H:%M:%S} "
          f"of the new clock, {back + 60} s after the attempt")
print("done")
