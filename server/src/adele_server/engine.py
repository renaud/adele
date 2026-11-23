"""The query engine for SQL written by agents (SPEC.md, Security).

Each query gets a fresh in-memory DuckDB connection:

- reads: `enable_external_access = false` with `allowed_directories` = one folder per table of
  the catalog (`<data_dir>/<dataset>/<table>/`). Not the data folder: it also holds the query
  log and the state files. Reads outside these folders fail, including `..` and symlinks
  (tested with duckdb 2.0.0). DuckDB adds its `temp_directory` (`.tmp` in the working
  directory) to the list by itself.
- writes: DuckDB can still write inside an allowed folder (`COPY ... TO`, `EXPORT DATABASE`,
  `ATTACH` all create files there), and no setting makes a folder read-only. So `run` lets
  through only what DuckDB's own parser shows to be a read (allow-lists, tested with duckdb
  2.0.0):
  - one statement, of type SELECT (`extract_statements`). Nothing else, also no EXPLAIN:
    EXPLAIN ANALYZE runs the statement that follows it, a COPY included, and DuckDB gives no
    parse tree for an EXPLAIN.
  - SELECT: the parse tree (`json_serialize_sql`) holds only query nodes that read
    (`READ_NODES`). A CTE body can be a COPY, INSERT, UPDATE or DELETE: refused at any depth.
    A SELECT that DuckDB can't serialize is refused.
  - table functions: only those of `TABLE_FUNCTIONS`. Some of the others run SQL that they get
    as data, which the tree doesn't show: `query`, `json_execute_serialized_sql`,
    `destroy_external_resource`. Scalar functions are not on a list.
  On the Linux server, the query process also runs as a user that can only read the data
  folder: the layer that doesn't depend on parsing.
- settings: `lock_configuration = true` after the setup, so a query can't change them.
- limits: rows returned (`max_rows`), memory (`memory_limit`), temporary files (`temp_limit`),
  time (a timer calls `interrupt()`; DuckDB has no time limit of its own). How many queries run
  at once is limited in `app.py`.
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

from . import state
from .catalog import VERSIONS_SUFFIX, Dataset, Table
from .config import QueryLimits
from .storage import ident, select_sql, sql_str, table_dir, versions_sql

# Query nodes that read, as json_serialize_sql names them. The others write: COPY_QUERY_NODE,
# INSERT_QUERY_NODE, UPDATE_QUERY_NODE, DELETE_QUERY_NODE.
READ_NODES = {"SELECT_NODE", "SET_OPERATION_NODE", "RECURSIVE_CTE_NODE"}
# Table functions that a query may call. A table function can run a statement that the parse tree
# doesn't show, so a name that is not listed is refused (also one that a later DuckDB adds).
TABLE_FUNCTIONS = {
    "range", "generate_series", "unnest", "json_each", "json_tree", "pg_timezone_names", "icu_calendar_names",
    # the catalog
    "duckdb_tables", "duckdb_views", "duckdb_columns", "duckdb_schemas", "duckdb_databases", "duckdb_functions",
    "duckdb_types", "duckdb_settings", "duckdb_keywords", "pragma_table_info", "pragma_version",
    # files: the engine settings keep them inside the folders of the tables
    "read_parquet", "parquet_scan", "parquet_schema", "parquet_metadata", "parquet_file_metadata",
    "parquet_kv_metadata", "glob", "read_csv", "read_csv_auto", "read_json", "read_json_auto", "read_ndjson",
    "read_ndjson_auto", "read_json_objects", "read_json_objects_auto", "read_ndjson_objects", "read_text",
    "read_blob", "sniff_csv",
}


class QueryError(Exception):
    pass


class Busy(QueryError):
    """Too many queries run at once, and none ended in time (app.py)."""


@dataclass
class QueryResult:
    columns: list[str]
    types: list[str]
    rows: list[list]
    total: int | None  # rows before the cap; None if counting them hit the time limit
    truncated: bool
    datasets: list[str] = field(default_factory=list)  # datasets that the query read
    elapsed_ms: int = 0
    versions: list[str] = field(default_factory=list)  # datasets whose view of every version the query read
    as_of: dt.datetime | None = None


def parse_as_of(text: str) -> dt.datetime:
    """`as_of` as a client sends it: an ISO 8601 date or timestamp; without an offset, UTC."""
    try:
        v = dt.datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise QueryError(f"as_of must be an ISO 8601 timestamp such as 2026-11-15T12:00Z, got {text!r}") from None
    return v.replace(tzinfo=dt.timezone.utc) if v.tzinfo is None else v.astimezone(dt.timezone.utc)


def connect(catalog: dict[str, Dataset], data_dir: Path, limits: QueryLimits,
            as_of: dt.datetime | None = None) -> duckdb.DuckDBPyConnection:
    """A connection for one query. Each table is the view `<dataset>.<table>`; an append-only table
    also has `<dataset>.<table>_versions` (D30). With `as_of`, both views of an append-only table
    show only the versions fetched at or before it."""
    con = duckdb.connect(":memory:", config={
        "threads": limits.threads,
        "memory_limit": limits.memory_limit,
        "autoinstall_known_extensions": False,
        "autoload_known_extensions": False,
    })
    con.execute("SET TimeZone = 'UTC'")
    if limits.temp_limit is not None:
        # SET, not the config of connect(): duckdb 2.0.0 shows the value given there as the current
        # setting and doesn't apply it (tested in test_access.py).
        con.execute("SET max_temp_directory_size = $s", {"s": limits.temp_limit})
    # The folders of the tables only: the data folder also holds logs/ and a state.json per dataset.
    # A folder that doesn't exist yet (a dataset that was never fetched) is accepted.
    folders = [str(table_dir(data_dir, t).resolve()) + "/" for ds in catalog.values() for t in ds.tables.values()]
    con.execute("SET allowed_directories = $d", {"d": folders})
    con.execute("SET enable_external_access = false")
    for ds in catalog.values():
        con.execute(f"CREATE SCHEMA {ident(ds.id)}")
        for t in ds.tables.values():
            _create_view(con, ds.id, t.name, select_sql(data_dir, t, as_of), t.storage_types())
            if t.versioned:
                _create_view(con, ds.id, t.name + VERSIONS_SUFFIX, versions_sql(data_dir, t, as_of), t.stored_types())
    con.execute("SET lock_configuration = true")
    return con


def _create_view(con: duckdb.DuckDBPyConnection, ds_id: str, name: str, body: str, cols: dict[str, str]) -> None:
    """A view that can't be created (stored files that don't match the descriptor) becomes one with
    the same columns that fails when a query reads it: the views of the other datasets still answer."""
    view = f"{ident(ds_id)}.{ident(name)}"
    try:
        con.execute(f"CREATE VIEW {view} AS {body}")
    except duckdb.Error as e:
        msg = (f"{ds_id}.{name} can't be read: the stored files don't match its descriptor "
               f"({str(e).splitlines()[0]}). See the status in `adele describe {ds_id}`")
        nulls = ", ".join(f"NULL::{tp} AS {ident(c)}" for c, tp in cols.items())
        con.execute(f"CREATE VIEW {view} AS SELECT {nulls} FROM range(1) WHERE error({sql_str(msg)})")


def nodes(tree):
    """Every object of a parse tree, at any depth."""
    todo = [tree]
    while todo:
        n = todo.pop()
        if isinstance(n, dict):
            yield n
            todo.extend(n.values())
        elif isinstance(n, list):
            todo.extend(n)


def read_only_tree(con: duckdb.DuckDBPyConnection, sql: str) -> dict:
    """The parse tree of one SELECT, as DuckDB's parser serializes it. QueryError if it can write.

    Not by matching text: every query node must be one that reads, and every table function one
    of TABLE_FUNCTIONS. A statement that DuckDB can't serialize is refused.
    """
    try:
        tree = json.loads(con.execute("SELECT json_serialize_sql($q)", {"q": sql}).fetchone()[0])
    except (duckdb.Error, ValueError, RecursionError):
        tree = {"error": True}
    if tree.get("error") or len(tree.get("statements") or []) != 1:
        raise QueryError("this statement can't be checked as read-only: DuckDB can't serialize it. "
                         "Write it as one plain SELECT.")
    for n in nodes(tree):
        kind = n.get("type")
        if ("cte_map" in n or str(kind).endswith("_NODE")) and kind not in READ_NODES:
            raise QueryError(f"queries are read-only: {str(kind).removesuffix('_QUERY_NODE')} is not allowed, "
                             "also inside WITH. Only SELECT.")
        if kind == "TABLE_FUNCTION":
            name = str((n.get("function") or {}).get("function_name") or "?").lower()
            if name not in TABLE_FUNCTIONS:
                raise QueryError(f"the table function {name}() is not allowed in queries")
    return tree


def versions_of(ds: Dataset, name: str) -> Table | None:
    """The append-only table whose view of every version is `name`, else None."""
    base = name.removesuffix(VERSIONS_SUFFIX)
    t = ds.tables.get(base) if base != name else None
    return t if t is not None and t.versioned else None


def views_read(tree: dict, catalog: dict[str, Dataset]) -> set[tuple[str, str]]:
    """(dataset, view) for each view of the catalog that the query names: a table, or the view of
    every version of an append-only table. Parsed by DuckDB, not by matching text."""
    found = set()
    for n in nodes(tree):
        if n.get("type") == "BASE_TABLE":
            ds = catalog.get(n.get("schema_name") or "")
            name = n.get("table_name") or ""
            if ds and (name in ds.tables or versions_of(ds, name)):
                found.add((ds.id, name))
    return found


def tables_read(tree: dict, catalog: dict[str, Dataset]) -> list[str]:
    """Datasets whose tables the query names."""
    return sorted({d for d, _ in views_read(tree, catalog)})


def check_as_of(catalog: dict[str, Dataset], data_dir: Path, datasets: list[str], as_of: dt.datetime) -> None:
    """QueryError unless every dataset that the query reads keeps versions since `as_of` or earlier (D30)."""
    if not datasets:
        raise QueryError("as_of applies to the tables of append-only datasets, and this query reads none of them")
    plain = [d for d in datasets if catalog[d].revisions != "append-only"]
    if plain:
        one = len(plain) == 1
        raise QueryError(f"as_of applies only to append-only datasets; {', '.join(plain)} keep{'s' if one else ''} only "
                         f"the latest value of each row. Query {'it' if one else 'them'} separately, without as_of")
    for d in datasets:
        since = state.load(data_dir, d).get("versions_since")
        if since is None:
            raise QueryError(f"{d} has no versions yet (no scheduled run so far): as_of can't answer")
        if as_of < since:
            raise QueryError(f"{d} keeps versions since {since:%Y-%m-%d %H:%M:%S}Z. Its rows fetched before that "
                             f"were backfilled: their fetched_at is the time of the backfill, not of the "
                             f"publication. Use an as_of at or after that time")


def read_statement(con: duckdb.DuckDBPyConnection, sql: str,
                   catalog: dict[str, Dataset]) -> tuple[str, set[tuple[str, str]]]:
    """The statement to run and the views that it names (views_read). QueryError unless `sql` is
    one statement that only reads."""
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error as e:
        raise QueryError(str(e)) from None
    if len(statements) != 1:
        raise QueryError(f"send exactly one SQL statement (got {len(statements)})")
    st = statements[0]
    if st.type != duckdb.StatementType.SELECT:
        hint = " For PIVOT, use conditional aggregation, e.g. avg(x) FILTER (WHERE zone = 'CH')." \
            if st.type == duckdb.StatementType.MULTI else ""
        raise QueryError(f"only SELECT statements are allowed (got {st.type.name}).{hint}")
    return st.query, views_read(read_only_tree(con, st.query), catalog)


def run(catalog: dict[str, Dataset], data_dir: Path, limits: QueryLimits, sql: str,
        max_rows: int | None = None, as_of: dt.datetime | None = None) -> QueryResult:
    max_rows = limits.max_rows if max_rows is None else max_rows
    t0 = time.monotonic()
    con = connect(catalog, data_dir, limits, as_of)
    try:
        query, views = read_statement(con, sql, catalog)
        datasets = sorted({d for d, _ in views})
        versions = sorted({d for d, name in views if name not in catalog[d].tables})
        if as_of is not None:
            check_as_of(catalog, data_dir, datasets, as_of)
        timer = threading.Timer(limits.timeout_s, con.interrupt)
        timer.start()
        try:
            con.execute(query)
            columns = [d[0] for d in con.description]
            types = [str(d[1]) for d in con.description]
            rows = con.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            total: int | None = len(rows)
            if truncated:
                try:
                    total = con.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
                except duckdb.InterruptException:
                    total = None
        except duckdb.InterruptException:
            raise QueryError(f"query stopped after {limits.timeout_s:g} s (time limit). "
                             "Aggregate, or narrow the filter.") from None
        except duckdb.OutOfMemoryException:
            temp = f" and {limits.temp_limit} of temporary files" if limits.temp_limit else ""
            raise QueryError(f"query stopped: memory limit ({limits.memory_limit}{temp}). "
                             "Aggregate, or narrow the filter.") from None
        except duckdb.Error as e:
            raise QueryError(str(e)) from None
        finally:
            timer.cancel()
        return QueryResult(columns, types, [[to_json(v) for v in r] for r in rows], total, truncated,
                           datasets, int((time.monotonic() - t0) * 1000), versions, as_of)
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
