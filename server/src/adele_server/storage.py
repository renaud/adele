"""Storage: each table is Parquet, one file per month or per day (UTC), written by DuckDB (D9).

The month or day is that of the dataset's window column: delivery_start, unless `adele.window`
names another column (e.g. init_time for forecasts). `adele.partition` picks month (default) or
day. Layout: <data_dir>/<dataset>/<table>/<YYYY-MM>.parquet or <YYYY-MM-DD>.parquet. A partition
is written to a temp file and renamed, so readers never see a half-written partition (SPEC.md,
Storage).
"""
from __future__ import annotations

import datetime as dt
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .catalog import DELIVERY_FIELD, Table

UTC = dt.timezone.utc
PARTITION_FORMAT = {"month": "%Y-%m", "day": "%Y-%m-%d"}
PARTITION_FILE = {"month": re.compile(r"^\d{4}-\d{2}\.parquet$"), "day": re.compile(r"^\d{4}-\d{2}-\d{2}\.parquet$")}


class StorageError(Exception):
    pass


def connect() -> duckdb.DuckDBPyConnection:
    """A plain connection for the server's own work (ingestion, checks, stats). Never for agent SQL."""
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone = 'UTC'")
    return con


def table_dir(data_dir: Path, table: Table) -> Path:
    return data_dir / table.dataset_id / table.name


def partitions(data_dir: Path, table: Table) -> list[Path]:
    d = table_dir(data_dir, table)
    return sorted(d.glob("*.parquet")) if d.is_dir() else []


def sql_str(s: str | os.PathLike) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def select_sql(data_dir: Path, table: Table) -> str:
    """SELECT over the stored table, declared columns in declared order. Empty but typed if no data yet."""
    cols = table.storage_types()
    if partitions(data_dir, table):
        glob = table_dir(data_dir, table) / "*.parquet"
        return f"SELECT {', '.join(ident(c) for c in cols)} FROM read_parquet({sql_str(glob)})"
    return "SELECT " + ", ".join(f"NULL::{t} AS {ident(c)}" for c, t in cols.items()) + " WHERE false"


def partition_bounds(key: str) -> tuple[dt.datetime, dt.datetime]:
    """[start, end) of a partition: 'YYYY-MM' (a month) or 'YYYY-MM-DD' (a day), UTC."""
    parts = list(map(int, key.split("-")))
    if len(parts) == 3:
        start = dt.datetime(*parts, tzinfo=UTC)
        return start, start + dt.timedelta(days=1)
    y, m = parts
    return dt.datetime(y, m, 1, tzinfo=UTC), dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=UTC)


month_bounds = partition_bounds  # older name


def check_layout(data_dir: Path, table: Table, partition: str) -> None:
    """Raise if files of another partition size sit in the table's folder (they would be read twice)."""
    bad = [p.name for p in partitions(data_dir, table) if not PARTITION_FILE[partition].match(p.name)]
    if bad:
        raise StorageError(f"{table.sql_name}: files {bad[:3]}{' ...' if len(bad) > 3 else ''} don't match "
                           f"adele.partition {partition!r}: run `adele-server repartition {table.dataset_id}`")


def _order(table: Table, window: str) -> str:
    first = list(dict.fromkeys([window, table.time_field]))
    return ", ".join(ident(c) for c in first + [k for k in table.primary_key if k not in first])


def _keys(con, batch: str, window: str, partition: str) -> list[str]:
    fmt = PARTITION_FORMAT[partition]
    return [r[0] for r in con.execute(
        f"SELECT DISTINCT strftime({ident(window)}, '{fmt}') AS k FROM {batch} ORDER BY k").fetchall()]


def _write(con, out_dir: Path, key: str, select: str, order: str) -> None:
    tmp = out_dir / f".{key}.parquet.tmp-{os.getpid()}"
    con.execute(f"COPY (SELECT * FROM ({select}) ORDER BY {order}) TO {sql_str(tmp)} (FORMAT parquet, COMPRESSION zstd)")
    os.replace(tmp, out_dir / f"{key}.parquet")


@dataclass
class MergeResult:
    partitions_written: list[str]
    rows_changed: int  # rows of the batch that were new, or differed from the stored row


def merge_overwrite(con: duckdb.DuckDBPyConnection, data_dir: Path, table: Table, batch: str,
                    window: str = DELIVERY_FIELD, partition: str = "month") -> MergeResult:
    """Merge the rows of the temp table `batch` into the partitions; the batch wins on the key.

    Stored rows of the window that the batch doesn't contain are kept (a source that stops
    sending a row doesn't delete it).
    """
    cols = ", ".join(ident(c) for c in table.field_names)
    order = _order(table, window)
    pk = ", ".join(ident(k) for k in table.primary_key)
    out_dir = table_dir(data_dir, table)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, changed_total = [], 0
    for key in _keys(con, batch, window, partition):
        start, end = partition_bounds(key)
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE _part AS SELECT {cols} FROM {batch} "
            f"WHERE {ident(window)} >= $s AND {ident(window)} < $e", {"s": start, "e": end})
        path = out_dir / f"{key}.parquet"
        if path.exists():
            old = f"(SELECT {cols} FROM read_parquet({sql_str(path)}))"
            changed = con.execute(f"SELECT count(*) FROM (SELECT * FROM _part EXCEPT SELECT * FROM {old})").fetchone()[0]
            if changed == 0:
                continue
            merged = f"SELECT o.* FROM {old} o ANTI JOIN _part n USING ({pk}) UNION ALL SELECT * FROM _part"
        else:
            changed = con.execute("SELECT count(*) FROM _part").fetchone()[0]
            merged = "SELECT * FROM _part"
        _write(con, out_dir, key, merged, order)
        written.append(key)
        changed_total += changed
    con.execute("DROP TABLE IF EXISTS _part")
    return MergeResult(written, changed_total)


