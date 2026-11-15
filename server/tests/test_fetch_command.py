"""The fetch command as the timers run it: the runner of a script keeps its path, a signal stops
a fetch in order, one invalid descriptor does not stop the other datasets.

Synthetic datasets only. The signal tests send a real signal to a real `adele-server fetch`.
"""
from __future__ import annotations

import datetime as dt
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import duckdb
import pytest

from adele_server import cli, ingest, state
from adele_server.catalog import CatalogError, load_catalog, parse_duration, refresh_every, scan_catalog

UTC = dt.timezone.utc
DAY = (dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 2, tzinfo=UTC))
BLOCK = "# /// script\n# dependencies = []\n# ///\n"
# Writes its pid, then sleeps: a fetch that only a signal or the time limit ends.
SLEEPER = """\
import os
import time

def fetch(start, end):
    with open(os.environ["ADELE_TEST_PIDFILE"], "w") as fh:
        fh.write(str(os.getpid()))
    time.sleep(120)
"""


def add(cfg, name, fetch=None, descriptor=None):
    """A copy of test_prices under another name, with another fetch.py or descriptor."""
    src, d = cfg.datasets_dir / "test_prices", cfg.datasets_dir / name
    d.mkdir()
    text = (src / "datapackage.yaml").read_text().replace("test_prices", name)
    text = text.replace("ADELE_TEST_BUMP]", "ADELE_TEST_BUMP, ADELE_TEST_PIDFILE]")
    (d / "datapackage.yaml").write_text(text if descriptor is None else descriptor)
    (d / "fetch.py").write_text((src / "fetch.py").read_text() if fetch is None else fetch)


def stand_in_uv(tmp_path, monkeypatch, replace_shell=True) -> Path:
    """A `uv` that runs the runner with the test interpreter and logs the path of the runner.

    replace_shell=False: the shell stays and waits for python, as uv does: two processes in the group.
    """
    bin_dir, log = tmp_path / "bin", tmp_path / "uv_runners.txt"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text('#!/bin/sh\nwhile [ "$1" != "--script" ]; do shift; done\nshift\n'
                                f'echo "$1" >> {log}\n{"exec " if replace_shell else ""}{sys.executable} "$@"\n')
    (bin_dir / "uv").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


def main(cfg, *args):
    return cli.main(["--config", str(cfg.path), *args])


# --- B1: the runner of a script has the same path at every fetch ------------------------------

@pytest.fixture
def scripts(env, tmp_path, monkeypatch):
    cfg, _, _ = env
    log = stand_in_uv(tmp_path, monkeypatch)
    fetch = BLOCK + (cfg.datasets_dir / "test_prices" / "fetch.py").read_text()
    add(cfg, "test_script", fetch)
    add(cfg, "test_other", fetch)
    return cfg, load_catalog(cfg.datasets_dir), log


def test_the_runner_of_a_script_keeps_its_path(scripts):
    cfg, catalog, log = scripts
    for name in ("test_script", "test_script", "test_other"):
        o = ingest.fetch_window(cfg, catalog, catalog[name], *DAY)
        assert o.ok and o.rows == 48, o.error
    runners = cfg.cache_path / "runners"
    assert log.read_text().splitlines() == [str(runners / "test_script" / "_runner.py")] * 2 + [
        str(runners / "test_other" / "_runner.py")]  # one folder per dataset: two datasets run side by side
    for folder in (runners, runners / "test_script", runners / "test_other"):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and folder.stat().st_uid == os.geteuid()
    # python puts this folder first on its import path: nothing but the runner is in it
    assert [p.name for p in (runners / "test_script").iterdir()] == ["_runner.py"]
    assert (runners / "test_script" / "_runner.py").read_text() == ingest.runner_source({"dependencies": []})
    assert cfg.data_dir not in runners.parents and not list(cfg.data_dir.rglob("_runner.py"))


