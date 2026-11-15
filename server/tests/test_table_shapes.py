"""WP2, table shapes: the `adele:` block per table, tables by calendar day, month or year in a zone
(D26), and tables without a time column (D22). Synthetic data only."""
from __future__ import annotations

import datetime as dt
import json
import os

import duckdb
import pytest
import yaml

from adele_server import checks, engine, ingest, render, storage
from adele_server.catalog import CatalogError, load_catalog

UTC = dt.timezone.utc

SHAPES = """\
name: test_shapes
title: Synthetic table shapes
resources:
  - name: prices
    adele:
      resolution: [{from: 2026-01-01, value: PT15M}]
      partition: day
    schema:
      primaryKey: [zone, delivery_start]
      fields:
        - {name: zone, type: string}
        - {name: delivery_start, type: datetime}
        - {name: price, type: number, unit: EUR/MWh}
  - name: daily
    adele: {timezone: Europe/Zurich}
    schema:
      primaryKey: [zone, delivery_date]
      fields:
        - {name: zone, type: string}
        - {name: delivery_date, type: date}
        - {name: energy, type: number, unit: MWh}
  - name: monthly
    adele: {timezone: Europe/Zurich}
    schema:
      primaryKey: [zone, delivery_month]
      fields:
        - {name: zone, type: string}
        - {name: delivery_month, type: date}
        - {name: energy_month, type: number, unit: GWh}
  - name: stations
    schema:
      primaryKey: [station]
      fields:
        - {name: station, type: string}
        - {name: altitude, type: number, unit: m}
adele:
  format_version: 2
  secrets: [ADELE_TEST_FAULT, ADELE_TEST_BUMP]
  refresh: {every: PT1H, lookback: P3D, horizon: PT0S}
  revisions: overwrite
"""

# The source serves whole local days and months, one more on each side of the window: the
# server keeps the periods that overlap the window. Faults: `drop` leaves out a station,
# `empty_stations` returns no station, `midmonth` stamps a month on its 15th, `ts` returns the
# months as timestamps.
SHAPES_FETCH = """\
import datetime as dt
import os

import pandas as pd

ZONES = ["A", "B"]
TZ = "Europe/Zurich"


def fetch(start, end):
    fault = os.environ.get("ADELE_TEST_FAULT", "")
    bump = float(os.environ.get("ADELE_TEST_BUMP", "0"))
    q = pd.date_range(start, end, freq="15min", inclusive="left", tz="UTC")
    prices = pd.DataFrame([(z, t, float(t.hour) + bump) for z in ZONES for t in q],
                          columns=["zone", "delivery_start", "price"])
    first, last = pd.Timestamp(start).tz_convert(TZ).date(), pd.Timestamp(end).tz_convert(TZ).date()
    days = pd.date_range(first - dt.timedelta(days=1), last + dt.timedelta(days=1), freq="D")
    daily = pd.DataFrame([(z, d.date(), 24.0 + bump) for z in ZONES for d in days],
                         columns=["zone", "delivery_date", "energy"])
    months = pd.date_range(pd.Timestamp(first.replace(day=1)) - pd.DateOffset(months=1),
                           pd.Timestamp(last.replace(day=1)) + pd.DateOffset(months=1), freq="MS")
    monthly = pd.DataFrame([(z, m.date(), 700.0 + bump) for z in ZONES for m in months],
                           columns=["zone", "delivery_month", "energy_month"])
    stations = pd.DataFrame({"station": ["PAY", "BAS", "GVE"], "altitude": [490.0, 316.0, 411.0 + bump]})
    if fault == "drop":
        stations = stations.iloc[:2]
    if fault == "empty_stations":
        stations = stations.iloc[:0]
    if fault == "midmonth":
        monthly["delivery_month"] = monthly["delivery_month"].map(lambda d: d.replace(day=15))
    if fault == "ts":
        monthly["delivery_month"] = pd.to_datetime(monthly["delivery_month"])
    return {"prices": prices, "daily": daily, "monthly": monthly, "stations": stations}
"""


def t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


def add(cfg, name, descriptor, fetch=SHAPES_FETCH):
    d = cfg.datasets_dir / name
    d.mkdir(exist_ok=True)
    (d / "datapackage.yaml").write_text(descriptor)
    (d / "fetch.py").write_text(fetch)
    return load_catalog(cfg.datasets_dirs)


