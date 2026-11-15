"""`revisions: append-only` (D30): every version of a row, the latest view, the versions view, as_of."""
from __future__ import annotations

import datetime as dt
import json

import duckdb
import pytest
import yaml

from adele_server import checks, engine, ingest, render, state, storage
from adele_server.catalog import load_catalog

UTC = dt.timezone.utc

LOAD = """\
name: test_load
title: Synthetic load
resources:
  - name: load
    schema:
      primaryKey: [zone, delivery_start]
      fields:
        - {name: zone, type: string, categories: [A, B]}
        - {name: delivery_start, type: datetime}
        - {name: resolution, type: duration}
        - {name: load, type: number, unit: MW}
adele:
  format_version: 1
  secrets: [ADELE_TEST_REVISE]
  refresh: {every: PT1H, lookback: PT12H, horizon: PT1H}
  revisions: append-only
"""

# Zone A = the hour of the day, zone B = the hour + 100. ADELE_TEST_REVISE, a JSON object
# {"<zone> <hour>": value or null}, revises those values (the hour as two digits).
LOAD_FETCH = """\
import json
import os

import pandas as pd

def fetch(start, end):
    revise = json.loads(os.environ.get("ADELE_TEST_REVISE") or "{}")
    idx = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    rows = []
    for z in ["A", "B"]:
        for t in idx:
            v = revise.get(f"{z} {t.hour:02d}", float(t.hour) + (100.0 if z == "B" else 0.0))
            rows.append((z, t, pd.Timedelta(hours=1), v))
    df = pd.DataFrame(rows, columns=["zone", "delivery_start", "resolution", "load"])
    df["load"] = pd.array(df["load"].tolist(), dtype="Float64")
    return df
"""

# Counts the rows of the latest view: with every version, it would count one row more per revision.
COUNT_CHECK = {"name": "rows_day", "question": "Rows on 2026-03-01 00:00-06:00?",
               "sql": "SELECT count(*) FROM test_load.load WHERE delivery_start < '2026-03-01 06:00Z'",
               "expected": 12, "tolerance": 0, "source": "Synthetic, https://example.org"}


def t(h: float) -> dt.datetime:
    return dt.datetime(2026, 3, 1, tzinfo=UTC) + dt.timedelta(hours=h)


@pytest.fixture
def load(env, monkeypatch):
    cfg, _, _ = env
    d = cfg.datasets_dir / "test_load"
    d.mkdir()
    (d / "datapackage.yaml").write_text(LOAD)
    (d / "fetch.py").write_text(LOAD_FETCH)
    catalog = load_catalog(cfg.datasets_dir)

    class Load:
        def __init__(self):
            self.cfg, self.catalog = cfg, catalog

        def reload(self):
            self.catalog = load_catalog(cfg.datasets_dir)

        @property
        def ds(self):
            return self.catalog["test_load"]

        def revise(self, values: dict | None):
            monkeypatch.setenv("ADELE_TEST_REVISE", json.dumps(values or {}))

        def fetch(self, start=t(0), end=t(6), revise=None):
            self.revise(revise)
            return ingest.fetch_window(cfg, self.catalog, self.ds, start, end)

        def scheduled(self, now, revise=None):
            self.revise(revise)
            return ingest.scheduled_fetch(cfg, self.catalog, self.ds, now)

        def q(self, sql, as_of=None):
            return engine.run(self.catalog, cfg.data_dir, cfg.query, sql, max_rows=1000, as_of=as_of)

        def state(self):
            return state.load(cfg.data_dir, "test_load")

    return Load()


def a05(ld, view="load", as_of=None):
    """The values of zone A at 05:00, oldest version first."""
    order = " ORDER BY fetched_at" if view.endswith("_versions") else ""
    return [r[0] for r in ld.q(f"SELECT load FROM test_load.{view} WHERE zone = 'A' "
                               f"AND delivery_start = '2026-03-01 05:00Z'{order}", as_of).rows]


# --- the merge ------------------------------------------------------------------------------