def test_a_changed_script_block_rewrites_the_runner(scripts):
    cfg, catalog, _ = scripts
    ds = catalog["test_script"]
    assert ingest.fetch_window(cfg, catalog, ds, *DAY).ok
    runner = cfg.cache_path / "runners" / "test_script" / "_runner.py"
    first = runner.stat().st_mtime_ns
    assert ingest.fetch_window(cfg, catalog, ds, *DAY).ok
    assert runner.stat().st_mtime_ns == first  # the same text is not written again
    ds.script_metadata = {"requires-python": ">=3.11", "dependencies": []}
    assert ingest.fetch_window(cfg, catalog, ds, *DAY).ok
    assert '# requires-python = ">=3.11"' in runner.read_text()


@pytest.mark.parametrize("how", ["mode of the folder", "mode of runners", "link"])
def test_a_runner_folder_that_another_user_could_write_is_not_used(scripts, tmp_path, caplog, how):
    cfg, catalog, log = scripts
    runners = cfg.cache_path / "runners"
    runners.mkdir(parents=True, mode=0o700)
    if how == "link":
        (tmp_path / "elsewhere").mkdir(mode=0o700)
        (runners / "test_script").symlink_to(tmp_path / "elsewhere")
    else:
        (runners / "test_script").mkdir(mode=0o700)
        (runners if how == "mode of runners" else runners / "test_script").chmod(0o770)
    assert ingest.runner_dir(cfg, catalog["test_script"]) is None
    o = ingest.fetch_window(cfg, catalog, catalog["test_script"], *DAY)
    assert o.ok and o.rows == 48, o.error  # in the temporary folder, as before
    assert cfg.cache_path not in Path(log.read_text().strip()).parents
    assert "no fixed folder for the uv runner" in caplog.text
    assert not (tmp_path / "elsewhere" / "_runner.py").exists()


def test_cache_path_without_the_config_key(env, monkeypatch):
    cfg, _, _ = env
    assert cfg.cache_path == cfg.path.parent / "cache"
    cfg.cache_dir = None
    monkeypatch.setenv("CACHE_DIRECTORY", "/var/cache/adele:/var/cache/other")  # systemd, CacheDirectory=
    assert cfg.cache_path == Path("/var/cache/adele")
    monkeypatch.delenv("CACHE_DIRECTORY")
    monkeypatch.setenv("XDG_CACHE_HOME", "/somewhere")
    assert cfg.cache_path == Path("/somewhere/adele")
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert cfg.cache_path == Path.home() / ".cache" / "adele"


# --- B2: SIGTERM and SIGINT -------------------------------------------------------------------

