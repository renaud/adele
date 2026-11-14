"""`revisions: none` (rows never change: fetch only what isn't stored) and `adele.partition`."""
from __future__ import annotations

import datetime as dt
import json

import duckdb
import pytest

from adele_server import checks, ingest, render, state, storage
from adele_server.catalog import CatalogError, load_catalog

UTC = dt.timezone.utc

RUNS = """\
name: test_runs
title: Synthetic forecast runs
resources:
  - name: runs
    schema:
      primaryKey: [init_time, delivery_start]
      fields:
        - {name: init_time, type: datetime}
        - {name: delivery_start, type: datetime}
        - {name: value, type: number}
adele:
  format_version: 1
  secrets: [ADELE_TEST_CALLS, ADELE_TEST_FAULT]
  refresh: {every: PT1H, lookback: PT12H, horizon: PT1H}
  revisions: none
  window: init_time
  partition: day
"""

# One run per hour, leads 1-3 h. Logs each window it is called with. Faults: `skip03` leaves
# out the run of 03:00 (published late), `all` ignores the window (returns the whole day),
# `bump` changes the values.
RUNS_FETCH = """\
import json
import os

import pandas as pd

def fetch(start, end):
    with open(os.environ["ADELE_TEST_CALLS"], "a") as fh:
        fh.write(json.dumps([start.isoformat(), end.isoformat()]) + "\\n")
    fault = os.environ.get("ADELE_TEST_FAULT", "")
    if fault.startswith("all"):
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = day, day + pd.Timedelta(days=1)
    inits = pd.date_range(start.replace(minute=0, second=0, microsecond=0), end, freq="h", inclusive="left", tz="UTC")
    inits = [i for i in inits if i >= start and not (fault == "skip03" and i.hour == 3)]
    bump = 100.0 if fault.endswith("bump") else 0.0
    rows = [(i, i + pd.Timedelta(hours=lead - 1), float(lead) + bump) for i in inits for lead in (1, 2, 3)]
    return pd.DataFrame(rows, columns=["init_time", "delivery_start", "value"]).astype(
        {"init_time": "datetime64[ns, UTC]", "delivery_start": "datetime64[ns, UTC]", "value": "float64"})
"""


def t(h: float, day: int = 1) -> dt.datetime:
    return dt.datetime(2026, 3, day, tzinfo=UTC) + dt.timedelta(hours=h)


@pytest.fixture
def runs(env, tmp_path, monkeypatch):
    cfg, _, _ = env
    d = cfg.datasets_dir / "test_runs"
    d.mkdir()
    (d / "datapackage.yaml").write_text(RUNS)
    (d / "fetch.py").write_text(RUNS_FETCH)
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setenv("ADELE_TEST_CALLS", str(calls))
    catalog = load_catalog(cfg.datasets_dir)

    def fetch(start, end, cat=None):
        calls.write_text("")
        cat = cat or catalog
        o = ingest.fetch_window(cfg, cat, cat["test_runs"], start, end)
        return o, [tuple(json.loads(ln)) for ln in calls.read_text().splitlines()]

    return cfg, catalog, fetch


