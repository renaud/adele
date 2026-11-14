"""Ingestion: call a dataset's fetch(start, end), check the result, merge it, run the checks.

Nothing happens silently: a fetch that fails, a result whose columns or types differ from the
descriptor, a null or duplicated key, all set the status to failing and keep the stored data.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import duckdb

from . import checks, state, storage
from .catalog import DELIVERY_FIELD, Dataset, Table, category_values
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
    problems: list[str] | None = None
    error: str | None = None


EPSILON = dt.timedelta(microseconds=1)  # DuckDB's timestamp resolution: (a, b) = [a + EPSILON, b)


def windows_to_fetch(data_dir: Path, ds: Dataset, start: dt.datetime, end: dt.datetime) -> list[tuple]:
    """The windows to pass to fetch() for [start, end).

    overwrite: the whole window. none: stored rows never change, so only the parts of [start,
    end) that hold no stored value of the window column: the gaps between the distinct stored
    values, each value excluded. A value counts as stored when every table has rows for it.
    A gap may hold no data at all (between two hourly runs); fetch() then returns no rows.
    """
    if ds.revisions != "none":
        return [(start, end)]
    stored = None
    con = storage.connect()
    try:
        for t in ds.tables.values():
            if not storage.partitions(data_dir, t):
                stored = set()
                break
            vals = {r[0] for r in con.execute(
                f"SELECT DISTINCT {ident(ds.window)} FROM ({storage.select_sql(data_dir, t)}) "
                f"WHERE {ident(ds.window)} >= $s AND {ident(ds.window)} < $e", {"s": start, "e": end}).fetchall()}
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


def call_fetch(ds: Dataset, windows: list[tuple], timeout_s: float, workdir: Path) -> dict[str, list[Path]]:
    """Run fetch(start, end) on each window in one child process, and stop it at the time limit.

    A hung source (e.g. an HTTP request without a timeout) would otherwise hold the dataset's
    lock forever: every scheduled run would skip, and the data would go stale silently. A
    thread can't be stopped, a process can. The child gets only the environment of fetch_env().

    A fetch.py with inline script metadata (PEP 723) runs in its own environment, built by
    `uv run --script` from the dependencies it declares; without it, in the server's Python.
    Either way, the child writes each table of each window as Parquet in `workdir/out`: returns
    {table: [paths]}, "_" for a fetch that returns one table.
    """
    out = workdir / "out"
    out.mkdir()
    runner = workdir / "_runner.py"
    args = [str(ds.folder / "fetch.py"), json.dumps([[s.isoformat(), e.isoformat()] for s, e in windows]), str(out)]
    if ds.script_metadata is not None:
        uv = shutil.which("uv")
        if uv is None:
            raise FetchError("uv not found on PATH: needed to run a fetch.py that declares its dependencies")
        runner.write_text(runner_source(ds.script_metadata))
        cmd = [uv, "run", "--quiet", "--no-project", "--script", str(runner), *args]
    else:
        runner.write_text(_RUNNER_BODY)
        cmd = [sys.executable, str(runner), *args]
    _run_child(ds, cmd, timeout_s, workdir)
    files: dict[str, list[Path]] = {}
    for p in sorted(out.glob("*.parquet")):
        files.setdefault(p.name.split(".")[0], []).append(p)
    return files


# The runner calls fetch(start, end) on each window and writes each table with DuckDB, which
# keeps the types (timezone-aware timestamps, durations as INTERVAL) without pyarrow.
_RUNNER_BODY = """
import datetime as dt
import importlib.util
import json
import sys

import duckdb

spec = importlib.util.spec_from_file_location("adele_fetch", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
windows = [tuple(dt.datetime.fromisoformat(x) for x in w) for w in json.loads(sys.argv[2])]
out = sys.argv[3]
con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
for i, (start, end) in enumerate(windows):
    result = module.fetch(start, end)
    if result is None:
        raise RuntimeError(f"fetch returned nothing for [{start}, {end})")
    tables = result if isinstance(result, dict) else {"_": result}
    for name, frame in tables.items():
        con.register("frame", frame)
        con.execute(f"COPY frame TO '{out}/{name}.{i}.parquet' (FORMAT parquet)")
        con.unregister("frame")
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


def _run_child(ds: Dataset, cmd: list[str], timeout_s: float, workdir: Path) -> None:
    log_path = workdir / "fetch.log"
    with open(log_path, "w") as log_fh:
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True,
                                cwd=ds.folder, env=fetch_env(ds))
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)  # uv and the python it started
            proc.wait()
            raise FetchError(f"fetch did not finish within {timeout_s:g} s (time limit); stopped") from None
    text = log_path.read_text(errors="replace")
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


