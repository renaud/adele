"""Ingestion: call a dataset's fetch(start, end), check the result, merge it, run the checks.

Nothing happens silently: a fetch that fails, a result whose columns or types differ from the
descriptor, a null or duplicated key, all set the status to failing and keep the stored data.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import functools
import json
import logging
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from . import checks, raw, state, storage
from .catalog import VERSION_FIELD, Dataset, Table, category_values
from .config import Config
from .storage import ident

log = logging.getLogger("adele.ingest")
UTC = dt.timezone.utc

# Table Schema type --> DuckDB types that a fetch result may have for it (cast to the storage type).
_INTS = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"}
ACCEPTED = {
    "string": {"VARCHAR"},
    "integer": _INTS,
    "number": _INTS | {"FLOAT", "DOUBLE"},
    "boolean": {"BOOLEAN"},
    "datetime": {"TIMESTAMP WITH TIME ZONE"},
    "date": {"DATE"},
    "time": {"TIME"},
    "duration": {"INTERVAL"},
}


class FetchError(Exception):
    pass


class Interrupted(FetchError):
    """SIGTERM or SIGINT asked the command to stop (see stop_on_signals). Not a failure of the source."""


@dataclass
class Outcome:
    dataset: str
    start: dt.datetime
    end: dt.datetime
    ok: bool
    rows: int = 0
    rows_changed: int = 0
    partitions_written: int = 0
    windows_fetched: int = 0  # revisions: none fetches only the parts of the window without stored rows
    interrupted: bool = False  # stopped by SIGTERM or SIGINT: a failed attempt, but no sign that the source fails
    problems: list[str] | None = None
    error: str | None = None
    pieces: int = 1  # a scheduled window longer than adele.refresh.max_window is fetched in pieces
    answers: int = 0  # adele.raw: keep: the answers that download() yielded
    answers_kept: int = 0  # of those, the ones that differ from the last kept answer of their name


EPSILON = dt.timedelta(microseconds=1)  # DuckDB's timestamp resolution: (a, b) = [a + EPSILON, b)


def windows_to_fetch(data_dir: Path, ds: Dataset, start: dt.datetime, end: dt.datetime) -> list[tuple]:
    """The windows to pass to fetch() for [start, end).

    overwrite: the whole window. none: stored rows never change, so only the parts of [start,
    end) that hold no stored value of the window column: the gaps between the distinct stored
    values, each value excluded. A value counts as stored when every table has rows for it.
    A gap may hold no data at all (between two hourly runs); fetch() then returns no rows.
    A table without a time column is left out: each fetch replaces it whole (D22). The catalog
    makes every other table of a `none` dataset share one window column of type datetime.
    """
    if ds.revisions != "none":
        return [(start, end)]
    stored = None
    con = storage.connect()
    try:
        for t in ds.tables.values():
            if not t.has_time:
                continue
            if not storage.partitions(data_dir, t):
                stored = set()
                break
            vals = {r[0] for r in con.execute(
                f"SELECT DISTINCT {ident(t.window)} FROM ({storage.select_sql(data_dir, t)}) "
                f"WHERE {ident(t.window)} >= $s AND {ident(t.window)} < $e", {"s": start, "e": end}).fetchall()}
            stored = vals if stored is None else stored & vals
    finally:
        con.close()
    gaps, lo = [], start
    for v in sorted(stored or ()):
        if v > lo:
            gaps.append((lo, v))
        lo = v + EPSILON
    if lo < end:
        gaps.append((lo, end))
    return gaps


# What a fetch gets from the server's environment: what uv and Python need (paths, locale,
# certificates, proxies, uv and Python settings), plus the secrets that its descriptor declares
# (adele.secrets). Not the other datasets' credentials.
BASE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")
BASE_ENV_PREFIXES = ("UV_", "PYTHON", "XDG_")


def fetch_env(ds: Dataset) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in BASE_ENV or k.startswith(BASE_ENV_PREFIXES)}
    env.update({k: os.environ[k] for k in ds.secrets if k in os.environ})
    return env


SECRET_MIN_LEN = 8  # a shorter value is a setting, not a credential: replacing it would garble the text


def redact(text: str, ds: Dataset) -> str:
    """`text` without the values of the dataset's secrets, as they are and URL-encoded (D34). What
    a fetch.py prints can hold them: requests writes the URL of a failed request in its error, and
    the ENTSO-E token is a parameter of the URL (2026-11-15, WP5.3: the error of an answer 599
    reached the console of a backfill with the token)."""
    for k in ds.secrets:
        v = os.environ.get(k)
        if v and len(v) >= SECRET_MIN_LEN:
            for form in sorted({v, urllib.parse.quote(v, safe=""), urllib.parse.quote_plus(v)}, key=len, reverse=True):
                text = text.replace(form, f"***{k}***")
    return text


def call_fetch(ds: Dataset, windows: list[tuple], timeout_s: float, workdir: Path,
               runner_dir: Path | None = None, raw_dir: Path | None = None) -> dict[str, list[Path]]:
    """Run fetch(start, end) on each window in one child process, and stop it at the time limit.

    A hung source (e.g. an HTTP request without a timeout) would otherwise hold the dataset's
    lock forever: every scheduled run would skip, and the data would go stale silently. A
    thread can't be stopped, a process can. The child gets only the environment of fetch_env().

    A fetch.py with inline script metadata (PEP 723) runs in its own environment, built by
    `uv run --script` from the dependencies it declares; without it, in the server's Python.
    Either way, the child writes each table of each window as Parquet in `workdir/out`: returns
    {table: [paths]}, "_" for a fetch that returns one table.

    `runner_dir`: where the runner of a script is written (see runner_dir()); None: in `workdir`.
    `raw_dir`: for a dataset with adele.raw: keep, the child calls download(start, end) and
    writes each answer there as soon as it comes (raw.ANSWERS lists them), then parse(answers).
    """
    windows_json = json.dumps([[s.isoformat(), e.isoformat()] for s, e in windows])
    mode = ["download", str(raw_dir)] if raw_dir is not None else ["fetch"]
    return _call_runner(ds, [windows_json, *mode], timeout_s, workdir, runner_dir)


def call_parse(ds: Dataset, groups: list[list[raw.Answer]], timeout_s: float, workdir: Path,
               runner_dir: Path | None = None) -> tuple[dict[str, list[Path]], dict[int, str]]:
    """Run parse(answers) on each group of kept answers in one child process (import_answers):
    the tables of group i come back as `<table>.<i>.parquet`, as for the windows of call_fetch.
    A group whose parse failed comes back in the second dict, group --> error; its files, if
    any, are to be ignored."""
    spec = workdir / "groups.json"
    spec.write_text(json.dumps([[{"name": a.name, "url": a.url, "received_at": a.received_at.isoformat(),
                                  "path": str(a.path.resolve())} for a in g] for g in groups]))
    files = _call_runner(ds, [str(spec), "parse"], timeout_s, workdir, runner_dir)
    errors_path = workdir / "out" / "errors.jsonl"
    errors = {}
    if errors_path.exists():
        for line in errors_path.read_text().splitlines():
            e = json.loads(line)
            errors[e["group"]] = e["error"]
    return files, errors


def _call_runner(ds: Dataset, rest: list[str], timeout_s: float, workdir: Path,
                 runner_dir: Path | None) -> dict[str, list[Path]]:
    out = workdir / "out"
    out.mkdir()
    args = [str(ds.folder / "fetch.py"), rest[0], str(out), *rest[1:]]
    if ds.script_metadata is not None:
        uv = shutil.which("uv")
        if uv is None:
            raise FetchError("uv not found on PATH: needed to run a fetch.py that declares its dependencies")
        runner = _write_runner(runner_dir or workdir, runner_source(ds.script_metadata))
        cmd = [uv, "run", "--quiet", "--no-project", "--script", str(runner), *args]
    else:
        runner = _write_runner(workdir, _RUNNER_BODY)
        cmd = [sys.executable, str(runner), *args]
    _run_child(ds, cmd, timeout_s, workdir)
    files: dict[str, list[Path]] = {}
    for p in sorted(out.glob("*.parquet")):
        files.setdefault(p.name.split(".")[0], []).append(p)
    return files


# The runner calls fetch(start, end) on each window and writes each table with DuckDB, which
# keeps the types (timezone-aware timestamps, durations as INTERVAL) without pyarrow.
# Arguments: fetch.py, the windows (JSON), the output folder, then the mode:
# - fetch (or none): fetch(start, end) per window.
# - download <raw folder>: per window, download(start, end), each answer written to the raw
#   folder as it comes (the body, then its line in answers.jsonl), then parse(answers) (D33).
# - parse: the second argument is a JSON file of groups of kept answers; parse(answers) per group.
_RUNNER_BODY = """
import datetime as dt
import gzip
import importlib.util
import json
import os
import re
import sys

