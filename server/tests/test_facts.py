"""The facts of a table (rows, coverage, resolution periods) are computed per partition file (D37)."""
from __future__ import annotations

import datetime as dt
import os
import random
import threading
import time

import duckdb
import pytest
import yaml

from adele_server import render, storage
from adele_server.catalog import load_catalog
from adele_server.engine import iso_duration

UTC = dt.timezone.utc
H, Q = dt.timedelta(hours=1), dt.timedelta(minutes=15)


def utc(*args):
    return dt.datetime(*args, tzinfo=UTC)


def whole_table(data_dir, t):
    """The resolution periods, computed over all files at once (the code before D37)."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    rows = con.execute(f"""
        WITH r AS (
          SELECT zone, resolution, delivery_start AS d,
                 CASE WHEN resolution IS DISTINCT FROM lag(resolution) OVER w
                        OR delivery_start IS DISTINCT FROM lag(delivery_start + resolution) OVER w
                      THEN 1 ELSE 0 END AS chg
          FROM ({storage.select_sql(data_dir, t)}) WINDOW w AS (PARTITION BY zone ORDER BY delivery_start)),
        g AS (SELECT *, sum(chg) OVER (PARTITION BY zone ORDER BY d) AS grp FROM r)
        SELECT zone, resolution, min(d), max(d) FROM g GROUP BY zone, resolution, grp ORDER BY zone, min(d)
    """).fetchall()
    return [{"series": z, "resolution": iso_duration(r), "first": a, "last": b} for z, r, a, b in rows]


def write(data_dir, t, rows):
    """(zone, delivery_start, resolution, price), or with fetched_at and superseded_at, into one file per month."""
    d = storage.table_dir(data_dir, t)
    d.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    types = {"zone": "VARCHAR", "delivery_start": "TIMESTAMPTZ", "resolution": "INTERVAL", "price": "DOUBLE"}
    if t.versioned:
        types |= {"fetched_at": "TIMESTAMPTZ", "superseded_at": "TIMESTAMPTZ"}
    for month in sorted({r[1].strftime("%Y-%m") for r in rows}):
        con.execute(f"CREATE OR REPLACE TABLE x ({', '.join(f'{c} {ty}' for c, ty in types.items())})")
        con.executemany(f"INSERT INTO x VALUES ({', '.join('?' * len(types))})",
                        [r for r in rows if r[1].strftime("%Y-%m") == month])
        con.execute(f"COPY x TO '{d / (month + '.parquet')}' (FORMAT parquet)")


def hours(zone, start, end, step, skip=()):
    out, at = [], start
    while at < end:
        if at not in skip:
            out.append((zone, at, step, 1.0))
        at += step
    return out


@pytest.fixture
def table(env):
    cfg, catalog, _ = env
    return cfg, catalog, catalog["test_prices"].tables["prices"]


CASES = {
    "one resolution over three months": hours("A", utc(2026, 1, 30), utc(2026, 3, 2), H),
    "a change at the border of a month":
        hours("A", utc(2026, 1, 30), utc(2026, 2, 1), H) + hours("A", utc(2026, 2, 1), utc(2026, 2, 2), Q),
    "a change inside a month":
        hours("A", utc(2026, 1, 30), utc(2026, 2, 10), H) + hours("A", utc(2026, 2, 10), utc(2026, 2, 11), Q),
    "a gap at the border": hours("A", utc(2026, 1, 30), utc(2026, 2, 3), H, skip=[utc(2026, 2, 1)]),
    "a gap before the border": hours("A", utc(2026, 1, 30), utc(2026, 2, 3), H, skip=[utc(2026, 1, 31, 23)]),
    "a month without a series":
        hours("A", utc(2026, 1, 1), utc(2026, 4, 1), H) + hours("B", utc(2026, 1, 1), utc(2026, 2, 1), H)
        + hours("B", utc(2026, 3, 1), utc(2026, 4, 1), H),
}


@pytest.mark.parametrize("name", CASES)
def test_the_periods_of_the_files_join_into_those_of_the_table(table, name):
    cfg, _, t = table
    write(cfg.data_dir, t, CASES[name])
    assert render.table_facts(cfg.data_dir, t).periods == whole_table(cfg.data_dir, t)


@pytest.mark.parametrize("seed", range(5))
def test_the_same_for_random_gaps_and_changes_with_old_versions(env, tmp_path, seed):
    cfg, _, _ = env
    path = cfg.datasets_dir / "test_prices" / "datapackage.yaml"
    d = yaml.safe_load(path.read_text())
    d["adele"]["revisions"] = "append-only"
    path.write_text(yaml.safe_dump(d))
    t = load_catalog(cfg.datasets_dir)["test_prices"].tables["prices"]
    rnd, rows = random.Random(seed), []
    for zone in "AB":
        at, step = utc(2026, 1, 25), H
        while at < utc(2026, 4, 5):
            if rnd.random() < 0.01:
                step = Q if step == H else H
            if rnd.random() > 0.01:
                if rnd.random() < 0.1:  # an older version, with another resolution: it must not count
                    rows.append((zone, at, 2 * H, 1.0, utc(2026, 5, 1), utc(2026, 5, 2)))
                rows.append((zone, at, step, 2.0, utc(2026, 5, 2), None))
            at += step
    write(cfg.data_dir, t, rows)
    f = render.table_facts(cfg.data_dir, t)
    assert f.periods == whole_table(cfg.data_dir, t) and len(f.periods) > 20
    latest = [r for r in rows if r[5] is None]
    assert (f.rows, f.versions) == (len(latest), len(rows))
    assert (f.first, f.last) == (min(r[1] for r in latest), max(r[1] for r in latest))


@pytest.fixture
def computed(monkeypatch):
    """The files that were computed."""
    seen, real = [], storage.file_facts
    monkeypatch.setattr(storage, "file_facts", lambda con, d, t, p: seen.append(p.name) or real(con, d, t, p))
    return seen


def test_only_the_files_that_changed_are_computed_again(table, computed):
    cfg, _, t = table
    write(cfg.data_dir, t, hours("A", utc(2026, 1, 30), utc(2026, 4, 2), H))
    assert render.table_facts(cfg.data_dir, t).rows == 62 * 24
    assert computed == ["2026-01.parquet", "2026-02.parquet", "2026-03.parquet", "2026-04.parquet"]
    render.table_facts(cfg.data_dir, t)
    assert len(computed) == 4
    time.sleep(0.01)
    write(cfg.data_dir, t, hours("A", utc(2026, 4, 1), utc(2026, 4, 4), H))  # as a fetch: the last month again
    assert render.table_facts(cfg.data_dir, t).rows == 64 * 24
    assert computed[4:] == ["2026-04.parquet"]
    os.remove(storage.table_dir(cfg.data_dir, t) / "2026-01.parquet")
    f = render.table_facts(cfg.data_dir, t)
    assert (f.rows, f.first) == (62 * 24, utc(2026, 2, 1)) and len(computed) == 5


def test_lists_at_the_same_time_compute_once(table, computed):
    cfg, catalog, t = table
    write(cfg.data_dir, t, hours("A", utc(2026, 1, 30), utc(2026, 4, 2), H))
    out: list = []
    ths = [threading.Thread(target=lambda: out.append(render.render_list(cfg, catalog))) for _ in range(6)]
    for th in ths:
        th.start()
    for th in ths:
        th.join(20)
    assert len(set(out)) == 1 and len(out) == 6 and len(computed) == 4


def test_list_and_describe_open_no_connection_without_limits(table, monkeypatch):
    cfg, catalog, t = table
    write(cfg.data_dir, t, hours("A", utc(2026, 1, 30), utc(2026, 2, 2), H))
    seen, real = [], storage.connect

    def connect(*a, **kw):
        con = real(*a, **kw)
        seen.append(con.execute("SELECT current_setting('memory_limit'), current_setting('max_temp_directory_size')")
                    .fetchone())
        return con

    monkeypatch.setattr(storage, "connect", connect)
    render.render_list(cfg, catalog)
    render.render_describe(cfg, catalog["test_prices"])
    render.merged_descriptor(cfg, catalog["test_prices"])
    render.query_footer(cfg, catalog, ["test_prices"])
    assert len(seen) == 2 and set(seen) == {("476.8 MiB", "953.6 MiB")}


def test_a_table_without_files(table):
    cfg, _, t = table
    f = render.table_facts(cfg.data_dir, t)
    assert (f.rows, f.first, f.last, f.periods, f.window) == (0, None, None, [], None)
    assert f.duckdb_types["price"] == "DOUBLE"