def test_first_fetch_stores_one_version_per_row(load):
    o = load.fetch()
    assert o.ok and o.rows == 12 and o.rows_changed == 12, o.error
    assert load.q("SELECT count(*) FROM test_load.load").rows == [[12]]
    res = load.q("SELECT * FROM test_load.load_versions LIMIT 1")
    assert res.columns == ["zone", "delivery_start", "resolution", "load", "fetched_at", "superseded_at"]
    assert res.types[-2:] == ["TIMESTAMP WITH TIME ZONE"] * 2
    assert load.q("SELECT count(*) FROM test_load.load_versions WHERE superseded_at IS NULL").rows == [[12]]
    assert load.q("SELECT * FROM test_load.load LIMIT 1").columns == ["zone", "delivery_start", "resolution", "load"]


def test_a_fetch_without_changes_adds_no_version(load):
    load.fetch()
    f = storage.partitions(load.cfg.data_dir, load.ds.tables["load"])[0]
    before = f.stat().st_mtime_ns
    o = load.fetch()
    assert o.ok and o.rows == 12 and o.rows_changed == 0 and o.partitions_written == 0
    assert f.stat().st_mtime_ns == before
    assert load.q("SELECT count(*) FROM test_load.load_versions").rows == [[12]]


def test_a_revised_value_adds_a_version(load):
    load.fetch()
    changed_before = load.state()["last_changed_at"]
    o = load.fetch(revise={"A 05": 7.5})
    assert o.ok and o.rows_changed == 1 and o.partitions_written == 1
    assert a05(load) == [7.5]
    assert a05(load, "load_versions") == [5.0, 7.5]
    assert load.q("SELECT count(*), count(DISTINCT fetched_at) FROM test_load.load_versions").rows == [[13, 2]]
    assert load.state()["last_changed_at"] >= changed_before
    # the old version is superseded at the fetched_at of the new one; every other row stays the latest
    (old, new), = load.q("SELECT max(superseded_at), max(fetched_at) FROM test_load.load_versions").rows
    assert old == new
    assert load.q("SELECT count(*) FROM test_load.load_versions WHERE superseded_at IS NULL").rows == [[12]]


def test_a_value_that_comes_back_is_a_new_version(load):
    load.fetch()
    load.fetch(revise={"A 05": 7.5})
    o = load.fetch()
    assert o.rows_changed == 1
    assert a05(load, "load_versions") == [5.0, 7.5, 5.0]
    assert a05(load) == [5.0]
    chain = load.q("SELECT fetched_at, superseded_at FROM test_load.load_versions WHERE zone = 'A' "
                   "AND delivery_start = '2026-03-01 05:00Z' ORDER BY fetched_at").rows
    assert [r[1] for r in chain] == [chain[1][0], chain[2][0], None]


def test_a_value_that_becomes_null_is_a_new_version_and_null_equals_null(load):
    load.fetch()
    assert load.fetch(revise={"A 05": None}).rows_changed == 1
    assert a05(load) == [None]
    assert load.fetch(revise={"A 05": None}).rows_changed == 0
    assert a05(load, "load_versions") == [5.0, None]


def test_a_row_that_the_source_no_longer_sends_is_kept(load):
    load.fetch(end=t(6))
    o = load.fetch(start=t(0), end=t(3))
    assert o.rows_changed == 0
    assert load.q("SELECT count(*) FROM test_load.load").rows == [[12]]


def test_a_backfill_run_twice_adds_nothing(load):
    first = ingest.backfill(load.cfg, load.catalog, load.ds, t(0), t(24), dt.timedelta(hours=6), now=t(30))
    again = ingest.backfill(load.cfg, load.catalog, load.ds, t(0), t(24), dt.timedelta(hours=6), now=t(30))
    assert sum(o.rows_changed for o in first) == 48 and sum(o.rows_changed for o in again) == 0
    assert load.q("SELECT count(*) FROM test_load.load_versions").rows == [[48]]


