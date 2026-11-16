"""`adele.window` (the time column of the fetch window and of the partitions), and fetch.py files
that declare their own dependencies (PEP 723), run by `uv run --script`."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sys
import textwrap
from urllib.parse import quote

import duckdb
import pytest

from adele_server import ingest, render, state
from adele_server.catalog import CatalogError, load_catalog

UTC = dt.timezone.utc

FORECASTS = """\
name: test_forecasts
title: Synthetic forecasts
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
  refresh: {every: PT1H, lookback: PT6H, horizon: PT1H}
  revisions: overwrite
  window: init_time
  resolution: [{from: 2026-01-01, value: PT1H}]
"""

# One run per hour, leads 1-3 h; one run before the window, which the server must drop.
FORECASTS_FETCH = """\
import pandas as pd

def fetch(start, end):
    inits = pd.date_range(start - pd.Timedelta(hours=1), end, freq="h", inclusive="left", tz="UTC")
    rows = [(i, i + pd.Timedelta(hours=lead - 1), float(lead)) for i in inits for lead in (1, 2, 3)]
    return pd.DataFrame(rows, columns=["init_time", "delivery_start", "value"])
"""

SCRIPT_FETCH = """\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import os
import time

import not_installed_in_the_server  # noqa: F401 - provided below, so that only the runner can import it


def fetch(start, end):
    import pandas as pd
    if os.environ.get("ADELE_TEST_FAULT") == "error":
        raise RuntimeError("source down")
    if os.environ.get("ADELE_TEST_FAULT") == "hang":
        time.sleep(60)
    idx = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    return pd.DataFrame({"zone": "A", "delivery_start": idx, "resolution": pd.Timedelta(hours=1),
                         "price": [float(t.hour) for t in idx]})
"""


def add_dataset(cfg, name, descriptor, fetch, extra=None):
    d = cfg.datasets_dir / name
    d.mkdir()
    (d / "datapackage.yaml").write_text(descriptor)
    (d / "fetch.py").write_text(fetch)
    for fname, text in (extra or {}).items():
        (d / fname).write_text(text)
    return load_catalog(cfg.datasets_dir)


def stored(cfg, ds, table, sql):
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{cfg.data_dir}/{ds}/{table}/*.parquet', filename = true)")
    return con.execute(sql).fetchall()


# --- adele.window ---------------------------------------------------------------------------

def test_window_on_init_time_filters_and_partitions_by_init_month(env):
    cfg, _, _ = env
    catalog = add_dataset(cfg, "test_forecasts", FORECASTS, FORECASTS_FETCH)
    ds = catalog["test_forecasts"]
    assert ds.window == "init_time"
    start, end = dt.datetime(2026, 1, 31, 22, tzinfo=UTC), dt.datetime(2026, 2, 1, 2, tzinfo=UTC)
    o = ingest.fetch_window(cfg, catalog, ds, start, end)
    assert o.ok and o.rows == 12, o.error  # runs 22, 23, 00, 01 (not 21) x 3 leads
    files = sorted(p.name for p in (cfg.data_dir / "test_forecasts" / "runs").glob("*.parquet"))
    assert files == ["2026-01.parquet", "2026-02.parquet"]
    # the run of 23:00 keeps its leads that deliver in February in the January file: whole runs per file
    rows = stored(cfg, "test_forecasts", "runs",
                  "SELECT strftime(init_time, '%H'), count(*), max(delivery_start)::VARCHAR, "
                  "parse_filename(filename) FROM t GROUP BY ALL ORDER BY min(init_time)")
    assert rows == [("22", 3, "2026-02-01 00:00:00+00", "2026-01.parquet"),
                    ("23", 3, "2026-02-01 01:00:00+00", "2026-01.parquet"),
                    ("00", 3, "2026-02-01 02:00:00+00", "2026-02.parquet"),
                    ("01", 3, "2026-02-01 03:00:00+00", "2026-02.parquet")]
    # list and describe show the range of the window column, not only of delivery_start
    line = next(ln for ln in render.render_list(cfg, catalog).splitlines() if ln.startswith("test_forecasts"))
    assert "| init_time 2026-01-31 22:00Z .. 2026-02-01 01:00Z |" in line and "PT1H" in line
    card = render.describe_dict(cfg, ds)
    assert card["tables"][0]["init_time coverage"] == "2026-01-31 22:00Z .. 2026-02-01 01:00Z (4 distinct values)"
    assert card["freshness"]["refresh"] == "every PT1H, window on init_time [last scheduled run - PT6H, now + PT1H)"


def test_window_on_delivery_start_is_the_default(env):
    _, catalog, _ = env
    assert catalog["test_prices"].window == "delivery_start"


@pytest.mark.parametrize("window", ["valid_time", "value"])
def test_window_must_be_a_datetime_in_the_key(env, window):
    cfg, _, _ = env
    with pytest.raises(CatalogError, match="adele.window"):
        add_dataset(cfg, "test_forecasts", FORECASTS.replace("window: init_time", f"window: {window}"),
                    FORECASTS_FETCH)


# --- fetch.py with inline dependencies (PEP 723) ---------------------------------------------

# Tests run offline. A stand-in `uv` runs the runner with the test interpreter (which has pandas
# and duckdb), so they test the protocol (arguments, Parquet out, errors, time limit), not uv's
# resolver. ADELE_TEST_UV=1 runs one test with the real uv (needs the network or a warm cache).
REAL_UV = os.environ.get("ADELE_TEST_UV") == "1"


@pytest.fixture
def script_env(env, monkeypatch, tmp_path):
    cfg, _, key = env
    # A module that the server can't import (it is not on the server's path) but the runner can.
    lib = tmp_path / "runner_lib"
    lib.mkdir()
    (lib / "not_installed_in_the_server.py").write_text("")
    monkeypatch.setenv("PYTHONPATH", str(lib))
    if not REAL_UV:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "uv"
        fake.write_text(f'#!/bin/sh\nwhile [ "$1" != "--script" ]; do shift; done\nshift\nexec {sys.executable} "$@"\n')
        fake.chmod(0o755)
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    descriptor = (cfg.datasets_dir / "test_prices" / "datapackage.yaml").read_text()
    shutil.rmtree(cfg.datasets_dir / "test_prices")
    descriptor = descriptor.replace("name: test_prices", "name: test_script").replace("test_prices.prices", "test_script.prices")
    catalog = add_dataset(cfg, "test_script", descriptor, SCRIPT_FETCH)
    return cfg, catalog


def test_catalog_does_not_import_a_script_fetch(script_env):
    _, catalog = script_env
    ds = catalog["test_script"]
    assert ds.fetch is None and ds.script_metadata == {"requires-python": ">=3.11", "dependencies": []}


def test_script_without_fetch_function_is_refused(env):
    cfg, _, _ = env
    with pytest.raises(CatalogError, match=r"must define fetch\(start, end\)"):
        add_dataset(cfg, "test_forecasts", FORECASTS, "# /// script\n# dependencies = []\n# ///\ndef get(a, b): pass\n")


def test_script_fetch_runs_through_uv_and_keeps_types(script_env):
    cfg, catalog = script_env
    ds = catalog["test_script"]
    o = ingest.fetch_window(cfg, catalog, ds, dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert o.ok, o.error
    assert o.rows == 24 and o.problems == []
    types = dict(stored(cfg, "test_script", "prices", "SELECT column_name, column_type FROM (DESCRIBE t)"))
    assert types["delivery_start"] == "TIMESTAMP WITH TIME ZONE" and types["resolution"] == "INTERVAL"


def test_script_fetch_error_sets_failing(script_env, monkeypatch):
    cfg, catalog = script_env
    monkeypatch.setenv("ADELE_TEST_FAULT", "error")
    o = ingest.fetch_window(cfg, catalog, catalog["test_script"], dt.datetime(2026, 1, 1, tzinfo=UTC),
                            dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert not o.ok and "exited with code 1" in o.error and "RuntimeError: source down" in o.error
    assert state.load(cfg.data_dir, "test_script")["status"] == "failing"


LEAKY_FETCH = """\
import os
from urllib.parse import quote