def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_until(condition, seconds=30.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


@pytest.mark.parametrize("sig, script", [(signal.SIGTERM, False), (signal.SIGINT, False), (signal.SIGTERM, True)])
def test_a_signal_stops_the_fetch_and_is_recorded(env, tmp_path, monkeypatch, sig, script):
    cfg, _, _ = env
    if script:  # the child is a shell that waits for python, as uv does: the whole group must go
        stand_in_uv(tmp_path, monkeypatch, replace_shell=False)
    add(cfg, "test_sleep", (BLOCK if script else "") + SLEEPER)
    pidfile = tmp_path / "fetch.pid"
    proc = subprocess.Popen([sys.executable, "-m", "adele_server.cli", "--config", str(cfg.path), "fetch", "test_sleep"],
                            env={**os.environ, "ADELE_TEST_PIDFILE": str(pidfile)}, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    fetch_pid = None
    try:
        assert wait_until(lambda: pidfile.exists() and pidfile.read_text().strip()), "fetch.py did not start"
        fetch_pid = int(pidfile.read_text())
        assert alive(fetch_pid) and not state.path(cfg.data_dir, "test_sleep").exists()
        with pytest.raises(ingest.FetchError, match="another fetch of test_sleep is running"):
            with ingest.dataset_lock(cfg.data_dir, "test_sleep"):
                pass
        t0 = time.monotonic()
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=30)
        assert time.monotonic() - t0 < 10
        assert proc.returncode == 128 + sig, err
        assert wait_until(lambda: not alive(fetch_pid), 5), "fetch.py still runs"
    finally:
        if proc.poll() is None:
            proc.kill()
        if fetch_pid and alive(fetch_pid):
            os.kill(fetch_pid, signal.SIGKILL)
    st = state.load(cfg.data_dir, "test_sleep")
    error = f"interrupted by {sig.name}: fetch.py was stopped"
    assert st["status"] == "failing" and st["last_error"] == error
    assert st["problems"] == [f"last fetch failed: {error}", "never fetched"]
    assert st["last_attempt_at"] is not None and "last_fetched_at" not in st
    assert "last_scheduled_at" not in st and "failing_since" not in st  # not a failure of the source
    assert "test_sleep [" in out and "FAILED" in out and f"problem: last fetch failed: {error}" in out
    with ingest.dataset_lock(cfg.data_dir, "test_sleep"):  # the lock is free again
        pass
    assert not list(cfg.data_dir.rglob("*.parquet"))


def test_an_interrupted_run_stops_its_pieces_and_does_not_count_as_a_failing_source(env, monkeypatch):
    """In this process: the signal is simulated at the start of the second piece of a scheduled run."""
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    ds.refresh.max_window = dt.timedelta(days=1)
    now = dt.datetime(2026, 3, 10, 12, tzinfo=UTC)
    assert ingest.scheduled_fetch(cfg, catalog, ds, now).ok
    calls, run_child = [], ingest._run_child

    def second_call_is_interrupted(*args):
        calls.append(args)
        if len(calls) == 2:
            ingest._stop.append("SIGTERM")
        return run_child(*args)

    monkeypatch.setattr(ingest, "_run_child", second_call_is_interrupted)
    later = now + dt.timedelta(days=3)
    try:
        o = ingest.scheduled_fetch(cfg, catalog, ds, later)  # [now - 1 day, later + 1 day): 5 pieces
    finally:
        ingest._stop.clear()
    assert o.pieces == 5 and len(calls) == 2 and not o.ok and o.interrupted
    assert o.error == ("interrupted by SIGTERM: fetch.py was not started (piece 2 of 5; the later pieces were not "
                       "attempted)")
    st = state.load(cfg.data_dir, "test_prices")
    assert st["last_scheduled_at"] == now and "failing_since" not in st
    assert st["status"] == "failing" and st["problems"] == [f"last fetch failed: {o.error}"]
    assert (cfg.log_dir / "alerts.log").read_text().splitlines()[-1].split(": ", 1)[1].startswith("ok --> failing")
    o = ingest.scheduled_fetch(cfg, catalog, ds, later)  # the next run starts at the same place
    assert o.ok and o.pieces == 5 and (o.start, o.end) == (now - dt.timedelta(days=1), later + dt.timedelta(days=1))
    assert state.load(cfg.data_dir, "test_prices")["status"] == "ok"


def test_the_handlers_are_put_back(env):
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    with ingest.stop_on_signals():
        assert signal.getsignal(signal.SIGTERM) is ingest._on_signal and ingest.stopped() is None
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before
    cfg, _, _ = env
    assert main(cfg, "fetch", "test_prices") == 0
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)) == before


# --- B3: one invalid descriptor does not stop the fetch of the others -------------------------

@pytest.fixture
def broken(env):
    """test_prices is valid; test_yaml is not YAML, test_refresh has no adele.refresh."""
    cfg, _, _ = env
    add(cfg, "test_yaml", descriptor="name: test_yaml\nresources: [\n")
    text = (cfg.datasets_dir / "test_prices" / "datapackage.yaml").read_text().replace("test_prices", "test_refresh")
    add(cfg, "test_refresh", descriptor=text.replace("  refresh: {every: PT1H, lookback: P1D, horizon: P1D}\n", ""))
    return cfg


def test_scan_catalog_keeps_the_valid_datasets(broken):
    catalog, errors = scan_catalog(broken.datasets_dirs)
    assert sorted(catalog) == ["test_prices"]
    assert [e.split(":")[0] for e in errors] == ["test_refresh", "test_yaml"]
    with pytest.raises(CatalogError, match="test_yaml: datapackage.yaml is not valid YAML"):
        load_catalog(broken.datasets_dirs)