@pytest.fixture
def shapes(env):
    cfg, _, _ = env
    catalog = add(cfg, "test_shapes", SHAPES)
    return cfg, catalog, catalog["test_shapes"]


def rows(cfg, catalog, sql):
    return engine.run(catalog, cfg.data_dir, cfg.query, sql, max_rows=10_000).rows


def files(cfg, table):
    return sorted(p.name for p in (cfg.data_dir / "test_shapes" / table).glob("*.parquet"))


# --- catalog ----------------------------------------------------------------------------------

def test_each_table_has_its_window_partition_resolution_and_zone(shapes):
    _, _, ds = shapes
    p, d, m, s = (ds.tables[n] for n in ("prices", "daily", "monthly", "stations"))
    assert (p.window, p.partition, p.resolution, p.timezone) == (
        "delivery_start", "day", [{"from": dt.date(2026, 1, 1), "value": "PT15M"}], None)
    assert (d.window, d.partition, d.period, d.timezone) == ("delivery_date", "month", "day", "Europe/Zurich")
    assert (m.window, m.period, m.resolution) == ("delivery_month", "month", [])
    assert (s.window, s.has_time, s.time_field) == (None, False, None)
    assert ds.windows == ["delivery_start", "delivery_date", "delivery_month"]


def test_a_package_resolution_applies_to_the_tables_with_delivery_start_only(env):
    cfg, _, _ = env
    desc = SHAPES.replace("      resolution: [{from: 2026-01-01, value: PT15M}]\n", "").replace(
        "  revisions: overwrite\n", "  revisions: overwrite\n  resolution: [{from: 2025-01-01, value: PT1H}]\n")
    ds = add(cfg, "test_shapes", desc)["test_shapes"]
    assert ds.tables["prices"].resolution == [{"from": dt.date(2025, 1, 1), "value": "PT1H"}]
    assert ds.tables["monthly"].resolution == ds.tables["stations"].resolution == []


def _resource(d, name):
    return next(r for r in d["resources"] if r["name"] == name)


def _fields(d, name):
    return _resource(d, name)["schema"]["fields"]


@pytest.mark.parametrize("fn, message", [
    (lambda d: d["adele"].update(format_version=1), "needs adele.format_version: 2"),
    (lambda d: (d["adele"].update(format_version=1), d.update(resources=[_resource(d, "stations")])),
     "without a time column needs adele.format_version: 2"),
    (lambda d: _resource(d, "daily").pop("adele"), "adele.timezone is required"),
    (lambda d: _resource(d, "daily").update(adele={"timezone": "CET"}), "abbreviation such as CET is refused"),
    (lambda d: _resource(d, "daily").update(adele={"timezone": "Europe/Atlantis"}), "not a zone that DuckDB knows"),
    (lambda d: _resource(d, "prices")["adele"].update(timezone="Europe/Zurich"), "only a table by calendar day"),
    (lambda d: _resource(d, "stations").update(adele={"timezone": "UTC"}), "only a table by calendar day"),
    (lambda d: _resource(d, "monthly")["adele"].update(resolution=[{"from": "2026-01-01", "value": "P1D"}]),
     "only a table with delivery_start has a resolution"),
    (lambda d: _resource(d, "stations").update(adele={"partition": "day"}), "stored as one file"),
    (lambda d: _resource(d, "prices")["adele"].update(partition="year"), "adele.partition must be one of"),
    (lambda d: _resource(d, "prices")["adele"].update(window="init_time"), "unknown key window"),
    (lambda d: d["adele"].update(timezone="Europe/Zurich"), "the zone goes in the `adele:` block of the table"),
    (lambda d: _fields(d, "monthly")[1].update(type="datetime"), "'delivery_month' must have type date"),
    (lambda d: _fields(d, "daily").append({"name": "delivery_start", "type": "datetime"}), "at most one time field"),
    (lambda d: _resource(d, "monthly")["schema"].update(primaryKey=["zone"]), "'delivery_month' must be in the primaryKey"),
    (lambda d: d["adele"].update(revisions="append-only"), "stations: a table without a time column can't be append-only"),
    (lambda d: (d["adele"].update(revisions="none"), d["resources"].remove(_resource(d, "stations"))),
     "revisions: none needs one window column of type datetime"),
])
def test_invalid_shapes_are_refused(env, fn, message):
    cfg, _, _ = env
    d = yaml.safe_load(SHAPES)
    fn(d)
    with pytest.raises(CatalogError, match=message):
        add(cfg, "test_shapes", yaml.safe_dump(d, sort_keys=False))