def fetch(start, end):
    token = os.environ["ADELE_TEST_BUMP"]
    print(f"GET https://source/api?securityToken={token}")
    raise RuntimeError(f"599 Server Error for url: https://source/api?securityToken={quote(token, safe='')}&x=1")
"""


def test_a_fetch_error_never_shows_a_secret(env, monkeypatch):
    cfg, _, _ = env
    token = "a1b2/c3d4+e5f6 g7"  # URL-encoded, it reads a1b2%2Fc3d4%2Be5f6%20g7
    monkeypatch.setenv("ADELE_TEST_BUMP", token)
    descriptor = (cfg.datasets_dir / "test_prices" / "datapackage.yaml").read_text()
    shutil.rmtree(cfg.datasets_dir / "test_prices")
    descriptor = descriptor.replace("name: test_prices", "name: test_leaky").replace("test_prices.prices", "test_leaky.prices")
    catalog = add_dataset(cfg, "test_leaky", descriptor, LEAKY_FETCH)
    o = ingest.fetch_window(cfg, catalog, catalog["test_leaky"], dt.datetime(2026, 1, 1, tzinfo=UTC),
                            dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert not o.ok and "599 Server Error" in o.error
    assert "securityToken=***ADELE_TEST_BUMP***&x=1" in o.error
    forms = (token, quote(token, safe=""), "a1b2", "c3d4")
    assert not any(f in o.error for f in forms)
    for p in cfg.data_dir.rglob("*"):  # state.json, alerts.log
        if p.is_file():
            assert not any(f in p.read_text(errors="replace") for f in forms), p


def test_script_fetch_is_stopped_at_the_time_limit(script_env, monkeypatch):
    cfg, catalog = script_env
    monkeypatch.setenv("ADELE_TEST_FAULT", "hang")
    cfg.fetch_timeout_s = 5
    t0 = dt.datetime.now()
    o = ingest.fetch_window(cfg, catalog, catalog["test_script"], dt.datetime(2026, 1, 1, tzinfo=UTC),
                            dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert (dt.datetime.now() - t0).total_seconds() < 20
    assert not o.ok and "time limit" in o.error


def test_runner_adds_its_own_dependencies_once():
    src = ingest.runner_source({"requires-python": ">=3.12", "dependencies": ["zarr>=3", "pandas==2.3.1"]})
    head = src.split("# ///\n", 1)[0]
    assert '# requires-python = ">=3.12"' in head
    assert '# dependencies = ["zarr>=3", "pandas==2.3.1", "duckdb>=2.0"]' in head
    assert textwrap.dedent(src).count("# /// script") == 1
