"""WP3, design point 4: what versions cost, on synthetic data of the size of the largest planned
table (neighbours ws_forecast: 22.4 million rows, docs/datasets-inventory.md).

The same table in three layouts, one Parquet file per month as adele writes them:
- plain: no versions (revisions: overwrite), the reference.
- a: every version with fetched_at in one set of files; the latest view is a window function
  (QUALIFY row_number() ... = 1). Rejected in WP3 (D30), kept here as the reference.
- c: as a, plus superseded_at (the fetched_at of the next version, null for the latest); the
  latest view is `WHERE superseded_at IS NULL`. What adele builds (storage.select_sql).
Layout b (the latest values as today, plus the files of a next to them) answers the latest view
from plain, so its query times are those of plain; its costs are the disk of plain + a and two
writes per fetch.

Each key has one version, a second with probability --p2 and a third with probability --p3.
Each query runs once to warm up, then --runs times; the median is printed. The engine settings
are those of a query on the server (threads 4, memory_limit 2GB).

Usage (from server/): uv run python bench/wp3_versions_storage.py <empty folder> [--p2 0.3 --p3 0.1]
"""
from __future__ import annotations

import argparse
import datetime as dt
import statistics
import sys
import time
from pathlib import Path

import duckdb

from adele_server import storage
from adele_server.catalog import Table

UTC = dt.timezone.utc
ZONES, SERIES = 16, 6
START, END = dt.datetime(2019, 5, 1, tzinfo=UTC), dt.datetime(2026, 1, 1, tzinfo=UTC)
FIELDS = [{"name": "zone", "type": "string"}, {"name": "series", "type": "string"},
          {"name": "delivery_start", "type": "datetime"}, {"name": "value", "type": "number"}]
PK = ["zone", "series", "delivery_start"]


def months():
    m = START
    while m < END:
        nxt = dt.datetime(m.year + (m.month == 12), m.month % 12 + 1, 1, tzinfo=UTC)
        yield m, nxt
        m = nxt