def scheduled_window(ds: Dataset, now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    return now - ds.refresh.lookback, now + ds.refresh.horizon


def is_due(ds: Dataset, s: dict, now: dt.datetime) -> bool:
    last = s.get("last_attempt_at")
    return last is None or now >= last + ds.refresh.every


def fetch_window(cfg: Config, catalog: dict[str, Dataset], ds: Dataset, start: dt.datetime, end: dt.datetime,
                 run_checks: bool = True) -> Outcome:
    out = Outcome(ds.id, start, end, ok=False)
    with dataset_lock(cfg.data_dir, ds.id):
        st = state.load(cfg.data_dir, ds.id)
        old_status = st.get("status")
        st["last_attempt_at"] = state.now()
        st["last_window"] = [start.isoformat(), end.isoformat()]
        con = storage.connect()
        workdir = tempfile.TemporaryDirectory(prefix=f"adele-{ds.id}-")
        try:
            for t in ds.tables.values():
                storage.check_layout(cfg.data_dir, t, ds.partition)
            windows = windows_to_fetch(cfg.data_dir, ds, start, end)
            out.windows_fetched = len(windows)
            if windows:
                batches = _as_tables(ds, call_fetch(ds, windows, cfg.fetch_timeout_s, Path(workdir.name)))
                for t in ds.tables.values():
                    out.rows += _stage(con, t, batches[t.name], windows, ds.window)
                merge = storage.merge_append if ds.revisions == "none" else storage.merge_overwrite
                for t in ds.tables.values():
                    m = merge(con, cfg.data_dir, t, f"_batch_{t.name}", ds.window, ds.partition)
                    out.rows_changed += m.rows_changed
                    out.partitions_written += len(m.partitions_written)
            st["last_fetched_at"] = st["last_attempt_at"]
            if out.rows_changed:
                st["last_changed_at"] = st["last_attempt_at"]
            st.pop("last_error", None)
            out.ok = True
        except Exception as e:  # noqa: BLE001 - any failure of a fetch must set the status
            out.error = f"{type(e).__name__}: {e}"
            st["last_error"] = out.error
            log.exception("fetch of %s failed", ds.id)
        finally:
            con.close()
            workdir.cleanup()
        if run_checks:
            problems = checks.run_checks(catalog, ds, cfg.data_dir, cfg.query)
            st["published_checks"] = {"count": len(ds.checks), "at": state.now().isoformat()}
        else:
            problems = st.get("problems", [])
        if out.error:
            problems = [f"last fetch failed: {out.error}"] + list(problems)
        out.problems = problems
        st["problems"] = problems
        st["status"] = "failing" if problems else "ok"
        st["last_rows"] = {"fetched": out.rows, "changed": out.rows_changed}
        state.save(cfg.data_dir, ds.id, st)
        if run_checks:
            alert_on_change(cfg, ds.id, old_status, st["status"], problems)
    return out


def recheck(cfg: Config, catalog: dict[str, Dataset], ds: Dataset) -> list[str]:
    """Run the checks on the stored data and update the status (after a backfill)."""
    with dataset_lock(cfg.data_dir, ds.id):
        st = state.load(cfg.data_dir, ds.id)
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
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    line = f"{state.now().isoformat()} {ds_id}: {old} --> {new}"
    if problems:
        line += " | " + " | ".join(problems)
    with open(cfg.log_dir / "alerts.log", "a") as fh:
        fh.write(line + "\n")
    log.warning("ALERT %s", line)


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


def _stage(con: duckdb.DuckDBPyConnection, t: Table, files: list[Path], windows: list[tuple],
           window: str = DELIVERY_FIELD) -> int:
    """Check one fetched table against its schema; keep the rows of its windows in a temp table.

    `files`: the Parquet files that the child wrote for this table, `<table>.<i>.parquet` for
    windows[i]. Each file keeps only the rows of its own window [start, end), on the column
    `window` (adele.window): a source may ignore the window, the server filters.
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
            hint = " (timestamps must be timezone-aware)" if got[name] == "TIMESTAMP" else ""
            errors.append(f"{name}: got {got[name]}, declared {ftype}{hint}")
    if errors:
        raise FetchError(f"{t.sql_name}: schema check failed: " + "; ".join(errors))
    types = t.storage_types()
    cols = ", ".join(f"CAST({ident(c)} AS {types[c]}) AS {ident(c)}" for c in t.field_names)
    batch = f"_batch_{t.name}"
    parts = []
    for f in files:
        s, e = windows[int(f.name.split(".")[1])]
        parts.append(f"SELECT * FROM read_parquet({storage.sql_str(f)}) WHERE {ident(window)} >= "
                     f"'{s.isoformat()}'::TIMESTAMPTZ AND {ident(window)} < '{e.isoformat()}'::TIMESTAMPTZ")
    con.execute(f"CREATE OR REPLACE TEMP TABLE {batch} AS SELECT {cols} FROM ("
                + " UNION ALL BY NAME ".join(parts) + ")")
    con.execute(f"DROP VIEW {raw}")
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
             step: dt.timedelta = dt.timedelta(days=365)) -> list[Outcome]:
    """Call fetch on successive windows, then run the checks once."""
    outcomes = []
    s = start
    while s < end:
        e = min(s + step, end)
        o = fetch_window(cfg, catalog, ds, s, e, run_checks=False)
        log.info("backfill %s [%s, %s): ok=%s rows=%s changed=%s %s", ds.id, s, e, o.ok, o.rows, o.rows_changed,
                 o.error or "")
        outcomes.append(o)
        s = e
    recheck(cfg, catalog, ds)
    return outcomes