def test_fetch_of_a_valid_dataset_works_beside_invalid_ones(broken, capsys):
    assert main(broken, "fetch", "test_prices") == 0
    out, err = capsys.readouterr()
    assert "test_prices [" in out and ": ok, 96 rows" in out
    lines = [ln for ln in err.splitlines() if ln.startswith("invalid, not loaded: ")]
    assert len(lines) == 2 and len(err.splitlines()) == 2  # one line per invalid descriptor
    assert lines[0].startswith("invalid, not loaded: test_refresh: adele.refresh needs every, lookback and horizon")
    assert lines[1].startswith("invalid, not loaded: test_yaml: datapackage.yaml is not valid YAML")
    assert state.load(broken.data_dir, "test_prices")["status"] == "ok"


def test_fetch_due_fetches_the_valid_datasets_and_exits_with_2(broken, capsys):
    assert main(broken, "fetch", "--due") == 2
    out, err = capsys.readouterr()
    assert "test_prices [" in out and ": ok, 96 rows" in out and len(err.splitlines()) == 2
    assert state.load(broken.data_dir, "test_prices")["status"] == "ok"
    for name in ("test_yaml", "test_refresh"):
        assert not (broken.data_dir / name).exists()


@pytest.mark.parametrize("name, message", [("test_yaml", "the descriptor of 'test_yaml' is invalid"),
                                           ("test_refresh", "the descriptor of 'test_refresh' is invalid"),
                                           ("test_nowhere", "unknown dataset 'test_nowhere'")])
def test_fetch_of_an_invalid_or_unknown_dataset_exits_with_2(broken, capsys, name, message):
    assert main(broken, "fetch", name) == 2
    assert f"error: {message}" in capsys.readouterr().err
    assert not (broken.data_dir / "test_prices").exists()


@pytest.mark.parametrize("command", [("validate",), ("serve",), ("check", "test_prices"),
                                     ("backfill", "test_prices", "--start", "2026-01-01", "--end", "2026-01-02")])
def test_the_other_commands_stay_strict(broken, capsys, command):
    assert main(broken, *command) == 2
    err = capsys.readouterr().err
    assert "error: invalid catalog" in err and "test_yaml" in err and "test_refresh" in err
    assert not (broken.data_dir / "test_prices").exists()


# --- C2: due by whole periods of `every` on the clock (UTC) -----------------------------------