# --- fetch, storage, checks -------------------------------------------------------------------

def test_a_fetch_keeps_the_periods_that_overlap_the_window(shapes):
    cfg, catalog, ds = shapes
    o = ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 00:00"), t("2026-04-02 00:00"))
    assert o.ok, o.error
    assert o.problems == []
    # 2026-04-02 in Zurich starts at 2026-04-01 22:00 UTC, inside the window; 2026-03-29 ends at 22:00 UTC before it
    assert rows(cfg, catalog, "SELECT DISTINCT delivery_date FROM test_shapes.daily ORDER BY 1") == [
        ['2026-03-30'], ['2026-03-31'], ['2026-04-01'], ['2026-04-02']]
    assert rows(cfg, catalog, "SELECT DISTINCT delivery_month FROM test_shapes.monthly ORDER BY 1") == [
        ['2026-03-01'], ['2026-04-01']]
    assert rows(cfg, catalog, "SELECT count(*) FROM test_shapes.prices") == [[3 * 96 * 2]]
    assert files(cfg, "prices") == ["2026-03-30.parquet", "2026-03-31.parquet", "2026-04-01.parquet"]
    assert files(cfg, "monthly") == ["2026-03.parquet", "2026-04.parquet"]
    assert files(cfg, "daily") == ["2026-03.parquet", "2026-04.parquet"]
    assert files(cfg, "stations") == ["table.parquet"]


@pytest.mark.parametrize("start, end, month, day", [
    ("2026-03-31 21:00", "2026-03-31 22:00", "2026-03-01", "2026-03-31"),  # the last local hour of March
    ("2026-03-31 22:00", "2026-03-31 23:00", "2026-04-01", "2026-04-01"),  # the first local hour of April
])
def test_a_period_starts_at_midnight_in_the_zone_of_its_table(shapes, start, end, month, day):
    cfg, catalog, ds = shapes
    assert ingest.fetch_window(cfg, catalog, ds, t(start), t(end)).ok
    assert rows(cfg, catalog, "SELECT DISTINCT delivery_month FROM test_shapes.monthly") == [[month]]
    assert rows(cfg, catalog, "SELECT DISTINCT delivery_date FROM test_shapes.daily") == [[day]]


def test_a_table_without_a_time_column_is_replaced_whole(shapes, monkeypatch):
    cfg, catalog, ds = shapes
    w = (t("2026-03-30 00:00"), t("2026-03-30 01:00"))
    assert ingest.fetch_window(cfg, catalog, ds, *w).ok
    path = cfg.data_dir / "test_shapes" / "stations" / "table.parquet"
    before = path.stat().st_mtime_ns
    o = ingest.fetch_window(cfg, catalog, ds, *w)  # the same answer: nothing changes, the file is not written
    assert o.ok and o.rows_changed == 0 and path.stat().st_mtime_ns == before
    monkeypatch.setenv("ADELE_TEST_FAULT", "drop")
    o = ingest.fetch_window(cfg, catalog, ds, *w)
    assert o.ok and o.rows_changed == 1, o  # the station that the source dropped
    assert rows(cfg, catalog, "SELECT station FROM test_shapes.stations ORDER BY 1") == [["BAS"], ["PAY"]]
    monkeypatch.delenv("ADELE_TEST_FAULT")
    monkeypatch.setenv("ADELE_TEST_BUMP", "1")  # GVE comes back with another altitude
    o = ingest.fetch_window(cfg, catalog, ds, *w)
    assert o.ok
    assert rows(cfg, catalog, "SELECT station, altitude FROM test_shapes.stations ORDER BY 1") == [
        ["BAS", 316.0], ["GVE", 412.0], ["PAY", 490.0]]