def test_a_clock_set_back_is_refused_and_nothing_is_written(load):
    load.fetch()
    t_ = load.ds.tables["load"]
    f = storage.partitions(load.cfg.data_dir, t_)[0]
    before = f.read_bytes()
    con = storage.connect()
    con.execute(f"CREATE TEMP TABLE b AS SELECT zone, delivery_start, resolution, load + 1 AS load "
                f"FROM read_parquet({storage.sql_str(f)})")
    with pytest.raises(storage.StorageError, match="clock set back"):
        storage.merge_versions(con, load.cfg.data_dir, t_, "b", fetched_at=dt.datetime(2020, 1, 1, tzinfo=UTC))
    assert f.read_bytes() == before


def test_repartition_keeps_every_version(load):
    load.fetch()
    load.fetch(revise={"A 05": 7.5})
    p = load.cfg.datasets_dir / "test_load" / "datapackage.yaml"
    d = yaml.safe_load(p.read_text())
    d["adele"]["partition"] = "day"
    p.write_text(yaml.safe_dump(d))
    load.reload()
    con = storage.connect()
    assert storage.repartition(con, load.cfg.data_dir, load.ds.tables["load"], "delivery_start", "day") == 1
    assert a05(load, "load_versions") == [5.0, 7.5]
    assert load.q("SELECT count(*) FROM test_load.load").rows == [[12]]


# --- the checks -----------------------------------------------------------------------------

def test_the_checks_pass_with_two_versions_and_run_on_the_latest_view(load):
    (load.cfg.datasets_dir / "test_load" / "checks.yaml").write_text(yaml.safe_dump({"checks": [COUNT_CHECK]}))
    load.reload()
    load.fetch()
    o = load.fetch(revise={"A 05": 7.5})
    assert o.ok and o.problems == [], o.problems
    assert load.state()["status"] == "ok"


def test_the_checks_find_a_superseded_at_that_breaks_the_chain(load):
    load.fetch()
    load.fetch(revise={"A 05": 7.5})
    f = storage.partitions(load.cfg.data_dir, load.ds.tables["load"])[0]
    con = storage.connect()
    # two latest versions of A 05: the latest view would show both
    con.execute(f"COPY (SELECT * REPLACE (NULL::TIMESTAMPTZ AS superseded_at) FROM read_parquet('{f}')) "
                f"TO '{f}.tmp' (FORMAT parquet)")
    con.close()
    f.with_name(f.name + ".tmp").replace(f)
    problems = checks.run_checks(load.catalog, load.ds, load.cfg.data_dir, load.cfg.query)
    assert any("superseded_at is not the fetched_at of the next version" in p for p in problems), problems


def test_a_change_of_policy_on_stored_data_is_refused_and_other_views_still_answer(load):
    cfg = load.cfg
    ingest.fetch_window(cfg, load.catalog, load.catalog["test_prices"], t(0), t(6))
    p = cfg.datasets_dir / "test_prices" / "datapackage.yaml"
    d = yaml.safe_load(p.read_text())
    d["adele"]["revisions"] = "append-only"
    p.write_text(yaml.safe_dump(d))
    load.reload()
    o = ingest.fetch_window(cfg, load.catalog, load.catalog["test_prices"], t(0), t(6))
    assert not o.ok and "the policy of a stored dataset can't change" in o.error
    load.fetch()
    assert load.q("SELECT count(*) FROM test_load.load").rows == [[12]]
    with pytest.raises(engine.QueryError, match="test_prices.prices can't be read"):
        load.q("SELECT count(*) FROM test_prices.prices")


# --- as_of ----------------------------------------------------------------------------------

def test_as_of_returns_what_adele_held_at_that_time(load):
    assert load.scheduled(t(12)).ok
    since = load.state()["versions_since"]
    mid = dt.datetime.now(UTC)
    assert load.scheduled(t(13), revise={"A 05": 7.5}).ok
    assert load.state()["versions_since"] == since  # written once
    assert a05(load) == [7.5]
    assert a05(load, as_of=mid) == [5.0]
    assert a05(load, as_of=dt.datetime.now(UTC)) == [7.5]
    assert a05(load, "load_versions", as_of=mid) == [5.0]
    # as of mid, the version 5.0 was the latest: its superseded_at (later than mid) doesn't show
    assert load.q("SELECT count(*) FROM test_load.load_versions WHERE superseded_at IS NOT NULL", as_of=mid).rows == [[0]]
    assert load.q("SELECT count(*) FROM test_load.load_versions WHERE superseded_at IS NOT NULL").rows == [[1]]
    # the rows of the second run that the first didn't have (13:00) are not there as of mid
    assert load.q("SELECT max(delivery_start) FROM test_load.load", as_of=mid).rows == [["2026-03-01 12:00:00Z"]]
    with pytest.raises(engine.QueryError, match="keeps versions since"):
        load.q("SELECT count(*) FROM test_load.load", as_of=since - dt.timedelta(seconds=1))