def at(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.mark.parametrize("every, last, now, due", [
    ("PT1M", "2026-03-10T12:00:01", "2026-03-10T12:00:59", False),
    ("PT1M", "2026-03-10T12:00:01", "2026-03-10T12:01:00", True),  # the timer: 59 s after the attempt
    ("PT15M", "2026-03-10T12:14:59", "2026-03-10T12:15:00", True),
    ("PT1H", "2026-03-10T12:00:00", "2026-03-10T12:59:59", False),
    ("PT1H", "2026-03-10T12:59:59", "2026-03-10T13:00:00", True),
    ("PT1H", "2026-03-10T12:00:01", "2026-03-10T14:30:00", True),
    ("P1D", "2026-03-10T00:00:00", "2026-03-10T23:59:59", False),
    ("P1D", "2026-03-10T23:59:59", "2026-03-11T00:00:00", True),
    ("P1W", "2026-03-09T00:00:00", "2026-03-15T23:59:59", False),  # Monday to Sunday
    ("P1W", "2026-03-15T23:59:59", "2026-03-16T00:00:00", True),
    ("PT1H", "2026-03-10T13:00:00", "2026-03-10T12:30:00", True),  # the clock was set back
])
def test_due_counts_whole_periods_on_the_clock(env, every, last, now, due):
    _, catalog, _ = env
    ds = catalog["test_prices"]
    ds.refresh.every = parse_duration(every)
    assert ingest.is_due(ds, {"last_attempt_at": at(last)}, at(now)) is due
    assert state.is_due({"last_attempt_at": at(last)}, ds.refresh.every, at(now)) is due
    assert ingest.is_due(ds, {}, at(now))  # never attempted


def test_next_fetch_eta_is_the_start_of_the_next_period():
    s = {"last_attempt_at": at("2026-03-10T12:00:01")}
    assert state.next_fetch_eta(s, dt.timedelta(hours=1)) == at("2026-03-10T13:00:00")
    assert state.next_fetch_eta(s, dt.timedelta(days=1)) == at("2026-03-11T00:00:00")
    assert state.next_fetch_eta({}, dt.timedelta(hours=1)) is None


@pytest.fixture
def clock(monkeypatch):
    """state.now() returns clock[0]."""
    now = [at("2026-03-10T12:59:30")]
    monkeypatch.setattr(state, "now", lambda: now[0])
    return now


def test_fetch_due_uses_the_periods(env, clock, capsys):
    cfg, _, _ = env
    assert main(cfg, "fetch", "--due") == 0 and "test_prices [" in capsys.readouterr().out
    clock[0] = at("2026-03-10T12:59:59")
    assert main(cfg, "fetch", "--due") == 0 and capsys.readouterr().out == ""
    clock[0] = at("2026-03-10T13:00:00")  # 30 s after the attempt, in the next hour
    assert main(cfg, "fetch", "--due") == 0 and "test_prices [" in capsys.readouterr().out
    assert state.load(cfg.data_dir, "test_prices")["last_scheduled_at"] == clock[0]


# --- C1: fetch <id> --if-due ------------------------------------------------------------------

def test_if_due_fetches_when_due_and_is_silent_when_not(env, clock, capsys):
    cfg, _, _ = env
    assert main(cfg, "fetch", "test_prices", "--if-due") == 0  # never fetched: due
    out, err = capsys.readouterr()
    assert "test_prices [2026-03-09 12:59, 2026-03-11 12:59) UTC: ok, 96 rows" in out and err == ""
    st = state.load(cfg.data_dir, "test_prices")
    assert st["last_scheduled_at"] == clock[0] and st["status"] == "ok"  # a scheduled run
    before = state.path(cfg.data_dir, "test_prices").read_bytes()
    clock[0] = at("2026-03-10T12:59:59")
    assert main(cfg, "fetch", "test_prices", "--if-due") == 0
    assert capsys.readouterr() == ("", "") and state.path(cfg.data_dir, "test_prices").read_bytes() == before
    clock[0] = at("2026-03-10T13:00:00")
    assert main(cfg, "fetch", "test_prices", "--if-due") == 0
    assert "test_prices [2026-03-09 12:59, 2026-03-11 13:00) UTC: ok" in capsys.readouterr().out
    assert state.load(cfg.data_dir, "test_prices")["last_scheduled_at"] == clock[0]


def test_if_due_reads_no_other_descriptor_and_no_heavy_module_when_not_due(broken):
    """A real process: which modules did the tick import, what did it print?"""
    assert main(broken, "fetch", "test_prices") == 0  # the attempt of this hour
    code = ("import sys\nfrom adele_server import cli\n"
            f"rc = cli.main(['--config', {str(broken.path)!r}, 'fetch', 'test_prices', '--if-due'])\n"
            "heavy = ('duckdb', 'pandas', 'frictionless', 'adele_server.ingest', 'adele_server.storage', 'logging')\n"
            "print(rc, [m for m in heavy if m in sys.modules])\n")
    last = state.load(broken.data_dir, "test_prices")["last_attempt_at"]
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if state.period(state.now(), dt.timedelta(hours=1)) == state.period(last, dt.timedelta(hours=1)):
        # not due: nothing printed, also not the lines about test_yaml and test_refresh
        assert (p.returncode, p.stdout, p.stderr) == (0, "0 []\n", "")
    # due (the test crossed the hour, or the next lines): the catalog is loaded, tolerant
    path = state.path(broken.data_dir, "test_prices")
    path.write_text(path.read_text().replace(last.isoformat(), (last - dt.timedelta(hours=2)).isoformat()))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert p.returncode == 0 and "test_prices [" in p.stdout and "'duckdb'" in p.stdout
    assert len([ln for ln in p.stderr.splitlines() if ln.startswith("invalid, not loaded: ")]) == 2


def test_if_due_on_doubt_takes_the_full_path(broken, clock, capsys):
    cfg = broken
    assert main(cfg, "fetch", "test_nowhere", "--if-due") == 2
    assert "error: unknown dataset 'test_nowhere'" in capsys.readouterr().err
    assert main(cfg, "fetch", "test_yaml", "--if-due") == 2
    assert "error: the descriptor of 'test_yaml' is invalid" in capsys.readouterr().err
    assert main(cfg, "fetch", "test_prices", "--if-due") == 0
    capsys.readouterr()
    # a descriptor that broke after the fetch: `every` can't be read, so the full path reports it at each tick
    (cfg.datasets_dir / "test_prices" / "datapackage.yaml").write_text("name: test_prices\nresources: [\n")
    assert main(cfg, "fetch", "test_prices", "--if-due") == 2
    assert "error: the descriptor of 'test_prices' is invalid" in capsys.readouterr().err


@pytest.mark.parametrize("args", [("--due", "--if-due"), ("test_prices", "--if-due", "--start", "2026-01-01"),
                                  ("test_prices", "--if-due", "--end", "2026-01-01"), ("--if-due",)])
def test_if_due_needs_a_dataset_and_no_window(env, capsys, args):
    cfg, _, _ = env
    with pytest.raises(SystemExit) as e:
        main(cfg, "fetch", *args)
    assert e.value.code == 2
    assert not state.path(cfg.data_dir, "test_prices").exists()


def test_refresh_every_reads_one_descriptor(env, tmp_path):
    cfg, _, _ = env
    single = tmp_path / "checkout_of_a_repository"  # an entry that is one dataset: its folder name is free
    single.mkdir()
    text = (cfg.datasets_dir / "test_prices" / "datapackage.yaml").read_text()
    (single / "datapackage.yaml").write_text(text.replace("test_prices", "test_single").replace("PT1H", "PT15M"))
    add(cfg, "test_yaml", descriptor="name: test_yaml\nresources: [\n")
    dirs = [single, cfg.datasets_dir]
    assert refresh_every(dirs, "test_prices") == dt.timedelta(hours=1)
    assert refresh_every(dirs, "test_single") == dt.timedelta(minutes=15)
    assert refresh_every(cfg.datasets_dir, "test_prices") == dt.timedelta(hours=1)
    for unknown in ("test_yaml", "test_nowhere", "checkout_of_a_repository", "../datasets/test_prices", ""):
        assert refresh_every(dirs, unknown) is None


# --- C3: adele.refresh.timeout ----------------------------------------------------------------

def declare(cfg, refresh: str):
    """Write adele.refresh of test_prices and load the catalog."""
    path = cfg.datasets_dir / "test_prices" / "datapackage.yaml"
    path.write_text(path.read_text().replace("refresh: {every: PT1H, lookback: P1D, horizon: P1D}", f"refresh: {refresh}"))
    return load_catalog(cfg.datasets_dir)


def test_the_time_limit_is_the_smaller_of_the_dataset_and_the_server(env):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    assert ds.refresh.timeout is None and ingest.time_limit(cfg, ds) == 1800
    ds = declare(cfg, "{every: PT1H, lookback: P1D, horizon: P1D, timeout: PT5M}")["test_prices"]
    assert ds.refresh.timeout == dt.timedelta(minutes=5) and ingest.time_limit(cfg, ds) == 300
    cfg.fetch_timeout_s = 3
    assert ingest.time_limit(cfg, ds) == 3


def test_a_fetch_is_stopped_at_the_time_limit_of_its_dataset_each_piece(env, monkeypatch):
    cfg, _, _ = env
    catalog = declare(cfg, "{every: PT1H, lookback: P1D, horizon: P1D, max_window: P1D, timeout: PT1S}")
    monkeypatch.setenv("ADELE_TEST_FAULT", "hang")
    t0 = time.monotonic()
    o = ingest.scheduled_fetch(cfg, catalog, catalog["test_prices"], at("2026-03-10T12:00:00"))
    assert cfg.fetch_timeout_s == 1800 and time.monotonic() - t0 < 15
    assert not o.ok and o.pieces == 2
    assert o.error.startswith("2 of 2 pieces failed") and "did not finish within 1 s (time limit)" in o.error


@pytest.mark.parametrize("value", ["PT0S", "soon", "P1M", "30", "null"])
def test_a_bad_timeout_is_refused(env, capsys, value):
    cfg, _, _ = env
    with pytest.raises(CatalogError, match="adele.refresh.timeout"):
        declare(cfg, f"{{every: PT1H, lookback: P1D, horizon: P1D, timeout: {value}}}")
    assert main(cfg, "validate") == 2 and "adele.refresh.timeout" in capsys.readouterr().err


# --- C4: an unknown key under adele.refresh is refused ----------------------------------------

@pytest.mark.parametrize("refresh, message", [
    ("{every: PT1H, lookback: P1D, horizon: P1D, max_windw: PT1H}",
     r"adele.refresh: unknown key max_windw \(allowed: every, lookback, horizon, max_window, timeout\)"),
    ("{every: PT1H, lookback: P1D, horizon: P1D, Timeout: PT1M, step: PT1H}", "adele.refresh: unknown keys Timeout, step"),
    ("{every: PT1H, lookback: P1D, horizont: P1D}", "needs every, lookback and horizon; adele.refresh: unknown key horizont"),
    ("{every: PT0S, lookback: P1D, horizon: P1D}", "adele.refresh.every: it must be longer than zero"),
])
def test_validate_refuses_an_unknown_key_under_refresh(env, capsys, refresh, message):
    cfg, _, _ = env
    with pytest.raises(CatalogError, match=message):
        declare(cfg, refresh)
    assert main(cfg, "validate") == 2 and "adele.refresh" in capsys.readouterr().err


def test_validate_accepts_the_five_keys_of_refresh(env):
    cfg, _, _ = env
    r = declare(cfg, "{every: PT1M, lookback: P1D, horizon: PT0S, max_window: PT6H, timeout: PT90S}")["test_prices"].refresh
    assert (r.every, r.max_window, r.timeout) == (dt.timedelta(minutes=1), dt.timedelta(hours=6), dt.timedelta(seconds=90))
    assert main(cfg, "validate") == 0


# --- C5: a backfill holds the lock of its dataset from its first window to its checks ---------

def stored_span(cfg):
    """The first and the last stored delivery_start, and the longest gap between two stored values."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    return con.execute(
        "SELECT min(d), max(d), max(gap) FROM (SELECT d, d - lag(d) OVER (ORDER BY d) AS gap FROM (SELECT DISTINCT "
        f"delivery_start AS d FROM read_parquet('{cfg.data_dir}/test_prices/prices/*.parquet')))").fetchone()


def test_a_scheduled_fetch_between_two_windows_of_a_backfill_is_refused(env, clock, monkeypatch, capsys):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    before_stop = at("2026-03-01T12:00:00")
    clock[0] = before_stop
    assert ingest.scheduled_fetch(cfg, catalog, ds, before_stop).ok  # the anchor, 9 days before the backfill
    start, now0 = at("2026-02-27T12:00:00"), at("2026-03-10T12:05:00")
    clock[0] = now0 + dt.timedelta(minutes=10)  # the windows of the backfill are stamped 12:15
    seen, fetch_merge = [], ingest._fetch_merge
    state_file = state.path(cfg.data_dir, "test_prices")

    def between_two_windows(*args):
        if len(seen) == 1:  # the first window is merged, the second one has not started
            stamps, clock[0] = clock[0], at("2026-03-10T13:00:00")  # the tick of the next hour: due
            state_before = state_file.read_bytes()
            assert ingest.is_due(ds, state.load(cfg.data_dir, "test_prices"), clock[0])
            with pytest.raises(ingest.FetchError, match="another fetch of test_prices is running"):
                ingest.scheduled_fetch(cfg, catalog, ds, clock[0])
            capsys.readouterr()
            for tick in (("fetch", "test_prices", "--if-due"), ("fetch", "--due"), ("fetch", "test_prices"),
                         ("fetch", "test_prices", "--start", "2026-03-09")):
                assert main(cfg, *tick) == 0  # skipped, the exit code of a skip
                assert capsys.readouterr() == ("", "skip test_prices: another fetch of test_prices is running\n")
            assert main(cfg, "backfill", "test_prices", "--start", "2026-03-09") == 1  # a second backfill
            assert capsys.readouterr().err == "error: another fetch of test_prices is running\n"
            assert main(cfg, "check", "test_prices") == 1
            assert capsys.readouterr().err == "error: another fetch of test_prices is running\n"
            # a skipped tick writes nothing: no attempt is stamped, the dataset stays due
            assert state_file.read_bytes() == state_before
            assert ingest.is_due(ds, state.load(cfg.data_dir, "test_prices"), clock[0])
            clock[0] = stamps
        seen.append(args[3:])
        return fetch_merge(*args)

    monkeypatch.setattr(ingest, "_fetch_merge", between_two_windows)
    outs = ingest.backfill(cfg, catalog, ds, start, now0 + dt.timedelta(days=1), dt.timedelta(days=5), now=now0)
    monkeypatch.setattr(ingest, "_fetch_merge", fetch_merge)
    assert len(outs) == 3 == len(seen) and all(o.ok for o in outs), [o.error for o in outs]  # the backfill completes
    st = state.load(cfg.data_dir, "test_prices")
    assert st["last_scheduled_at"] == now0 and st["status"] == "ok"  # the anchor: the start time of the backfill
    assert st["last_attempt_at"] == now0  # not the stamp of the last window: the backfill counts as a run at now0
    with ingest.dataset_lock(cfg.data_dir, "test_prices"):  # released at the end
        pass
    # the first tick after the backfill, in a later hour than its start: it runs, from the anchor on
    clock[0] = at("2026-03-10T14:05:00")
    assert main(cfg, "fetch", "test_prices", "--if-due") == 0
    assert "test_prices [2026-03-09 12:05, 2026-03-11 14:05) UTC: ok" in capsys.readouterr().out
    assert state.load(cfg.data_dir, "test_prices")["last_scheduled_at"] == clock[0]
    # no hole: the source gives one value per hour, counted from the start of each window
    assert stored_span(cfg) == (start, at("2026-03-11T13:05:00"), dt.timedelta(hours=1))


def test_a_backfill_of_the_past_leaves_the_dataset_as_due_as_before(env, clock):
    """Its windows are stamped with their own times, but they are not attempts of a scheduled run."""
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    clock[0] = at("2026-03-10T12:05:00")
    outs = ingest.backfill(cfg, catalog, ds, at("2026-01-01T00:00:00"), at("2026-01-03T00:00:00"), dt.timedelta(days=1))
    assert len(outs) == 2 and all(o.ok for o in outs)
    st = state.load(cfg.data_dir, "test_prices")
    assert "last_attempt_at" not in st and "last_scheduled_at" not in st and ingest.is_due(ds, st, clock[0])
    assert st["last_fetched_at"] == clock[0]
    assert ingest.scheduled_fetch(cfg, catalog, ds, clock[0]).ok
    clock[0] = at("2026-03-10T12:50:00")
    ingest.backfill(cfg, catalog, ds, at("2026-01-03T00:00:00"), at("2026-01-04T00:00:00"))
    st = state.load(cfg.data_dir, "test_prices")
    assert st["last_attempt_at"] == at("2026-03-10T12:05:00") and st["last_scheduled_at"] == at("2026-03-10T12:05:00")
    assert not ingest.is_due(ds, st, clock[0]) and ingest.is_due(ds, st, at("2026-03-10T13:00:00"))


def test_an_interrupted_backfill_stops_and_keeps_the_anchor(env, clock, monkeypatch, capsys):
    """In this process: the signal is simulated at the start of the second window."""
    cfg, catalog, _ = env
    calls, run_child = [], ingest._run_child

    def second_call_is_interrupted(*args):
        calls.append(args)
        if len(calls) == 2:
            ingest._stop.append("SIGINT")
        return run_child(*args)

    monkeypatch.setattr(ingest, "_run_child", second_call_is_interrupted)
    assert main(cfg, "backfill", "test_prices", "--start", "2026-03-07", "--step-days", "1") == 130  # 5 windows
    out = capsys.readouterr().out
    assert "test_prices: 2 windows, 48 rows, 1 failed; status failing" in out
    assert "failed [2026-03-08 00:00, 2026-03-09 00:00) UTC: interrupted by SIGINT: fetch.py was not started" in out
    st = state.load(cfg.data_dir, "test_prices")
    assert len(calls) == 2 and "last_scheduled_at" not in st and "published_checks" not in st
    assert st["problems"] == ["last fetch failed: interrupted by SIGINT: fetch.py was not started", "never fetched"]
    assert ingest.stopped() is None
    with ingest.dataset_lock(cfg.data_dir, "test_prices"):
        pass
