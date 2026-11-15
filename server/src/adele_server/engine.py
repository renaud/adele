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
from .storage import ident, select_sql, table_dir

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
    # The folders of the tables only: the data folder also holds logs/ and a state.json per dataset.
    # A folder that doesn't exist yet (a dataset that was never fetched) is accepted.
    folders = [str(table_dir(data_dir, t).resolve()) + "/" for ds in catalog.values() for t in ds.tables.values()]
    con.execute("SET allowed_directories = $d", {"d": folders})
    con.execute("SET enable_external_access = false")
    for ds in catalog.values():
        con.execute(f"CREATE SCHEMA {ident(ds.id)}")
        for t in ds.tables.values():
            con.execute(f"CREATE VIEW {ident(ds.id)}.{ident(t.name)} AS {select_sql(data_dir, t)}")
    con.execute("SET lock_configuration = true")
    return con


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


def tables_read(tree: dict, catalog: dict[str, Dataset]) -> list[str]:
    """Datasets whose tables the query names. Parsed by DuckDB, not by matching text."""
    found = set()
    for n in nodes(tree):
        if n.get("type") == "BASE_TABLE":
            ds = catalog.get(n.get("schema_name") or "")
            if ds and (n.get("table_name") or "") in ds.tables:
                found.add(ds.id)
    return sorted(found)


def read_statement(con: duckdb.DuckDBPyConnection, sql: str, catalog: dict[str, Dataset]) -> tuple[str, list[str]]:
    """The statement to run and the datasets that it names. QueryError unless `sql` is one statement that only reads."""
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
    return st.query, tables_read(read_only_tree(con, st.query), catalog)


def run(catalog: dict[str, Dataset], data_dir: Path, limits: QueryLimits, sql: str,
        max_rows: int | None = None) -> QueryResult:
    max_rows = limits.max_rows if max_rows is None else max_rows
    t0 = time.monotonic()
    con = connect(catalog, data_dir, limits)
    try:
        query, datasets = read_statement(con, sql, catalog)
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