def write(folder: Path, p2: float, p3: float) -> None:
    con = storage.connect()
    for name in ("plain", "a", "c"):
        (folder / name / "bench" / "t").mkdir(parents=True)
    for s, e in months():
        key = f"{s:%Y-%m}"
        # keys of the month; h: a fixed random number per key, picks its versions
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE k AS
            SELECT printf('Z%02d', z) AS zone, printf('S%d', sr) AS series, d AS delivery_start,
                   hash(z, sr, d) % 1000000 / 1e6 AS h
            FROM range({ZONES}) r1(z), range({SERIES}) r2(sr),
                 range(TIMESTAMPTZ '{s.isoformat()}', TIMESTAMPTZ '{e.isoformat()}', INTERVAL 15 MINUTE) r3(d)""")
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE v AS
            SELECT zone, series, delivery_start, 100 * h + n AS value,
                   delivery_start + (2 * n - 1) * INTERVAL '1 day' AS fetched_at  -- 1 day before, 1 and 3 days after
            FROM k, range(3) r(n)
            WHERE n = 0 OR (n = 1 AND h < {p2}) OR (n = 2 AND h < {p3})""")
        order = "delivery_start, zone, series"
        con.execute(f"""COPY (SELECT zone, series, delivery_start, value FROM v
                              QUALIFY row_number() OVER (PARTITION BY zone, series, delivery_start
                                                         ORDER BY fetched_at DESC) = 1
                              ORDER BY {order})
                        TO '{folder}/plain/bench/t/{key}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
        con.execute(f"COPY (SELECT * FROM v ORDER BY {order}, fetched_at) "
                    f"TO '{folder}/a/bench/t/{key}.parquet' (FORMAT parquet, COMPRESSION zstd)")
        con.execute(f"""COPY (SELECT *, lead(fetched_at) OVER (PARTITION BY zone, series, delivery_start
                                                               ORDER BY fetched_at) AS superseded_at
                              FROM v ORDER BY {order}, fetched_at)
                        TO '{folder}/c/bench/t/{key}.parquet' (FORMAT parquet, COMPRESSION zstd)""")
    con.close()


def latest_a(folder: Path, as_of: dt.datetime | None = None) -> str:
    """The latest view of layout a, as WP3 first built it: the as_of filter, then a window function."""
    where = f" WHERE fetched_at <= '{as_of.isoformat()}'" if as_of else ""
    return (f"SELECT zone, series, delivery_start, value FROM read_parquet('{folder}/a/bench/t/*.parquet'){where} "
            f"QUALIFY row_number() OVER (PARTITION BY zone, series, delivery_start ORDER BY fetched_at DESC) = 1")


def views(folder: Path) -> dict[str, str]:
    """layout --> SQL of its latest view."""
    plain = Table("bench", "t", FIELDS, PK, revisions="overwrite")
    versioned = Table("bench", "t", FIELDS, PK, revisions="append-only")
    return {"plain": storage.select_sql(folder / "plain", plain), "a": latest_a(folder),
            "c": storage.select_sql(folder / "c", versioned)}


QUERIES = {
    "one zone, one week": "SELECT avg(value) FROM latest WHERE zone = 'Z03' "
                          "AND delivery_start >= '2025-06-01' AND delivery_start < '2025-06-08'",
    "all zones, one month": "SELECT zone, avg(value) FROM latest WHERE delivery_start >= '2025-06-01' "
                            "AND delivery_start < '2025-07-01' GROUP BY zone",
    "all rows, by zone": "SELECT zone, avg(value) FROM latest GROUP BY zone",
    "count, min, max (describe)": "SELECT count(*), min(delivery_start), max(delivery_start) FROM latest",
}


def timed(con, sql: str, runs: int) -> float:
    con.execute(sql).fetchall()
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        con.execute(sql).fetchall()
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def bench_queries(folder: Path, runs: int) -> None:
    sqls = views(folder)
    con = duckdb.connect(config={"threads": 4, "memory_limit": "2GB"})
    con.execute("SET TimeZone = 'UTC'")
    rows = {}
    for layout, sql in sqls.items():
        con.execute(f"CREATE OR REPLACE VIEW latest AS {sql}")
        n = con.execute("SELECT count(*) FROM latest").fetchone()[0]
        stored = con.execute(f"SELECT count(*) FROM read_parquet('{folder}/{layout}/bench/t/*.parquet')").fetchone()[0]
        disk = sum(p.stat().st_size for p in (folder / layout / "bench" / "t").glob("*.parquet"))
        rows[layout] = {"latest rows": n, "stored rows": stored, "disk MB": disk / 1e6}
        for q, qs in QUERIES.items():
            rows[layout][q] = timed(con, qs, runs)
    print(f"{'':28}" + "".join(f"{x:>12}" for x in rows))
    for k in rows["plain"]:
        cells = []
        for layout in rows:
            v = rows[layout][k]
            cells.append(f"{v:>12,}" if isinstance(v, int) else f"{v:>12.1f}" if k == "disk MB" else
                         f"{v * 1000:>9.0f} ms")
        ratio = "" if k in ("latest rows", "stored rows") else \
            "   a/plain {:.2f}, c/plain {:.2f}".format(rows["a"][k] / rows["plain"][k], rows["c"][k] / rows["plain"][k])
        print(f"{k:28}" + "".join(cells) + ratio)
    # as_of: the view with as_of in each layout (layout c: as adele builds it)
    as_of = dt.datetime(2025, 6, 4, tzinfo=UTC)
    versioned = Table("bench", "t", FIELDS, PK, revisions="append-only")
    for layout, sql in (("a", latest_a(folder, as_of)), ("c", storage.select_sql(folder / "c", versioned, as_of))):
        con.execute(f"CREATE OR REPLACE VIEW latest AS {sql}")
        ms = timed(con, QUERIES["all zones, one month"], runs) * 1000
        print(f"as_of 2025-06-04, all zones, one month, layout {layout}: {ms:.0f} ms")
    con.close()


def bench_merge(folder: Path, runs: int) -> None:
    """One fetch of 3 days (16 zones x 6 series x 288 quarter hours), 10 % of the values revised,
    into the partition 2025-06: merge_overwrite on plain, merge_versions on c. On a copy of the
    partition each time, so that every run merges the same batch into the same file."""
    import shutil
    plain = Table("bench", "t", FIELDS, PK, revisions="overwrite")
    versioned = Table("bench", "t", FIELDS, PK, revisions="append-only")
    for layout, table, merge in (("plain", plain, storage.merge_overwrite), ("c", versioned, storage.merge_versions)):
        times = []
        for i in range(runs + 1):
            work = folder / f"merge_{layout}"
            if work.exists():
                shutil.rmtree(work)
            (work / "bench" / "t").mkdir(parents=True)
            shutil.copy(folder / layout / "bench" / "t" / "2025-06.parquet", work / "bench" / "t" / "2025-06.parquet")
            con = storage.connect()
            con.execute(f"""CREATE TEMP TABLE b AS SELECT zone, series, delivery_start,
                                   CASE WHEN hash(zone, series, delivery_start, {i}) % 10 = 0 THEN value + 1
                                        ELSE value END AS value
                            FROM ({storage.select_sql(work, table)})
                            WHERE delivery_start >= '2025-06-10' AND delivery_start < '2025-06-13'""")
            kw = {"fetched_at": dt.datetime(2026, 1, 1, tzinfo=UTC) + dt.timedelta(minutes=i)} if layout == "c" else {}
            t0 = time.perf_counter()
            merge(con, work, table, "b", "delivery_start", "month", **kw)
            if i:
                times.append(time.perf_counter() - t0)
            con.close()
        print(f"merge of a 3-day fetch into one month, layout {layout}: {statistics.median(times) * 1000:.0f} ms")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("folder", type=Path)
    p.add_argument("--p2", type=float, default=0.3)
    p.add_argument("--p3", type=float, default=0.1)
    p.add_argument("--runs", type=int, default=5)
    args = p.parse_args()
    done = args.folder / "written.txt"
    if not done.exists():
        if args.folder.exists() and any(args.folder.iterdir()):
            p.error(f"{args.folder} is not empty and holds no written.txt")
        t0 = time.perf_counter()
        write(args.folder, args.p2, args.p3)
        done.write_text(f"p2 {args.p2}, p3 {args.p3}\n")
        print(f"written in {time.perf_counter() - t0:.0f} s (p2 {args.p2}, p3 {args.p3})")
    else:
        print(f"data already written: {done.read_text().strip()}")
    print(f"duckdb {duckdb.__version__}")
    bench_queries(args.folder, args.runs)
    bench_merge(args.folder, args.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