import duckdb

spec = importlib.util.spec_from_file_location("adele_fetch", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
out = sys.argv[3]
mode = sys.argv[4] if len(sys.argv) > 4 else "fetch"
con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def write(i, result, nothing):
    if result is None:
        raise RuntimeError(nothing)
    tables = result if isinstance(result, dict) else {"_": result}
    for name, frame in tables.items():
        con.register("frame", frame)
        con.execute(f"COPY frame TO '{out}/{name}.{i}.parquet' (FORMAT parquet)")
        con.unregister("frame")


def download(i, start, end, folder):
    answers = []
    for k, a in enumerate(module.download(start, end)):
        if not isinstance(a, dict) or not isinstance(a.get("body"), (bytes, bytearray)) \\
                or not isinstance(a.get("name"), str) or not NAME.fullmatch(a["name"]):
            raise RuntimeError("download must yield dicts with name (a file name), body (bytes) and url")
        received = dt.datetime.now(dt.timezone.utc)
        body = bytes(a["body"])
        file = f"{i}.{k}.body"
        with open(os.path.join(folder, file), "wb") as fh:
            fh.write(body)
        line = {"name": a["name"], "url": a.get("url"), "received_at": received.isoformat(), "file": file}
        with open(os.path.join(folder, "answers.jsonl"), "a") as fh:
            fh.write(json.dumps(line) + "\\n")
        answers.append({"name": a["name"], "url": a.get("url"), "body": body, "received_at": received})
    return answers


if mode == "parse":
    with open(sys.argv[2]) as fh:
        groups = json.load(fh)
    for i, group in enumerate(groups):  # a group that fails goes to errors.jsonl, and the next one is parsed
        try:
            answers = []
            for a in group:
                with open(a["path"], "rb") as fh:
                    body = fh.read()
                answers.append({"name": a["name"], "url": a["url"],
                                "received_at": dt.datetime.fromisoformat(a["received_at"]),
                                "body": gzip.decompress(body) if a["path"].endswith(".gz") else body})
            write(i, module.parse(answers), "parse returned nothing")
        except Exception as e:
            with open(os.path.join(out, "errors.jsonl"), "a") as fh:
                fh.write(json.dumps({"group": i, "error": f"{type(e).__name__}: {e}"}) + "\\n")
else:
    windows = [tuple(dt.datetime.fromisoformat(x) for x in w) for w in json.loads(sys.argv[2])]
    for i, (start, end) in enumerate(windows):
        if mode == "download":
            write(i, module.parse(download(i, start, end, sys.argv[5])), f"parse returned nothing for [{start}, {end})")
        else:
            write(i, module.fetch(start, end), f"fetch returned nothing for [{start}, {end})")
"""
RUNNER_DEPS = ("pandas>=2.2", "duckdb>=2.0")


def runner_source(meta: dict) -> str:
    """fetch.py's dependencies plus what the runner needs, as a PEP 723 script."""
    deps = list(meta.get("dependencies", []))
    named = {re.split(r"[<>=!~;\[ ]", d, maxsplit=1)[0].lower() for d in deps}
    deps += [d for d in RUNNER_DEPS if re.split(r"[<>=]", d)[0] not in named]
    head = ["# /// script"]
    if meta.get("requires-python"):
        head.append(f"# requires-python = {json.dumps(meta['requires-python'])}")
    head += [f"# dependencies = {json.dumps(deps)}", "# ///"]
    return "\n".join(head) + "\n" + _RUNNER_BODY


def runner_dir(cfg: Config, ds: Dataset) -> Path | None:
    """The folder of the uv runner of a dataset, the same at every fetch: <cache>/runners/<dataset>.

    uv keeps one environment per path of a script. In a new temporary folder at each fetch, the
    runner had a new path each time and uv built the environment again (8.7 s per fetch
    measured, 0.3 s with the same path). <cache> is Config.cache_path, outside the data folder.
    One folder per dataset: two datasets may run at the same time, and Python puts the folder
    of the runner first on its import path, so the folder holds nothing but the runner. For
    the same reason no other user may write in it: `runners` and the folder are made with mode
    0700, and each must be a real folder (no link) of this user with that mode. If not, or if
    the folder can't be made: None and a warning, and the fetch uses its temporary folder as
    before (it works, uv is slow).
    """
    try:
        folder = cfg.cache_path / "runners" / ds.id
        for p in (folder.parent, folder):
            p.mkdir(mode=0o700, parents=True, exist_ok=True)
            st = p.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
                raise OSError(f"{p} must be a folder of this user with mode 0700")
    except (OSError, RuntimeError) as e:
        log.warning("%s: no fixed folder for the uv runner (%s). A temporary folder is used: uv builds the "
                    "environment again at each fetch", ds.id, e)
        return None
    return folder


def _write_runner(folder: Path, source: str) -> Path:
    """`folder/_runner.py` with this text. Written (temp file + rename) only if it differs."""
    path = folder / "_runner.py"
    try:
        if not path.is_symlink() and path.read_text() == source:
            return path
    except OSError:
        pass
    tmp = folder / f"._runner.tmp-{os.getpid()}"
    tmp.write_text(source)
    os.replace(tmp, path)
    return path


# --- SIGTERM and SIGINT ------------------------------------------------------------------------
_stop: list[str] = []  # the signals received under stop_on_signals(), by name, the first one first
_running: list[subprocess.Popen] = []  # the fetch.py that runs now


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the child and what it started (uv and its python): it leads its own process group."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _on_signal(signum, _frame) -> None:
    _stop.append(signal.Signals(signum).name)
    signal.signal(signum, signal.SIG_DFL)  # a second signal ends the command at once
    for proc in _running:
        _kill_group(proc)


@contextmanager
def stop_on_signals():
    """While a fetch command runs: SIGTERM and SIGINT stop it in order.

    Without this, SIGTERM ended the server at once: fetch.py (in its own session) kept running
    without a time limit, and state.json showed nothing. Now the signal kills the process group
    of the running fetch.py and is noted (stopped()). The fetch that was cut is recorded as a
    failed attempt (Interrupted), a merge or a check that runs is finished, and nothing new
    starts: no further piece, window or dataset. The lock is released as after any fetch.
    Main thread only. The handlers of before are put back at the end.
    """
    old = {s: signal.signal(s, _on_signal) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for s, handler in old.items():
            signal.signal(s, signal.SIG_DFL if handler is None else handler)
        _stop.clear()


def stopped() -> str | None:
    """The name of the signal that asked the command to stop, or None."""
    return _stop[0] if _stop else None


def _run_child(ds: Dataset, cmd: list[str], timeout_s: float, workdir: Path) -> None:
    if stopped():
        raise Interrupted(f"interrupted by {stopped()}: fetch.py was not started")
    log_path = workdir / "fetch.log"
    with open(log_path, "w") as log_fh:
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True,
                                cwd=ds.folder, env=fetch_env(ds))
        _running.append(proc)
        try:
            if stopped():  # the signal came while the child started: its handler did not see the child
                _kill_group(proc)
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            proc.wait()
            raise FetchError(f"fetch did not finish within {timeout_s:g} s (time limit); stopped") from None
        except BaseException:  # e.g. KeyboardInterrupt without stop_on_signals(): no child is left behind
            _kill_group(proc)
            proc.wait()
            raise
        finally:
            _running.remove(proc)
    if rc != 0 and stopped():
        raise Interrupted(f"interrupted by {stopped()}: fetch.py was stopped")
    text = redact(log_path.read_text(errors="replace"), ds)  # it goes to the error, state.json, alerts.log and the log
    if rc != 0:
        tail = " | ".join(ln.strip() for ln in text.strip().splitlines()[-3:] if ln.strip()) or "no output"
        raise FetchError(f"fetch.py exited with code {rc}: {tail[-800:]}")
    if text.strip():
        log.info("fetch.py of %s said:\n%s", ds.id, text[-4000:])


@contextmanager
def dataset_lock(data_dir: Path, ds_id: str):
    p = data_dir / ds_id / ".lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FetchError(f"another fetch of {ds_id} is running") from None
        yield


def scheduled_window(ds: Dataset, now: dt.datetime, s: dict | None = None) -> tuple[dt.datetime, dt.datetime]:
    """The window of a scheduled run: [last - lookback, now + horizon).

    last is `last_scheduled_at` in the state `s`: the `now` of the last scheduled run that
    succeeded. So the time of a stop (server down, source failing, a long backfill) is fetched
    by the next run, however long the stop was. A window that started at now - lookback left
    that time out for good. Without the field (first run, or no state given), last is `now`.
    A field later than `now` (a clock that was set back) also counts as `now`.

    Giving up: when the scheduled runs have failed for longer than the lookback (`failing_since`
    in `s`), last is `now` again, whatever the field says. A stretch that fails is retried for
    one lookback after its first failed run, not for ever: a part that can never be fetched
    must not keep the newer data out.
    """
    s = s or {}
    last = s.get("last_scheduled_at")
    if last is None or last > now or _gives_up(ds, s, now):
        last = now
    return last - ds.refresh.lookback, now + ds.refresh.horizon


def _gives_up(ds: Dataset, s: dict, now: dt.datetime) -> bool:
    since = s.get("failing_since")
    return since is not None and now - since > ds.refresh.lookback


def split_window(start: dt.datetime, end: dt.datetime, length: dt.timedelta | None) -> list[tuple]:
    """[start, end) as successive windows of `length`, oldest first; the last one may be shorter.
    One window when `length` is None or [start, end) is not longer."""
    if length is None or end - start <= length:
        return [(start, end)]
    out, s = [], start
    while s < end:
        e = min(s + length, end)
        out.append((s, e))
        s = e
    return out


def is_due(ds: Dataset, s: dict, now: dt.datetime) -> bool:
    """`now` lies in a later period of adele.refresh.every than `last_attempt_at` (state.is_due)."""
    return state.is_due(s, ds.refresh.every, now)


def time_limit(cfg: Config, ds: Dataset) -> float:
    """Seconds that one call of fetch.py may last: adele.refresh.timeout, at most the server's fetch_timeout_s."""
    if ds.refresh.timeout is None:
        return cfg.fetch_timeout_s
    return min(cfg.fetch_timeout_s, ds.refresh.timeout.total_seconds())


def fetch_window(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, start: dt.datetime, end: dt.datetime,
                 run_checks: bool = True) -> Outcome:
    """Fetch one explicit window. It is not a scheduled run: `last_scheduled_at` stays."""
    with dataset_lock(cfg.data_dir, ds.id):
        return _fetch_window(cfg, catalog, ds, start, end, run_checks)


def _fetch_window(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, start: dt.datetime, end: dt.datetime,
                  run_checks: bool) -> Outcome:
    """fetch_window for a caller that holds the dataset's lock."""
    st = state.load(cfg.data_dir, ds.id)
    old_status = st.get("status")
    out = _fetch_merge(cfg, ds, st, start, end)
    _settle(cfg, catalog, ds, st, out, old_status, run_checks)
    return out


def scheduled_fetch(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, now: dt.datetime) -> Outcome:
    """One scheduled run: fetch scheduled_window(), then set `last_scheduled_at` to `now`.

    The field moves only when the whole run succeeded. A run that failed, or that was skipped
    because of the lock (FetchError), keeps it: the next run starts from the same place.

    A window longer than adele.refresh.max_window is fetched in pieces of that length, oldest
    first, each one merged before the next starts (each piece is one child process with its own
    time limit). A piece that fails does not stop the run: every piece is attempted, as in a
    backfill, so the data after a piece that can't be fetched still comes in. The run counts as
    failed when at least one piece failed. Checks, status and alert come once, at the end, as
    for one fetch. The lock is held for the whole run.

    `failing_since` is the `now` of the first run that failed since the last one that succeeded.
    A run that starts more than one lookback after it gives up (scheduled_window): the first
    such run writes the stretch that it leaves out, [last_scheduled_at - lookback, now -
    lookback), to the log and to alerts.log, once. A run that succeeds clears the field.

    A run that a signal stops (Interrupted) is a failed run: the later pieces are not attempted
    and `last_scheduled_at` stays. But it does not set `failing_since`: it says nothing about
    the source, and the server may be down for longer than the lookback after it. With the
    field set, the first run after such a stop would give up the time of the stop.
    """
    with dataset_lock(cfg.data_dir, ds.id):
        st = state.load(cfg.data_dir, ds.id)
        old_status = st.get("status")
        last = st.get("last_scheduled_at")
        if last and last > now:
            log.warning("%s: last_scheduled_at %s is later than now %s (clock set back?): window as for a first run",
                        ds.id, last, now)
        start, end = scheduled_window(ds, now, st)
        if _gives_up(ds, st, now) and "given_up" not in st and last and last < now:
            left = (last - ds.refresh.lookback, start)
            st["given_up"] = [left[0].isoformat(), left[1].isoformat()]
            _alert(cfg, f"{ds.id}: gave up on {', '.join(ds.windows) or 'the window'} [{left[0]:%Y-%m-%d %H:%M}, {left[1]:%Y-%m-%d %H:%M}) UTC: "
                        f"the scheduled runs have failed since {st['failing_since']:%Y-%m-%d %H:%M} UTC, longer than "
                        f"the lookback. The window is [now - lookback, now + horizon) again")
            state.save(cfg.data_dir, ds.id, st)  # written once, also if this run is cut short
        todo = split_window(start, end, ds.refresh.max_window)
        out = Outcome(ds.id, start, end, ok=True, pieces=len(todo))
        failed = []
        for i, (s, e) in enumerate(todo):
            if i:  # the piece before is done: write it down, and is_due sees an attempt (as in a backfill)
                state.save(cfg.data_dir, ds.id, st)
            o = _fetch_merge(cfg, ds, st, s, e)
            out.rows += o.rows
            out.rows_changed += o.rows_changed
            out.partitions_written += o.partitions_written
            out.windows_fetched += o.windows_fetched
            out.answers += o.answers
            out.answers_kept += o.answers_kept
            if len(todo) > 1:
                log.info("scheduled %s piece %d of %d [%s, %s): ok=%s rows=%s changed=%s %s", ds.id, i + 1,
                         len(todo), s, e, o.ok, o.rows, o.rows_changed, o.error or "")
            if not o.ok:
                failed.append(o)
            if o.interrupted:
                break
        st["last_window"] = [start.isoformat(), end.isoformat()]
        if failed and failed[-1].interrupted:
            out.ok, out.interrupted = False, True
            out.error = failed[-1].error
            if len(todo) > 1:
                out.error += f" (piece {i + 1} of {len(todo)}; the later pieces were not attempted)"
            st["last_error"] = out.error
        elif failed:
            out.ok = False
            if len(todo) > 1:
                out.error = _failed_text(failed, len(todo), "pieces")
            else:
                out.error = failed[0].error
                if now - ds.refresh.lookback - start > ds.refresh.lookback:  # longer than a usual window: say so
                    hours = int((end - start).total_seconds() // 3600)
                    out.error += (f" (one window of {hours // 24} d {hours % 24} h: the last scheduled run that "
                                  f"succeeded was at {last:%Y-%m-%d %H:%M} UTC)")
            st["last_error"] = out.error
            st.setdefault("failing_since", now)
        else:
            st["last_scheduled_at"] = now
            st.pop("failing_since", None)
            st.pop("given_up", None)
            _note_versions_since(ds, st)
        _settle(cfg, catalog, ds, st, out, old_status, run_checks=True)
    return out


def _note_versions_since(ds: Dataset, st: dict) -> None:
    """append-only: the first time that the scheduled runs take over, written once (D30).

    Called when `last_scheduled_at` is set: after a scheduled run that succeeded, or at the end
    of a backfill that reached the present. Before that time, the rows were fetched in bulk
    (a backfill, explicit windows), and their fetched_at says nothing about when the source
    published them: an `as_of` before it is refused.
    """
    if ds.revisions == "append-only":
        st.setdefault("versions_since", state.now())


def _fetch_merge(cfg: Config, ds: Dataset, st: dict, start: dt.datetime, end: dt.datetime) -> Outcome:
    """Fetch [start, end) and merge it. Notes the times and the error in `st`. The caller holds
    the dataset's lock and saves `st`."""
    out = Outcome(ds.id, start, end, ok=False)
    st["last_attempt_at"] = state.now()
    st["last_window"] = [start.isoformat(), end.isoformat()]
    con = storage.connect()
    workdir = tempfile.TemporaryDirectory(prefix=f"adele-{ds.id}-")
    try:
        for t in ds.tables.values():
            storage.check_layout(cfg.data_dir, t)
            storage.check_columns(con, cfg.data_dir, t)
        windows = windows_to_fetch(cfg.data_dir, ds, start, end)
        out.windows_fetched = len(windows)
        if windows:
            fixed = runner_dir(cfg, ds) if ds.script_metadata is not None else None
            batches = _as_tables(ds, _call_keeping_raw(cfg, ds, windows, Path(workdir.name), fixed, out))
            # append-only: the time at which adele had these values, the same for every table of
            # this call (D30). Not the start of the run: a source may publish a value while it runs.
            fetched_at = dt.datetime.now(UTC)
            for t in ds.tables.values():
                out.rows += _stage(con, t, batches[t.name], windows)
            merge = {"overwrite": storage.merge_overwrite, "none": storage.merge_append,
                     "append-only": functools.partial(storage.merge_versions, fetched_at=fetched_at)}[ds.revisions]
            for t in ds.tables.values():
                m = (merge(con, cfg.data_dir, t, f"_batch_{t.name}") if t.has_time
                     else storage.merge_replace(con, cfg.data_dir, t, f"_batch_{t.name}"))
                out.rows_changed += m.rows_changed
                out.partitions_written += len(m.partitions_written)
        st["last_fetched_at"] = st["last_attempt_at"]
        if out.rows_changed:
            st["last_changed_at"] = st["last_attempt_at"]
        st.pop("last_error", None)
        out.ok = True
    except Interrupted as e:
        out.error, out.interrupted = str(e), True
        st["last_error"] = out.error
        log.warning("fetch of %s: %s", ds.id, e)
    except Exception as e:  # noqa: BLE001 - any failure of a fetch must set the status
        out.error = f"{type(e).__name__}: {e}"
        st["last_error"] = out.error
        log.exception("fetch of %s failed", ds.id)
    finally:
        con.close()
        workdir.cleanup()
    return out


def _settle(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, st: dict, out: Outcome,
            old_status: str | None, run_checks: bool) -> None:
    """After a fetch: run the checks (or keep the known problems), set the status, save the
    state, alert on a change of status. The caller holds the dataset's lock.

    An interrupted fetch runs no checks (the command is stopping) and alerts on a change of
    status in any case, so that alerts.log shows why the status is failing."""
    if run_checks and not out.interrupted:
        problems = checks.run_checks(catalog, ds, cfg.data_dir, cfg.query)
        st["published_checks"] = {"count": len(ds.checks), "at": state.now().isoformat()}
    else:  # the known problems, without the line of an earlier fetch that failed
        problems = [p for p in st.get("problems", []) if not p.startswith("last fetch failed: ")]
    if out.error:
        problems = [f"last fetch failed: {out.error}"] + list(problems)
    out.problems = problems
    st["problems"] = problems
    st["status"] = "failing" if problems else "ok"
    st["last_rows"] = {"fetched": out.rows, "changed": out.rows_changed}
    state.save(cfg.data_dir, ds.id, st)
    if run_checks or out.interrupted:
        alert_on_change(cfg, ds.id, old_status, st["status"], problems)


def recheck(cfg: Config, catalog: dict[str, Dataset], ds: Dataset) -> list[str]:
    """Run the checks on the stored data and update the status (the command `check`)."""
    with dataset_lock(cfg.data_dir, ds.id):
        return _recheck(cfg, catalog, ds)


def _recheck(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, backfill: tuple | None = None) -> list[str]:
    """recheck for a caller that holds the dataset's lock; at the end of a backfill with `backfill`.

    `backfill`: (start, now, reached, attempt_before). `now` is the time at which the backfill
    started, `reached` says that it reached the present with at least one window that
    succeeded, `attempt_before` is `last_attempt_at` as it was before the backfill.

    A backfill that reached the present counts as a scheduled run made at `now`:
    `last_scheduled_at` moves there. Except when the backfill started after last_scheduled_at -
    lookback: the time before its start is still to fetch, and the field stays, so the next
    scheduled run fetches it. The field never moves back. When it moves, `failing_since` is
    cleared: the scheduled runs start again from the backfill, and a failure of theirs is
    retried for one lookback from then on. With the old value, the first run after a long
    backfill would give up at once on the time that the backfill lasted.

    `last_attempt_at` decides when the next scheduled run is due (is_due). The windows of a
    backfill stamped it with their own times, the last one just now: the timer's ticks were
    skipped while the backfill held the lock, and the first tick after it would find the
    dataset not due. So the field is set to `now` when the backfill counts as a scheduled run,
    and back to `attempt_before` when it does not: the first tick in a later period of `every`
    than that time runs.
    """
    st = state.load(cfg.data_dir, ds.id)
    if backfill:
        start, now, reached, attempt_before = backfill
        last = st.get("last_scheduled_at")
        moved = reached and (last is None or (last < now and start <= last - ds.refresh.lookback))
        if moved:
            st["last_scheduled_at"] = now
            st.pop("failing_since", None)
            st.pop("given_up", None)
            _note_versions_since(ds, st)
        st["last_attempt_at"] = now if moved else attempt_before
        if st["last_attempt_at"] is None:
            del st["last_attempt_at"]
    old = st.get("status")
    problems = checks.run_checks(catalog, ds, cfg.data_dir, cfg.query)
    st["published_checks"] = {"count": len(ds.checks), "at": state.now().isoformat()}
    if st.get("last_error"):
        problems = [f"last fetch failed: {st['last_error']}"] + problems
    st["problems"] = problems
    st["status"] = "failing" if problems else "ok"
    state.save(cfg.data_dir, ds.id, st)
    alert_on_change(cfg, ds.id, old, st["status"], problems)
    return problems


def alert_on_change(cfg: Config, ds_id: str, old: str | None, new: str, problems: list[str]) -> None:
    """POC: a line in alerts.log. Email to cfg.admin_email comes later (TODOs.md, POC 2)."""
    if old == new:
        return
    _alert(cfg, f"{ds_id}: {old} --> {new}" + ("".join(f" | {p}" for p in problems)))


def _alert(cfg: Config, text: str) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    line = f"{state.now().isoformat()} {text}"
    with open(cfg.log_dir / "alerts.log", "a") as fh:
        fh.write(line + "\n")
    log.warning("ALERT %s", line)


def _failed_text(failed: list[Outcome], total: int, what: str) -> str:
    """'2 of 7 pieces failed: [start, end), [start, end) (UTC); first error: ...'. Three windows at most."""
    shown = ", ".join(f"[{o.start:%Y-%m-%d %H:%M}, {o.end:%Y-%m-%d %H:%M})" for o in failed[:3])
    more = f" and {len(failed) - 3} more" if len(failed) > 3 else ""
    return f"{len(failed)} of {total} {what} failed: {shown}{more} (UTC); first error: {failed[0].error}"


def _as_tables(ds: Dataset, files: dict[str, list[Path]]) -> dict[str, list[Path]]:
    if "_" in files:
        if len(ds.tables) != 1:
            raise FetchError(f"fetch must return a dict of tables {sorted(ds.tables)}")
        if len(files) > 1:
            raise FetchError("fetch returned a single table for some windows and a dict for others")
        return {next(iter(ds.tables)): files["_"]}
    if not files:
        raise FetchError("fetch returned nothing")
    missing, extra = set(ds.tables) - set(files), set(files) - set(ds.tables)
    if missing or extra:
        raise FetchError(f"fetch returned tables {sorted(files)}, declared {sorted(ds.tables)}")
    return files


def _call_keeping_raw(cfg: Config, ds: Dataset, windows: list[tuple], workdir: Path, fixed: Path | None,
                      out: Outcome) -> dict[str, list[Path]]:
    """call_fetch; with adele.raw: keep, the answers that download() yielded then go to the archive
    (raw.py), also when the child failed: a parse that raised, the time limit, a signal (D33).

    A failure to keep them fails the fetch, with the error of the child first if there was one.
    Except after a signal: the fetch is then recorded as interrupted, and the failure is logged."""
    if not ds.keeps_raw:
        return call_fetch(ds, windows, time_limit(cfg, ds), workdir, fixed)
    folder = workdir / "raw"
    folder.mkdir()
    failure: BaseException | None = None
    try:
        return call_fetch(ds, windows, time_limit(cfg, ds), workdir, fixed, raw_dir=folder)
    except BaseException as e:
        failure = e
        raise
    finally:
        try:
            out.answers, out.answers_kept = raw.keep_work_answers(cfg.data_dir, ds.id, folder)
        except Exception as e:  # noqa: BLE001 - not keeping an answer is a failure of the fetch
            log.exception("%s: the raw answers were not kept", ds.id)
            why = f"the raw answers were not kept: {type(e).__name__}: {e}"
            if failure is None:
                raise FetchError(why) from e  # noqa: B012 - replaces the result on purpose
            # a signal (Interrupted) or Ctrl-C / exit (not an Exception) keeps its meaning: only logged
            if isinstance(failure, Exception) and not isinstance(failure, Interrupted):
                raise FetchError(f"{failure}; and {why}") from e  # noqa: B012


def _window_filter(t: Table, s: dt.datetime, e: dt.datetime) -> str:
    """The rows of `t` that belong to the window [s, e): a source may ignore the window, the server filters.

    A timestamp window column: its value lies in [s, e). A date column of a table by calendar
    period (D26): the period overlaps [s, e), its start and end taken at midnight in the zone of
    the table. With "first instant inside", a table by month fetched with a lookback of 3 days
    kept no row.

    The date column is cast to DATE first: pandas returns an empty column of dates as objects,
    which DuckDB reads as type NULL, and NULL + INTERVAL has no single meaning (the fetch failed).
    """
    w = ident(t.window)
    lo, hi = storage.ts_literal(s), storage.ts_literal(e)
    if not t.window_is_date:
        return f"{w} >= {lo} AND {w} < {hi}"
    tz = storage.sql_str(t.timezone)
    d = f"CAST({w} AS DATE)"
    return (f"timezone({tz}, CAST({d} AS TIMESTAMP)) < {hi} AND "
            f"timezone({tz}, CAST({d} + INTERVAL 1 {t.period.upper()} AS TIMESTAMP)) > {lo}")


def _stage(con: duckdb.DuckDBPyConnection, t: Table, files: list[Path], windows: list[tuple]) -> int:
    """Check one fetched table against its schema; keep the rows of its windows in a temp table.

    `files`: the Parquet files that the child wrote for this table, `<table>.<i>.parquet` for
    windows[i]. Each file keeps only the rows of its own window, on the table's window column
    (_window_filter). A table without a time column (D22) has no window: each call of fetch()
    returns the whole table, so the file of the last window is the table, and it must hold at
    least one row (an empty answer would delete the stored table).
    """
    raw = f"_raw_{t.name}"
    paths = "[" + ", ".join(storage.sql_str(f) for f in files) + "]"
    con.execute(f"CREATE OR REPLACE TEMP VIEW {raw} AS SELECT * FROM read_parquet({paths}, union_by_name = true)")
    got = {r[0]: r[1] for r in con.execute(f"DESCRIBE SELECT * FROM {raw}").fetchall()}
    declared = {f["name"]: f["type"] for f in t.fields}
    errors = []
    if set(got) != set(declared):
        missing, extra = sorted(set(declared) - set(got)), sorted(set(got) - set(declared))
        errors.append(f"columns differ from the descriptor: missing {missing}, not declared {extra}")
    for name, ftype in declared.items():
        if name in got and got[name] not in ACCEPTED[ftype] and got[name] != '"NULL"':
            hint = ""
            if ftype == "date" and got[name].startswith("TIMESTAMP"):
                hint = (" (a calendar period is a date: return datetime.date values, e.g. with pandas "
                        "`.dt.date`, not timestamps)")
            elif got[name] == "TIMESTAMP":
                hint = " (timestamps must be timezone-aware)"
            errors.append(f"{name}: got {got[name]}, declared {ftype}{hint}")
    if errors:
        raise FetchError(f"{t.sql_name}: schema check failed: " + "; ".join(errors))
    types = t.storage_types()
    cols = ", ".join(f"CAST({ident(c)} AS {types[c]}) AS {ident(c)}" for c in t.field_names)
    batch = f"_batch_{t.name}"
    if not t.has_time:
        last = max(files, key=lambda f: int(f.name.split(".")[1]))
        parts = [f"SELECT * FROM read_parquet({storage.sql_str(last)})"]
    else:
        parts = []
        for f in files:
            s, e = windows[int(f.name.split(".")[1])]
            parts.append(f"SELECT * FROM read_parquet({storage.sql_str(f)}) WHERE {_window_filter(t, s, e)}")
    con.execute(f"CREATE OR REPLACE TEMP TABLE {batch} AS SELECT {cols} FROM ("
                + " UNION ALL BY NAME ".join(parts) + ")")
    con.execute(f"DROP VIEW {raw}")
    if not t.has_time and not con.execute(f"SELECT count(*) FROM {batch}").fetchone()[0]:
        raise FetchError(f"{t.sql_name}: fetch returned no row for this table without a time column: each fetch "
                         "replaces it whole, so an empty answer is an error and the stored table stays (D22)")
    if t.period in ("month", "year"):  # stored as their first day (D26)
        c = ident(t.time_field)
        bad = con.execute(f"SELECT DISTINCT {c} FROM {batch} WHERE {c} <> CAST(date_trunc('{t.period}', {c}) AS DATE) "
                          f"ORDER BY 1 LIMIT 3").fetchall()
        if bad:
            raise FetchError(f"{t.sql_name}: {t.time_field} must be the first day of its {t.period}, got "
                             f"{[str(b[0]) for b in bad]}")
    pk = ", ".join(ident(k) for k in t.primary_key)
    nulls = con.execute(f"SELECT count(*) FROM {batch} WHERE "
                        + " OR ".join(f"{ident(k)} IS NULL" for k in t.primary_key)).fetchone()[0]
    if nulls:
        raise FetchError(f"{t.sql_name}: {nulls} fetched rows have a null in the primary key ({pk})")
    dups = con.execute(f"SELECT {pk}, count(*) AS n FROM {batch} GROUP BY ALL HAVING n > 1 LIMIT 3").fetchall()
    if dups:
        raise FetchError(f"{t.sql_name}: the source delivered duplicates on ({pk}), e.g. {dups}")
    for f in t.fields:
        values = category_values(f)
        if values is None:
            continue
        bad = con.execute(f"SELECT DISTINCT {ident(f['name'])} FROM {batch} WHERE {ident(f['name'])} IS NOT NULL "
                          f"AND NOT list_contains($v, {ident(f['name'])}) LIMIT 10", {"v": values}).fetchall()
        if bad:
            raise FetchError(f"{t.sql_name}: {f['name']} has values not declared in categories: {[b[0] for b in bad]}")
    return con.execute(f"SELECT count(*) FROM {batch}").fetchone()[0]


def backfill(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, start: dt.datetime, end: dt.datetime,
             step: dt.timedelta | None = None, now: dt.datetime | None = None) -> list[Outcome]:
    """Call fetch on successive windows, then run the checks once.

    The step: `step`, else adele.refresh.max_window, else 365 days. `now`: the time at which the
    backfill started. A backfill may last days. When it reached the present (end >= now),
    `last_scheduled_at` moves to `now` (see _recheck): the first scheduled run after it starts
    at now - lookback, not at its own time - lookback. Also when some windows failed: one
    window that can't be fetched must not undo days of backfill. The failed windows are in the
    outcomes and in the log; the scheduled runs fetch again only those from now - lookback on.
    When every window failed, nothing was backfilled and the field stays.

    The lock of the dataset is held from before the first window until after the checks. With
    one lock per window, a scheduled run could start between two windows: the next window then
    met the lock and the backfill died there (FetchError), and that run moved
    `last_scheduled_at` to its own time, which the backfill never moves back: the time between
    the end of the backfill and that run minus the lookback was never fetched. Now a scheduled
    run, a fetch by hand or a second backfill is refused meanwhile (FetchError, "another fetch
    of ... is running") and writes nothing.
    """
    now = now or state.now()
    step = step or ds.refresh.max_window or dt.timedelta(days=365)
    outcomes = []
    with dataset_lock(cfg.data_dir, ds.id):
        attempt_before = state.load(cfg.data_dir, ds.id).get("last_attempt_at")
        for s, e in split_window(start, end, step) if start < end else []:
            o = _fetch_window(cfg, catalog, ds, s, e, run_checks=False)
            log.info("backfill %s [%s, %s): ok=%s rows=%s changed=%s %s", ds.id, s, e, o.ok, o.rows, o.rows_changed,
                     o.error or "")
            outcomes.append(o)
            if o.interrupted:  # stopped by a signal: no further window, no checks, and the anchor stays
                return outcomes
        failed = [o for o in outcomes if not o.ok]
        if failed:
            log.warning("backfill %s: %s", ds.id, _failed_text(failed, len(outcomes), "windows"))
        reached = end >= now and len(failed) < len(outcomes)
        _recheck(cfg, catalog, ds, backfill=(start, now, reached, attempt_before))
    return outcomes


@dataclass
class Imported:
    answers: int = 0  # found in the folder
    skipped: int = 0  # older than the newest stored version: imported before
    groups: int = 0  # merged: the answers received at the same time are parsed together
    kept: int = 0  # added to the raw archive
    rows: int = 0
    rows_changed: int = 0
    first: dt.datetime | None = None
    last: dt.datetime | None = None
    failed: list[tuple[dt.datetime, list[Path], str]] = field(default_factory=list)  # (received_at, files, error)
    problems: list[str] | None = None


def import_answers(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, folder: Path) -> Imported:
    """Parse answers that another program kept (the Swissgrid poller), or an archive of adele, as
    if adele had fetched each one at the time it was received (WP4, point 8; D33).

    In time order, each group of answers received at the same time is parsed by the dataset's
    parse(), kept in the raw archive, and merged as a version stamped with that time. Each group
    keeps the rows of the window that a scheduled run at that time would have had:
    [received - every - lookback, received + horizon). A group whose parse or schema check fails
    is kept in the archive, listed in `failed`, and not merged; the next groups go on.

    The dataset must keep raw answers and be `append-only`. Refused once a scheduled run has
    happened, and when the dataset holds versions that adele fetched (a backfill, a fetch with
    --start or --end): the stamps of an import must come before adele's own. An import that
    stopped can be run again: `imported` in state.json, written before each group is merged,
    holds the first and last time imported. The answers older than the newest stored version are
    skipped; the group of that version is merged again, since a hard stop may have left it in
    part (merge_versions with `resume`). `versions_since` becomes the time of the first group
    merged (unless set).
    """
    if not ds.keeps_raw:
        raise FetchError(f"{ds.id}: an import needs adele.raw: keep (the answers are read by its parse())")
    if ds.revisions != "append-only":
        raise FetchError(f"{ds.id}: an import needs revisions: append-only (each answer becomes a version)")
    folder = Path(folder).resolve()
    res = Imported()
    with dataset_lock(cfg.data_dir, ds.id):
        st = state.load(cfg.data_dir, ds.id)
        if st.get("last_scheduled_at"):
            raise FetchError(f"{ds.id}: scheduled runs have started (last_scheduled_at {st['last_scheduled_at']}): "
                             "an import comes before the first one")
        newest = _newest_version(cfg, ds)
        done = dt.datetime.fromisoformat(st["imported"][1]) if st.get("imported") else None
        if newest is not None and (done is None or newest > done):
            raise FetchError(f"{ds.id}: the dataset holds versions that adele fetched (the newest at "
                             f"{newest:%Y-%m-%d %H:%M:%S} UTC): an import goes into a dataset without stored "
                             "rows, or goes on with an import that stopped")
        answers = raw.find_answers(folder)
        res.answers = len(answers)
        todo = [a for a in answers if newest is None or a.received_at >= newest]
        res.skipped = len(answers) - len(todo)
        groups: list[list[raw.Answer]] = []
        for a in todo:
            if groups and groups[-1][0].received_at == a.received_at:
                groups[-1].append(a)
            else:
                groups.append([a])
        windows = [(g[0].received_at - ds.refresh.every - ds.refresh.lookback, g[0].received_at + ds.refresh.horizon)
                   for g in groups]
        if groups:
            con = storage.connect()
            workdir = tempfile.TemporaryDirectory(prefix=f"adele-import-{ds.id}-")
            try:
                for t in ds.tables.values():
                    storage.check_layout(cfg.data_dir, t)
                    storage.check_columns(con, cfg.data_dir, t)
                fixed = runner_dir(cfg, ds) if ds.script_metadata is not None else None
                parsed, errors = call_parse(ds, groups, cfg.fetch_timeout_s, Path(workdir.name), fixed)
                files = _as_tables(ds, parsed) if parsed else {name: [] for name in ds.tables}
                by_group = {name: {int(p.name.split(".")[1]): p for p in paths} for name, paths in files.items()}
                arch, last = raw.archive_dir(cfg.data_dir, ds.id), {}
                for i, g in enumerate(groups):
                    if stopped():
                        raise Interrupted(f"interrupted by {stopped()} after {res.groups} of {len(groups)} groups")
                    at = g[0].received_at
                    for a in g:
                        res.kept += raw.keep(arch, a.name, a.url, raw.read_body(a), at, last)
                    missing = [t.name for t in ds.tables.values() if i not in by_group[t.name]]
                    error = errors.get(i) or (f"parse returned no table {missing}" if missing else None)
                    if error is None:
                        try:
                            n = sum(_stage(con, t, [by_group[t.name][i]], windows) for t in ds.tables.values())
                        except FetchError as e:  # the schema check of the parsed rows
                            error = str(e)
                    if error is not None:
                        res.failed.append((at, [a.path for a in g], error))
                        log.warning("import %s: answers received at %s not merged: %s", ds.id, at.isoformat(), error)
                        continue
                    st = state.load(cfg.data_dir, ds.id)  # written before the merge: a hard stop leaves it right
                    st.setdefault("versions_since", at)
                    st["imported"] = [(st.get("imported") or [at.isoformat()])[0], at.isoformat()]
                    state.save(cfg.data_dir, ds.id, st)
                    for t in ds.tables.values():
                        m = storage.merge_versions(con, cfg.data_dir, t, f"_batch_{t.name}",
                                                   fetched_at=at, resume=newest is not None and at == newest)
                        res.rows_changed += m.rows_changed
                    res.rows += n
                    res.groups += 1
                    res.first = res.first or at
                    res.last = at
            finally:
                con.close()
                workdir.cleanup()
        res.problems = _recheck(cfg, catalog, ds)
    return res


def _newest_version(cfg: Config, ds: Dataset) -> dt.datetime | None:
    """The latest fetched_at of the stored versions of an append-only dataset, or None."""
    newest = None
    con = storage.connect()
    try:
        for t in ds.tables.values():
            if storage.partitions(cfg.data_dir, t):
                v = con.execute(f"SELECT max({ident(VERSION_FIELD)}) FROM ({storage.versions_sql(cfg.data_dir, t)})"
                                ).fetchone()[0]
                if v is not None and (newest is None or v > newest):
                    newest = v
    finally:
        con.close()
    return newest