def test_an_empty_answer_for_a_table_without_a_time_column_fails_and_writes_nothing(shapes, monkeypatch):
    cfg, catalog, ds = shapes
    assert ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 00:00"), t("2026-03-30 01:00")).ok
    monkeypatch.setenv("ADELE_TEST_FAULT", "empty_stations")
    o = ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 01:00"), t("2026-03-30 02:00"))
    assert not o.ok and "no row for this table without a time column" in o.error
    assert rows(cfg, catalog, "SELECT count(*) FROM test_shapes.stations") == [[3]]
    assert rows(cfg, catalog, "SELECT count(*) FROM test_shapes.prices") == [[4 * 2]]  # the second hour was not written


@pytest.mark.parametrize("fault, message", [
    ("midmonth", "delivery_month must be the first day of its month, got ['2026-03-15']"),  # the month that overlaps
    ("ts", "a calendar period is a date"),
])
def test_a_month_must_be_a_date_on_its_first_day(shapes, monkeypatch, fault, message):
    cfg, catalog, ds = shapes
    monkeypatch.setenv("ADELE_TEST_FAULT", fault)
    o = ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 00:00"), t("2026-03-30 01:00"))
    assert not o.ok and message in o.error, o.error


def test_the_checks_find_a_stored_month_that_is_not_on_its_first_day(shapes):
    cfg, catalog, ds = shapes
    assert ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 00:00"), t("2026-03-30 01:00")).ok
    con = duckdb.connect()
    con.execute(f"COPY (SELECT 'A' AS zone, DATE '2026-05-15' AS delivery_month, 1.0 AS energy_month) "
                f"TO '{cfg.data_dir / 'test_shapes' / 'monthly' / '2026-05.parquet'}' (FORMAT parquet)")
    problems = checks.run_checks(catalog, ds, cfg.data_dir, cfg.query)
    assert problems == ["test_shapes.monthly: 1 rows whose delivery_month is not the first day of its month"]


def test_the_join_printed_by_describe_counts_92_quarter_hours_on_the_day_of_the_time_change(shapes):
    cfg, catalog, ds = shapes
    assert ingest.fetch_window(cfg, catalog, ds, t("2026-03-28 00:00"), t("2026-03-30 00:00")).ok
    join = next(e["join"] for e in render.describe_dict(cfg, ds)["tables"] if e["table"] == "test_shapes.daily")
    expr = "date_trunc('day', u AT TIME ZONE 'Europe/Zurich') = delivery_date"
    assert expr in join
    on = expr.replace("u ", "p.delivery_start ").replace("= delivery_date", "= d.delivery_date")
    got = rows(cfg, catalog, f"""
        SELECT d.delivery_date, count(*) FROM test_shapes.daily d JOIN test_shapes.prices p
          ON p.zone = d.zone AND {on}
          AND p.delivery_start >= '2026-03-28' AND p.delivery_start < '2026-03-31'
        WHERE d.zone = 'A' AND d.delivery_date = '2026-03-29' GROUP BY 1""")
    assert got == [['2026-03-29', 92]]


def test_a_dataset_without_time_columns_needs_none_of_the_window(env):
    cfg, _, _ = env
    desc = yaml.safe_load(SHAPES)
    desc.update(name="test_register", resources=[_resource(desc, "stations")])
    fetch = SHAPES_FETCH.replace('return {"prices": prices, "daily": daily, "monthly": monthly, "stations": stations}',
                                 "return stations")
    catalog = add(cfg, "test_register", yaml.safe_dump(desc, sort_keys=False), fetch)
    ds = catalog["test_register"]
    o = ingest.scheduled_fetch(cfg, catalog, ds, t("2026-03-30 12:00"))
    assert o.ok and o.rows == 3 and o.problems == [], o
    line = next(ln for ln in render.render_list(cfg, catalog).splitlines() if ln.startswith("test_register"))
    assert line == "test_register | Synthetic table shapes | no time column | no time column, 3 rows | ok"
    card = render.describe_dict(cfg, ds)
    assert card["freshness"]["refresh"] == "every PT1H, each fetch replaces every table whole"
    entry = card["tables"][0]
    assert entry["coverage"].startswith("no time column: the whole table as the source delivers it; last changed 20")
    assert "resolution" not in entry
    assert entry["sample_rows"].splitlines()[0] == "station,altitude"
    assert render.query_footer(cfg, catalog, ["test_register"]).startswith(
        "-- test_register: units: altitude m. resolution: no time column. status ok")
    computed = render.merged_descriptor(cfg, ds)["adele"]["computed"]["tables"]["stations"]
    assert computed["rows"] == 3 and computed["last_changed_at"].endswith("Z") and "coverage" not in computed