def stored(cfg, sql):
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{cfg.data_dir}/test_runs/runs/*.parquet')")
    return con.execute(sql).fetchall()


def files(cfg):
    return sorted(p.name for p in (cfg.data_dir / "test_runs" / "runs").glob("*.parquet"))


# --- revisions: none ------------------------------------------------------------------------

def test_first_fetch_takes_the_whole_window(runs):
    cfg, _, fetch = runs
    o, calls = fetch(t(0), t(6))
    assert o.ok and o.rows == 18 and o.rows_changed == 18, o.error
    assert calls == [(t(0).isoformat(), t(6).isoformat())]


def test_refetch_asks_only_for_the_parts_without_stored_rows(runs):
    cfg, _, fetch = runs
    fetch(t(0), t(6))
    o, calls = fetch(t(0), t(8))
    # gaps between the stored runs 00..05 (each excluded), then (05:00, 08:00)
    eps = ingest.EPSILON
    assert calls == [((t(h) + eps).isoformat(), t(h + 1).isoformat()) for h in range(5)] + \
        [((t(5) + eps).isoformat(), t(8).isoformat())]
    assert o.ok and o.windows_fetched == 6 and o.rows == 6 and o.rows_changed == 6
    assert stored(cfg, "SELECT count(*), count(DISTINCT init_time) FROM t") == [(24, 8)]


def test_nothing_to_fetch_when_the_window_is_stored(runs):
    cfg, _, fetch = runs
    fetch(t(0), t(6))
    o, calls = fetch(t(2), t(4))
    # stored values 02:00 and 03:00: only the gaps between and after them, which hold no run
    eps = ingest.EPSILON
    assert calls == [((t(2) + eps).isoformat(), t(3).isoformat()), ((t(3) + eps).isoformat(), t(4).isoformat())]
    assert o.ok and o.rows == 0 and o.rows_changed == 0 and o.partitions_written == 0


def test_a_late_run_is_fetched_later(runs, monkeypatch):
    cfg, _, fetch = runs
    monkeypatch.setenv("ADELE_TEST_FAULT", "skip03")
    fetch(t(0), t(6))
    assert stored(cfg, "SELECT count(DISTINCT init_time) FROM t") == [(5,)]
    monkeypatch.delenv("ADELE_TEST_FAULT")
    o, calls = fetch(t(0), t(6))
    assert ((t(2) + ingest.EPSILON).isoformat(), t(4).isoformat()) in calls
    assert o.rows_changed == 3
    assert stored(cfg, "SELECT count(DISTINCT init_time) FROM t") == [(6,)]


def test_rows_outside_the_gaps_are_dropped(runs, monkeypatch):
    cfg, _, fetch = runs
    fetch(t(0), t(6))
    monkeypatch.setenv("ADELE_TEST_FAULT", "all_bump")  # the source ignores the window and changed its values
    o, _ = fetch(t(0), t(8))
    # each window keeps only its own rows: the new runs 06 and 07 (once each), stored runs untouched
    assert o.ok and o.rows == 6 and o.rows_changed == 6, o.error
    assert stored(cfg, "SELECT count(*), max(value) FILTER (WHERE init_time < '2026-03-01 06:00+00') FROM t") == [(24, 3.0)]


def test_a_changed_stored_row_is_an_error_and_nothing_is_written(runs):
    cfg, catalog, fetch = runs
    fetch(t(0), t(6))
    table = catalog["test_runs"].tables["runs"]
    before = {p: p.stat().st_mtime_ns for p in (cfg.data_dir / "test_runs" / "runs").glob("*.parquet")}
    con = storage.connect()
    con.execute("CREATE TEMP TABLE b AS SELECT * FROM (VALUES "
                "('2026-03-01 07:00+00'::TIMESTAMPTZ, '2026-03-01 07:00+00'::TIMESTAMPTZ, 1.0), "
                "('2026-03-01 01:00+00'::TIMESTAMPTZ, '2026-03-01 01:00+00'::TIMESTAMPTZ, 99.0)) v(init_time, delivery_start, value)")
    with pytest.raises(storage.StorageError, match=r"changed stored rows \(revisions: none\)"):
        storage.merge_append(con, cfg.data_dir, table, "b", "init_time", "day")
    assert {p: p.stat().st_mtime_ns for p in before} == before
    assert stored(cfg, "SELECT count(*), max(value) FROM t") == [(18, 3.0)]
    # an identical row is skipped, a new one added
    con.execute("UPDATE b SET value = 1.0")
    m = storage.merge_append(con, cfg.data_dir, table, "b", "init_time", "day")
    assert m.rows_changed == 1 and stored(cfg, "SELECT count(*) FROM t") == [(19,)]


def test_backfill_resumes(runs):
    cfg, catalog, fetch = runs
    ds = catalog["test_runs"]
    outs = ingest.backfill(cfg, catalog, ds, t(0), t(12), dt.timedelta(hours=4))
    assert [o.rows_changed for o in outs] == [12, 12, 12]
    outs = ingest.backfill(cfg, catalog, ds, t(0), t(12), dt.timedelta(hours=4))
    assert [o.rows_changed for o in outs] == [0, 0, 0] and all(o.ok for o in outs)


def test_windows_to_fetch_without_data(runs):
    cfg, catalog, _ = runs
    assert ingest.windows_to_fetch(cfg.data_dir, catalog["test_runs"], t(0), t(3)) == [(t(0), t(3))]


def test_overwrite_always_fetches_the_whole_window(env):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    ingest.fetch_window(cfg, catalog, ds, t(0), t(6))
    assert ingest.windows_to_fetch(cfg.data_dir, ds, t(0), t(6)) == [(t(0), t(6))]


def test_describe_states_the_policy(runs):
    cfg, catalog, fetch = runs
    fetch(t(0), t(2))
    card = render.describe_dict(cfg, catalog["test_runs"])
    assert card["revisions"] == "rows never change once stored (each is fetched once)"


# --- adele.partition -------------------------------------------------------------------------

def test_day_partitions_follow_the_window_column(runs):
    cfg, _, fetch = runs
    o, _ = fetch(t(22), t(2, day=2))
    assert o.ok and o.partitions_written == 2
    # the run of 23:00 delivers on 2 March but stays in the file of its init day
    assert files(cfg) == ["2026-03-01.parquet", "2026-03-02.parquet"]


def test_partition_must_be_month_or_day(env):
    cfg, _, _ = env
    d = cfg.datasets_dir / "test_runs"
    d.mkdir()
    (d / "datapackage.yaml").write_text(RUNS.replace("partition: day", "partition: week"))
    (d / "fetch.py").write_text(RUNS_FETCH)
    with pytest.raises(CatalogError, match="adele.partition"):
        load_catalog(cfg.datasets_dir)


def test_a_change_of_partition_needs_repartition(runs):
    cfg, _, fetch = runs
    desc = cfg.datasets_dir / "test_runs" / "datapackage.yaml"
    desc.write_text(RUNS.replace("partition: day", "partition: month"))
    month_cat = load_catalog(cfg.datasets_dir)
    o, _ = fetch(t(0), t(30), cat=month_cat)
    assert o.ok and files(cfg) == ["2026-03.parquet"]

    desc.write_text(RUNS)  # back to day
    day_cat = load_catalog(cfg.datasets_dir)
    ds = day_cat["test_runs"]
    o, calls = fetch(t(30), t(31), cat=day_cat)
    assert not o.ok and "repartition" in o.error and calls == []
    problems = checks.run_checks(day_cat, ds, cfg.data_dir, cfg.query)
    assert any("adele-server repartition test_runs" in p for p in problems)

    con = storage.connect()
    n = storage.repartition(con, cfg.data_dir, ds.tables["runs"], ds.window, ds.partition)
    assert n == 2 and files(cfg) == ["2026-03-01.parquet", "2026-03-02.parquet"]
    assert stored(cfg, "SELECT count(*) FROM t") == [(90,)]
    assert not (cfg.data_dir / "test_runs" / "runs.old").exists()
    o, _ = fetch(t(30), t(31), cat=day_cat)
    assert o.ok and o.rows_changed == 3, o.error


# --- weathernext3/fetch.py, the parts that need no network -------------------------------------

def _wn3():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "datasets" / "weathernext3" / "fetch.py"
    spec = importlib.util.spec_from_file_location("wn3_fetch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wn3_runs_are_3_hourly_before_2026_and_hourly_after():
    wn3 = _wn3()
    d = lambda *a: dt.datetime(*a, tzinfo=UTC)  # noqa: E731
    assert wn3._inits(d(2025, 12, 31, 17), d(2026, 1, 1, 3)) == \
        [d(2025, 12, 31, 18), d(2025, 12, 31, 21), d(2026, 1, 1, 0), d(2026, 1, 1, 1), d(2026, 1, 1, 2)]
    # a gap between two stored runs (exclusive lower bound) holds no run
    assert wn3._inits(d(2026, 3, 1, 5) + ingest.EPSILON, d(2026, 3, 1, 6)) == []
    with pytest.raises(ValueError, match="no runs before 2024-01-01"):
        wn3.fetch(d(2023, 12, 31), d(2024, 1, 2))


def test_wn3_decodes_the_init_time_with_its_units():
    wn3 = _wn3()
    # equal raw values in the two yearly stores: only the units tell 00 UTC from 03 UTC
    assert wn3._decode([0, 6], "hours since 2025-01-01 00:00:00")[1] == dt.datetime(2025, 1, 1, 6, tzinfo=UTC)
    assert wn3._decode([0, 6], "hours since 2025-01-01 03:00:00")[1] == dt.datetime(2025, 1, 1, 9, tzinfo=UTC)
    assert wn3._decode(0.5, "days since 2026-11-12 00:00:00") == [dt.datetime(2026, 11, 12, 12, tzinfo=UTC)]
