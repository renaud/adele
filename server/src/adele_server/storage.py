"""Storage: each table is Parquet, one file per month (UTC), written by DuckDB (D9).

The month is that of the dataset's window column: delivery_start, unless `adele.window` names
another column (e.g. init_time for forecasts). Layout: <data_dir>/<dataset>/<table>/<YYYY-MM>.parquet. A partition is written to a temp file
and renamed, so readers never see a half-written partition (SPEC.md, Storage).
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .catalog import DELIVERY_FIELD, Table

UTC = dt.timezone.utc


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


def month_bounds(month: str) -> tuple[dt.datetime, dt.datetime]:
    y, m = map(int, month.split("-"))
    start = dt.datetime(y, m, 1, tzinfo=UTC)
    end = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=UTC)
    return start, end


@dataclass
class MergeResult:
    months_written: list[str]
    rows_changed: int  # rows of the batch that were new, or differed from the stored row


def merge_overwrite(con: duckdb.DuckDBPyConnection, data_dir: Path, table: Table, batch: str,
                    window: str = DELIVERY_FIELD) -> MergeResult:
    """Merge the rows of the temp table `batch` into the month partitions; the batch wins on the key.

    Stored rows of the window that the batch doesn't contain are kept (a source that stops
    sending a row doesn't delete it).
    """
    cols = ", ".join(ident(c) for c in table.field_names)
    first = list(dict.fromkeys([window, DELIVERY_FIELD]))
    order = ", ".join(ident(c) for c in first + [k for k in table.primary_key if k not in first])
    pk = ", ".join(ident(k) for k in table.primary_key)
    months = [r[0] for r in con.execute(
        f"SELECT DISTINCT strftime({ident(window)}, '%Y-%m') AS m FROM {batch} ORDER BY m").fetchall()]
    out_dir = table_dir(data_dir, table)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, changed_total = [], 0
    for month in months:
        start, end = month_bounds(month)
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE _month AS SELECT {cols} FROM {batch} "
            f"WHERE {ident(window)} >= $s AND {ident(window)} < $e", {"s": start, "e": end})
        path = out_dir / f"{month}.parquet"
        if path.exists():
            old = f"(SELECT {cols} FROM read_parquet({sql_str(path)}))"
            changed = con.execute(f"SELECT count(*) FROM (SELECT * FROM _month EXCEPT SELECT * FROM {old})").fetchone()[0]
            if changed == 0:
                continue
            merged = f"SELECT o.* FROM {old} o ANTI JOIN _month n USING ({pk}) UNION ALL SELECT * FROM _month"
        else:
            changed = con.execute("SELECT count(*) FROM _month").fetchone()[0]
            merged = "SELECT * FROM _month"
        tmp = out_dir / f".{month}.parquet.tmp-{os.getpid()}"
        con.execute(f"COPY (SELECT * FROM ({merged}) ORDER BY {order}) TO {sql_str(tmp)} "
                    f"(FORMAT parquet, COMPRESSION zstd)")
        os.replace(tmp, path)
        written.append(month)
        changed_total += changed
    con.execute("DROP TABLE IF EXISTS _month")
    return MergeResult(written, changed_total)


@dataclass
class TableStats:
    rows: int
    first: dt.datetime | None  # first delivery interval present
    last: dt.datetime | None  # last delivery interval present
    duckdb_types: dict[str, str]
    files: int


def table_stats(con: duckdb.DuckDBPyConnection, data_dir: Path, table: Table) -> TableStats:
    src = select_sql(data_dir, table)
    types = {r[0]: r[1] for r in con.execute(f"DESCRIBE {src}").fetchall()}
    rows, first, last = con.execute(
        f"SELECT count(*), min({ident(DELIVERY_FIELD)}), max({ident(DELIVERY_FIELD)}) FROM ({src})").fetchone()
    return TableStats(rows, first, last, types, len(partitions(data_dir, table)))