def test_repartition_rewrites_the_date_tables_and_leaves_a_table_without_a_time_column(shapes):
    cfg, catalog, ds = shapes
    assert ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 00:00"), t("2026-04-02 00:00")).ok
    con = storage.connect()
    assert storage.repartition(con, cfg.data_dir, ds.tables["daily"], partition="day") == 4
    assert storage.repartition(con, cfg.data_dir, ds.tables["stations"]) == 0
    assert files(cfg, "daily") == ["2026-03-30.parquet", "2026-03-31.parquet", "2026-04-01.parquet", "2026-04-02.parquet"]
    assert files(cfg, "stations") == ["table.parquet"]


# --- what agents read ---------------------------------------------------------------------------

def test_list_describe_and_footer_show_each_shape(shapes):
    cfg, catalog, ds = shapes
    assert ingest.fetch_window(cfg, catalog, ds, t("2026-03-30 00:00"), t("2026-04-02 00:00")).ok
    line = next(ln for ln in render.render_list(cfg, catalog).splitlines() if ln.startswith("test_shapes"))
    assert line == ("test_shapes | Synthetic table shapes | PT15M, calendar day (Europe/Zurich), calendar month "
                    "(Europe/Zurich), no time column | 2026-03-30 00:00Z .. 2026-04-01 23:45Z; delivery_date "
                    "2026-03-30 .. 2026-04-02 (Europe/Zurich); delivery_month 2026-03 .. 2026-04 (Europe/Zurich) | ok")
    card = render.describe_dict(cfg, ds)
    assert card["freshness"]["refresh"] == ("every PT1H, window on delivery_start, delivery_date, delivery_month "
                                            "[last scheduled run - P3D, now + PT0S)")
    assert render.CONVENTIONS_PERIODS in card["conventions"] and render.CONVENTIONS_WHOLE in card["conventions"]
    by = {e["table"].split(".")[1]: e for e in card["tables"]}
    assert by["prices"]["resolution"] == ["PT15M from 2026-01-01"]
    assert by["monthly"]["coverage"] == "2026-03 .. 2026-04 (first and last delivery_month, in Europe/Zurich)"
    assert by["monthly"]["resolution"] == ("none: one row per calendar month in Europe/Zurich (delivery_month, "
                                           "stored as its first day)")
    assert by["monthly"]["timezone"] == "Europe/Zurich"
    assert "date_trunc('month', u AT TIME ZONE 'Europe/Zurich') = delivery_month" in by["monthly"]["join"]
    assert by["daily"]["coverage"] == "2026-03-30 .. 2026-04-02 (first and last delivery_date, in Europe/Zurich)"
    assert by["stations"]["coverage"].startswith("no time column")
    assert "2026-03-01" in by["monthly"]["sample_rows"]
    text = render.render_describe(cfg, ds)  # the card as YAML: the dates print as text
    assert "delivery_month 2026-03" not in text and "2026-03 .. 2026-04" in text
    footer = render.query_footer(cfg, catalog, ["test_shapes"])
    assert ("resolution: prices PT15M; daily calendar day in Europe/Zurich (delivery_date); monthly calendar month "
            "in Europe/Zurich (delivery_month); stations no time column.") in footer
    computed = render.merged_descriptor(cfg, ds)["adele"]["computed"]["tables"]
    assert computed["monthly"]["coverage"] == ["2026-03-01", "2026-04-01"]
    assert computed["monthly"]["resolution_periods"] == []
    json.dumps(render.merged_descriptor(cfg, ds), default=str)


# --- with the other revision policies ------------------------------------------------------------

def test_a_table_by_month_keeps_its_versions_when_append_only(env, monkeypatch):
    cfg, _, _ = env
    d = yaml.safe_load(SHAPES)
    d["adele"]["revisions"] = "append-only"
    d["resources"].remove(_resource(d, "stations"))
    fetch = SHAPES_FETCH.replace(', "stations": stations}', "}")
    catalog = add(cfg, "test_shapes", yaml.safe_dump(d, sort_keys=False), fetch)
    ds = catalog["test_shapes"]
    w = (t("2026-03-30 00:00"), t("2026-03-30 01:00"))
    assert ingest.fetch_window(cfg, catalog, ds, *w).ok
    monkeypatch.setenv("ADELE_TEST_BUMP", "5")
    o = ingest.fetch_window(cfg, catalog, ds, *w)
    assert o.ok and o.problems == [], o
    assert rows(cfg, catalog, "SELECT delivery_month, count(*) FROM test_shapes.monthly_versions WHERE zone = 'A' "
                              "GROUP BY 1") == [['2026-03-01', 2]]
    assert rows(cfg, catalog, "SELECT energy_month FROM test_shapes.monthly WHERE zone = 'A'") == [[705.0]]


