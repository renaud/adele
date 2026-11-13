"""The query engine for SQL written by agents (SPEC.md, Security).

Each query gets a fresh in-memory DuckDB connection:

- reads: `enable_external_access = false` with `allowed_directories = [data_dir]`. Reads
  outside the data folder fail, including `..` and symlinks (tested with duckdb 2.0.0).
- writes: DuckDB can still write inside an allowed folder (`COPY ... TO`, `EXPORT DATABASE`,
  `ATTACH` all create files there). So only SELECT and EXPLAIN statements run, as classified by
  DuckDB's own parser. On the Linux server, the query process also runs as a user that can only
  read the data folder.
- settings: `lock_configuration = true` after the setup, so a query can't change them.
- limits: rows returned (`max_rows`), memory (`memory_limit`), time (a timer calls
  `interrupt()`; DuckDB has no time limit of its own).
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .catalog import Dataset
from .config import QueryLimits
from .storage import ident, select_sql

ALLOWED_STATEMENTS = {duckdb.StatementType.SELECT, duckdb.StatementType.EXPLAIN}


class QueryError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    types: list[str]
    rows: list[list]
    total: int | None  # rows before the cap; None if counting them hit the time limit
    truncated: bool
    datasets: list[str] = field(default_factory=list)  # datasets that the query read
    elapsed_ms: int = 0


def connect(catalog: dict[str, Dataset], data_dir: Path, limits: QueryLimits) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:", config={
        "threads": limits.threads,
        "memory_limit": limits.memory_limit,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    })
    con.execute("SET TimeZone = 'UTC'")
    con.execute("SET allowed_directories = $d", {"d": [str(data_dir.resolve()) + "/"]})
    con.execute("SET enable_external_access = false")
    for ds in catalog.values():
        con.execute(f"CREATE SCHEMA {ident(ds.id)}")
        for t in ds.tables.values():
            con.execute(f"CREATE VIEW {ident(ds.id)}.{ident(t.name)} AS {select_sql(data_dir, t)}")
    con.execute("SET lock_configuration = true")
    return con


def tables_read(con: duckdb.DuckDBPyConnection, sql: str, catalog: dict[str, Dataset]) -> list[str]:
    """Datasets whose tables the query names. Parsed by DuckDB, not by matching text."""
    try:
        tree = json.loads(con.execute("SELECT json_serialize_sql($q)", {"q": sql}).fetchone()[0])
    except Exception:  # noqa: BLE001 - EXPLAIN and some statements can't be serialized
        return []
    found = set()

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "BASE_TABLE":
                schema, table = n.get("schema_name") or "", n.get("table_name") or ""
                ds = catalog.get(schema)
                if ds and table in ds.tables:
                    found.add(ds.id)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(tree)
    return sorted(found)


def run(catalog: dict[str, Dataset], data_dir: Path, limits: QueryLimits, sql: str,
        max_rows: int | None = None) -> QueryResult:
    max_rows = limits.max_rows if max_rows is None else max_rows
    t0 = time.monotonic()
    con = connect(catalog, data_dir, limits)
    try:
        try:
            statements = con.extract_statements(sql)
        except duckdb.Error as e:
            raise QueryError(str(e)) from None
        if len(statements) != 1:
            raise QueryError(f"send exactly one SQL statement (got {len(statements)})")
        st = statements[0]
        if st.type not in ALLOWED_STATEMENTS:
            hint = " For PIVOT, use conditional aggregation, e.g. avg(x) FILTER (WHERE zone = 'CH')." \
                if st.type == duckdb.StatementType.MULTI else ""
            raise QueryError(f"only SELECT and EXPLAIN statements are allowed (got {st.type.name}).{hint}")
        datasets = tables_read(con, st.query, catalog)
        timer = threading.Timer(limits.timeout_s, con.interrupt)
        timer.start()
        try:
            con.execute(st.query)
            columns = [d[0] for d in con.description]
            types = [str(d[1]) for d in con.description]
            rows = con.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            total: int | None = len(rows)
            if truncated:
                try:
                    total = con.execute(f"SELECT count(*) FROM ({st.query})").fetchone()[0]
                except duckdb.InterruptException:
                    total = None
        except duckdb.InterruptException:
            raise QueryError(f"query stopped after {limits.timeout_s:g} s (time limit). "
                             "Aggregate, or narrow the filter.") from None
        except duckdb.OutOfMemoryException:
            raise QueryError(f"query stopped: memory limit ({limits.memory_limit}). "
                             "Aggregate, or narrow the filter.") from None
        except duckdb.Error as e:
            raise QueryError(str(e)) from None
        finally:
            timer.cancel()
        return QueryResult(columns, types, [[to_json(v) for v in r] for r in rows], total, truncated,
                           datasets, int((time.monotonic() - t0) * 1000))
    finally:
        con.close()


def to_json(v):
    """A DuckDB value as a JSON value. Timestamps and intervals become text."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(dt.timezone.utc)
            return v.strftime("%Y-%m-%d %H:%M:%S") + "Z"
        return v.isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return iso_duration(v)
    if isinstance(v, (list, tuple)):
        return [to_json(x) for x in v]
    if isinstance(v, dict):
        return {str(k): to_json(x) for k, x in v.items()}
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, uuid.UUID):
        return str(v)
    return str(v)


def iso_duration(td: dt.timedelta) -> str:
    secs = int(td.total_seconds())
    if secs == 0:
        return "PT0S"
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    out = f"{sign}P{d}D" if d else f"{sign}P"
    if h or m or s:
        out += "T" + (f"{h}H" if h else "") + (f"{m}M" if m else "") + (f"{s}S" if s else "")
    return out