def merge_append(con: duckdb.DuckDBPyConnection, data_dir: Path, table: Table, batch: str,
                 window: str = DELIVERY_FIELD, partition: str = "month") -> MergeResult:
    """`revisions: none`: add the rows of `batch` whose key isn't stored; stored rows never change.

    A batch row whose key is stored with other values means that the source revised data that
    it declared final: StorageError, and nothing is written (checked on every partition first).
    """
    cols = ", ".join(ident(c) for c in table.field_names)
    order = _order(table, window)
    pk = ", ".join(ident(k) for k in table.primary_key)
    differs = " OR ".join(f"n.{ident(c)} IS DISTINCT FROM o.{ident(c)}"
                          for c in table.field_names if c not in table.primary_key) or "false"
    out_dir = table_dir(data_dir, table)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = []
    for key in _keys(con, batch, window, partition):
        start, end = partition_bounds(key)
        part = f"_part_{len(plan)}"
        con.execute(f"CREATE OR REPLACE TEMP TABLE {part} AS SELECT {cols} FROM {batch} "
                    f"WHERE {ident(window)} >= $s AND {ident(window)} < $e", {"s": start, "e": end})
        path = out_dir / f"{key}.parquet"
        old = f"(SELECT {cols} FROM read_parquet({sql_str(path)}))" if path.exists() else None
        if old:
            bad = con.execute(f"SELECT {', '.join('n.' + ident(k) for k in table.primary_key)} FROM {part} n "
                              f"JOIN {old} o USING ({pk}) WHERE {differs} LIMIT 3").fetchall()
            if bad:
                for i in range(len(plan) + 1):
                    con.execute(f"DROP TABLE IF EXISTS _part_{i}")
                raise StorageError(f"{table.sql_name}: the source changed stored rows (revisions: none), "
                                   f"e.g. keys ({pk}) = {bad}")
            new = con.execute(f"SELECT count(*) FROM (SELECT * FROM {part} ANTI JOIN {old} USING ({pk}))").fetchone()[0]
        else:
            new = con.execute(f"SELECT count(*) FROM {part}").fetchone()[0]
        plan.append((key, part, old, new))
    written, added = [], 0
    for key, part, old, new in plan:
        if new:
            merged = (f"SELECT * FROM {old} UNION ALL SELECT * FROM (SELECT * FROM {part} ANTI JOIN {old} USING ({pk}))"
                      if old else f"SELECT * FROM {part}")
            _write(con, out_dir, key, merged, order)
            written.append(key)
            added += new
        con.execute(f"DROP TABLE IF EXISTS {part}")
    return MergeResult(written, added)


def repartition(con: duckdb.DuckDBPyConnection, data_dir: Path, table: Table, window: str, partition: str) -> int:
    """Rewrite a table's files with another partition size; returns the number of files written.

    The new files are written to a sibling folder, which then replaces the table's folder (two
    renames: a query in between may see an empty table, never duplicated rows).
    """
    src = table_dir(data_dir, table)
    files = partitions(data_dir, table)
    if not files:
        return 0
    new_dir = src.with_name(src.name + ".repartition")
    old_dir = src.with_name(src.name + ".old")
    for d in (new_dir, old_dir):
        if d.exists():
            shutil.rmtree(d)
    new_dir.mkdir()
    cols = ", ".join(ident(c) for c in table.field_names)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _all AS SELECT {cols} FROM read_parquet({sql_str(src / '*.parquet')})")
    before = con.execute("SELECT count(*) FROM _all").fetchone()[0]
    order = _order(table, window)
    keys = _keys(con, "_all", window, partition)
    for key in keys:
        start, end = partition_bounds(key)
        _write(con, new_dir, key, f"SELECT * FROM _all WHERE {ident(window)} >= '{start.isoformat()}'::TIMESTAMPTZ "
                                  f"AND {ident(window)} < '{end.isoformat()}'::TIMESTAMPTZ", order)
    con.execute("DROP TABLE _all")
    after = con.execute(f"SELECT count(*) FROM read_parquet({sql_str(new_dir / '*.parquet')})").fetchone()[0]
    if after != before:
        shutil.rmtree(new_dir)
        raise StorageError(f"{table.sql_name}: repartition wrote {after} rows, read {before}; nothing changed")
    os.rename(src, old_dir)
    os.rename(new_dir, src)
    shutil.rmtree(old_dir)
    return len(keys)


@dataclass
class TableStats:
    rows: int
    first: dt.datetime | None  # first value of the time field: interval start, or instant (valid_at)
    last: dt.datetime | None
    duckdb_types: dict[str, str]
    files: int


def table_stats(con: duckdb.DuckDBPyConnection, data_dir: Path, table: Table) -> TableStats:
    src = select_sql(data_dir, table)
    types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {src}").fetchall()}
    rows, first, last = con.execute(
        f"SELECT count(*), min({ident(table.time_field)}), max({ident(table.time_field)}) FROM ({src})").fetchone()
    return TableStats(rows, first, last, types, len(partitions(data_dir, table)))