RUNS_WITH_CELLS = """\
name: test_runs
title: Synthetic forecast runs and their grid cells
resources:
  - name: runs
    schema:
      primaryKey: [init_time, delivery_start]
      fields:
        - {name: init_time, type: datetime}
        - {name: delivery_start, type: datetime}
        - {name: value, type: number}
  - name: cells
    schema:
      primaryKey: [cell]
      fields:
        - {name: cell, type: string}
        - {name: seen, type: string}
adele:
  format_version: 2
  secrets: [ADELE_TEST_SKIP]
  refresh: {every: PT1H, lookback: PT12H, horizon: PT1H}
  revisions: none
  window: init_time
  partition: day
"""

# One run per hour; `cells` says in which window it was fetched. ADELE_TEST_SKIP: the hours left out.
RUNS_WITH_CELLS_FETCH = """\
import os

import pandas as pd

def fetch(start, end):
    skip = {int(h) for h in os.environ.get("ADELE_TEST_SKIP", "").split(",") if h}
    inits = [i for i in pd.date_range(start.replace(minute=0, second=0, microsecond=0), end, freq="h",
                                      inclusive="left", tz="UTC") if i >= start and i.hour not in skip]
    runs = pd.DataFrame([(i, i + pd.Timedelta(hours=1), 1.0) for i in inits],
                        columns=["init_time", "delivery_start", "value"]).astype(
        {"init_time": "datetime64[ns, UTC]", "delivery_start": "datetime64[ns, UTC]"})
    cells = pd.DataFrame({"cell": ["c1", "c2"], "seen": [start.isoformat()] * 2})
    return {"runs": runs, "cells": cells}
"""


def test_revisions_none_leaves_out_a_table_without_a_time_column(env, monkeypatch):
    cfg, _, _ = env
    catalog = add(cfg, "test_runs", RUNS_WITH_CELLS, RUNS_WITH_CELLS_FETCH)
    ds = catalog["test_runs"]
    monkeypatch.setenv("ADELE_TEST_SKIP", "1,3")
    assert ingest.fetch_window(cfg, catalog, ds, t("2026-03-01 00:00"), t("2026-03-01 05:00")).ok
    # the gaps between the stored runs (00, 02 and 04); the cells don't count as stored values of init_time
    eps = ingest.EPSILON
    assert ingest.windows_to_fetch(cfg.data_dir, ds, t("2026-03-01 00:00"), t("2026-03-01 05:00")) == [
        (t("2026-03-01 00:00") + eps, t("2026-03-01 02:00")), (t("2026-03-01 02:00") + eps, t("2026-03-01 04:00")),
        (t("2026-03-01 04:00") + eps, t("2026-03-01 05:00"))]
    monkeypatch.delenv("ADELE_TEST_SKIP")
    o = ingest.fetch_window(cfg, catalog, ds, t("2026-03-01 00:00"), t("2026-03-01 05:00"))
    assert o.ok and o.windows_fetched == 3, o
    # three calls of fetch() in one child: the cells are those of the last window
    got = rows(cfg, catalog, "SELECT DISTINCT seen FROM test_runs.cells")
    assert got == [["2026-03-01T04:00:00.000001+00:00"]], got
    assert rows(cfg, catalog, "SELECT count(*) FROM test_runs.runs") == [[5]]


def test_the_real_descriptors_still_load():
    datasets = os.path.join(os.path.dirname(__file__), "..", "..", "datasets")
    from pathlib import Path
    catalog = load_catalog(Path(datasets))
    wx = catalog["weathernext3"]
    assert {t.window for t in wx.tables.values()} == {"init_time"}
    assert wx.tables["solar_radiation"].resolution == [{"from": dt.date(2024, 1, 1), "value": "PT1H"}]
    assert wx.tables["weather"].resolution == []
