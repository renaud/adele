"""Ingestion: call a dataset's fetch(start, end), check the result, merge it, run the checks.

Nothing happens silently: a fetch that fails, a result whose columns or types differ from the
descriptor, a null or duplicated key, all set the status to failing and keep the stored data.
"""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
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
    months_written: int = 0
    problems: list[str] | None = None
    error: str | None = None


def _fetch_in_child(folder: str, ds_id: str, start: dt.datetime, end: dt.datetime):
    from .catalog import _load_fetch

    return _load_fetch(ds_id, Path(folder) / "fetch.py")(start, end)


def call_fetch(ds: Dataset, start: dt.datetime, end: dt.datetime, timeout_s: float, workdir: Path | None = None):
    """Run fetch(start, end) in a child process, and stop it at the time limit.

    A hung source (e.g. an HTTP request without a timeout) would otherwise hold the dataset's
    lock forever: every scheduled run would skip, and the data would go stale silently. A
    thread can't be stopped, a process can. The child inherits the environment (credentials).

    A fetch.py with inline script metadata (PEP 723) runs in its own environment, built by
    `uv run --script` from the dependencies it declares; it returns Parquet paths in `workdir`.
    """
    if ds.script_metadata is not None:
        if workdir is None:
            raise ValueError("a fetch.py with inline dependencies needs a workdir")
        return _run_script(ds, start, end, timeout_s, workdir)
    with multiprocessing.get_context("spawn").Pool(1) as pool:
        res = pool.apply_async(_fetch_in_child, (str(ds.folder), ds.id, start, end))
        try:
            return res.get(timeout=timeout_s)
        except multiprocessing.TimeoutError:
            raise FetchError(f"fetch did not finish within {timeout_s:g} s (time limit); stopped") from None


# The runner calls fetch(start, end) and writes each table with DuckDB, which keeps the types
# (timezone-aware timestamps, durations as INTERVAL) without pyarrow on either side.
_RUNNER_BODY = """
import datetime as dt
import importlib.util
import sys

import duckdb

spec = importlib.util.spec_from_file_location("adele_fetch", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
start, end = (dt.datetime.fromisoformat(a) for a in sys.argv[2:4])
result = module.fetch(start, end)
tables = result if isinstance(result, dict) else {"_": result}
con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
for name, frame in tables.items():
    con.register("frame", frame)
    con.execute(f"COPY frame TO '{sys.argv[4]}/{name}.parquet' (FORMAT parquet)")
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


def _run_script(ds: Dataset, start: dt.datetime, end: dt.datetime, timeout_s: float, workdir: Path):
    uv = shutil.which("uv")
    if uv is None:
        raise FetchError("uv not found on PATH: needed to run a fetch.py that declares its dependencies")
    runner = workdir / "_runner.py"
    runner.write_text(runner_source(ds.script_metadata))
    out = workdir / "out"
    out.mkdir()
    cmd = [uv, "run", "--quiet", "--no-project", "--script", str(runner),
           str(ds.folder / "fetch.py"), start.isoformat(), end.isoformat(), str(out)]
    log_path = workdir / "fetch.log"
    with open(log_path, "w") as log_fh:
        proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, start_new_session=True,
                                cwd=ds.folder)
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
    files = {p.stem: p for p in out.glob("*.parquet")}
    return files.get("_") or files


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
            result = call_fetch(ds, start, end, cfg.fetch_timeout_s, Path(workdir.name))
            batches = _as_tables(ds, result)
            for t in ds.tables.values():
                out.rows += _stage(con, t, batches[t.name], start, end, ds.window)
            for t in ds.tables.values():
                m = storage.merge_overwrite(con, cfg.data_dir, t, f"_batch_{t.name}", ds.window)
                out.rows_changed += m.rows_changed
                out.months_written += len(m.months_written)
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


def _as_tables(ds: Dataset, result) -> dict:
    if isinstance(result, dict):
        missing = set(ds.tables) - set(result)
        extra = set(result) - set(ds.tables)
        if missing or extra:
            raise FetchError(f"fetch returned tables {sorted(result)}, declared {sorted(ds.tables)}")
        return result
    if len(ds.tables) != 1:
        raise FetchError(f"fetch must return a dict of tables {sorted(ds.tables)}")
    if result is None:
        raise FetchError("fetch returned nothing")
    return {next(iter(ds.tables)): result}


def _stage(con: duckdb.DuckDBPyConnection, t: Table, frame, start: dt.datetime, end: dt.datetime,
           window: str = DELIVERY_FIELD) -> int:
    """Check one fetched table against its schema; keep the rows of [start, end) in a temp table.

    `frame` is a data frame, or the path of a Parquet file (from a fetch.py run by uv). The
    window [start, end) applies to the column `window` (adele.window).
    """
    raw = f"_raw_{t.name}"
    if isinstance(frame, Path):
        con.execute(f"CREATE OR REPLACE TEMP VIEW {raw} AS SELECT * FROM read_parquet({storage.sql_str(frame)})")
    else:
        con.register(raw, frame)
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
    con.execute(f"CREATE OR REPLACE TEMP TABLE {batch} AS SELECT {cols} FROM {raw} "
                f"WHERE {ident(window)} >= $s AND {ident(window)} < $e", {"s": start, "e": end})
    if isinstance(frame, Path):
        con.execute(f"DROP VIEW {raw}")
    else:
        con.unregister(raw)
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