def test_versions_since_is_set_by_a_backfill_that_reaches_the_present(load):
    ingest.backfill(load.cfg, load.catalog, load.ds, t(0), t(13), dt.timedelta(hours=6), now=t(12))
    assert load.state()["versions_since"] is not None


def test_as_of_without_a_scheduled_run_is_refused(load):
    load.fetch()
    assert "versions_since" not in load.state()
    with pytest.raises(engine.QueryError, match="no versions yet"):
        load.q("SELECT count(*) FROM test_load.load", as_of=dt.datetime.now(UTC))


def test_as_of_refuses_a_query_that_reads_a_dataset_without_versions(load):
    load.scheduled(t(12))
    ingest.fetch_window(load.cfg, load.catalog, load.catalog["test_prices"], t(0), t(6))
    now = dt.datetime.now(UTC)
    join = ("SELECT count(*) FROM test_load.load l JOIN test_prices.prices p "
            "ON l.delivery_start = p.delivery_start AND l.zone = p.zone")
    assert load.q(join).rows == [[12]]
    with pytest.raises(engine.QueryError, match="test_prices keeps only the latest value"):
        load.q(join, as_of=now)
    with pytest.raises(engine.QueryError, match="reads none of them"):
        load.q("SELECT 1", as_of=now)


def test_parse_as_of():
    assert engine.parse_as_of("2026-11-15") == dt.datetime(2026, 11, 15, tzinfo=UTC)
    assert engine.parse_as_of("2026-11-15T12:00+01:00") == dt.datetime(2026, 11, 15, 11, tzinfo=UTC)
    assert engine.parse_as_of("2026-11-15 12:00Z") == dt.datetime(2026, 11, 15, 12, tzinfo=UTC)
    with pytest.raises(engine.QueryError, match="ISO 8601"):
        engine.parse_as_of("yesterday'; DROP")


# --- what agents read -----------------------------------------------------------------------

def test_describe_and_footer_explain_the_versions(load):
    load.scheduled(t(12))
    load.scheduled(t(13), revise={"A 05": 7.5})
    card = render.describe_dict(load.cfg, load.ds)
    assert card["revisions"].startswith("append-only: every version")
    assert "backfilled" in card["versions_since"]
    table = card["tables"][0]
    assert table["rows"] == 28 and table["versions"].startswith("29 rows in test_load.load_versions")
    computed = render.merged_descriptor(load.cfg, load.ds)["adele"]["computed"]
    assert computed["tables"]["load"]["versions"] == 29 and computed["versions_since"]

    def footer(sql, as_of=None):
        res = load.q(sql, as_of)
        return render.query_footer(load.cfg, load.catalog, res.datasets, res.versions, res.as_of)

    assert "versions since" not in footer("SELECT count(*) FROM test_load.load")
    assert "versions since" in footer("SELECT count(*) FROM test_load.load_versions")
    assert "-- test_load: as of 2026-" in footer("SELECT count(*) FROM test_load.load", dt.datetime.now(UTC))


def test_versions_view_exists_only_for_append_only_tables(load):
    ingest.fetch_window(load.cfg, load.catalog, load.catalog["test_prices"], t(0), t(6))
    with pytest.raises(engine.QueryError, match="prices_versions"):
        load.q("SELECT * FROM test_prices.prices_versions")


def test_one_fetch_stamps_its_rows_with_one_fetched_at(load):
    load.fetch()
    con = duckdb.connect()
    f = storage.partitions(load.cfg.data_dir, load.ds.tables["load"])[0]
    (n,) = con.execute(f"SELECT count(DISTINCT fetched_at) FROM read_parquet('{f}')").fetchone()
    assert n == 1
