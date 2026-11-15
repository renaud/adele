"""Tables of instants (valid_at), and the packaging rules: adele.format_version, adele.secrets, datasets_dirs."""
from __future__ import annotations

import datetime as dt
import shutil
import textwrap

import pytest

from adele_server import config as config_mod
from adele_server import ingest, render
from adele_server.catalog import CatalogError, load_catalog

UTC = dt.timezone.utc

FORECAST = """\
name: test_wx
title: Synthetic forecast with an interval table and an instant table
resources:
  - name: radiation
    schema:
      primaryKey: [init_time, delivery_start]
      fields:
        - {name: init_time, type: datetime}
        - {name: delivery_start, type: datetime}
        - {name: ssrd, type: number, unit: W/m2}
  - name: weather
    schema:
      primaryKey: [init_time, valid_at]
      fields:
        - {name: init_time, type: datetime}
        - {name: valid_at, type: datetime}
        - {name: cloud, type: number, unit: "1"}
adele:
  format_version: 1
  refresh: {every: PT1H, lookback: PT6H, horizon: PT1H}
  revisions: none
  window: init_time
  partition: day
  resolution: [{from: 2026-01-01, value: PT1H}]
"""

FORECAST_FETCH = """\
import pandas as pd

def fetch(start, end):
    inits = pd.date_range(start.replace(minute=0, second=0, microsecond=0), end, freq="h", inclusive="left", tz="UTC")
    inits = [i for i in inits if i >= start]
    h = pd.Timedelta(hours=1)
    rad = pd.DataFrame([(i, i + (lead - 1) * h, 100.0 * lead) for i in inits for lead in (1, 2)],
                       columns=["init_time", "delivery_start", "ssrd"])
    wx = pd.DataFrame([(i, i + lead * h, 0.25 * lead) for i in inits for lead in (1, 2)],
                      columns=["init_time", "valid_at", "cloud"])
    types = {"init_time": "datetime64[ns, UTC]"}
    return {"radiation": rad.astype({**types, "delivery_start": "datetime64[ns, UTC]", "ssrd": "float64"}),
            "weather": wx.astype({**types, "valid_at": "datetime64[ns, UTC]", "cloud": "float64"})}
"""


def t(h: float) -> dt.datetime:
    return dt.datetime(2026, 3, 1, tzinfo=UTC) + dt.timedelta(hours=h)


def add(cfg, name, descriptor, fetch):
    d = cfg.datasets_dir / name
    d.mkdir()
    (d / "datapackage.yaml").write_text(descriptor)
    (d / "fetch.py").write_text(fetch)
    return load_catalog(cfg.datasets_dirs)


# --- instants -------------------------------------------------------------------------------

def test_instant_table_is_stored_and_described(env):
    cfg, _, _ = env
    catalog = add(cfg, "test_wx", FORECAST, FORECAST_FETCH)
    ds = catalog["test_wx"]
    assert [tb.time_field for tb in ds.tables.values()] == ["delivery_start", "valid_at"]
    o = ingest.fetch_window(cfg, catalog, ds, t(0), t(3))
    assert o.ok and o.rows == 12 and o.problems == [], (o.error, o.problems)
    card = render.describe_dict(cfg, ds)
    assert "A table with valid_at instead of delivery_start holds values at an instant" in card["conventions"]
    wx = card["tables"][1]
    assert wx["resolution"] == "none: values at instants (valid_at)"
    assert wx["coverage"] == "2026-03-01 01:00Z .. 2026-03-01 04:00Z (first and last valid_at)"
    assert card["tables"][0]["resolution"] == ["PT1H from 2026-01-01"]
    line = next(ln for ln in render.render_list(cfg, catalog).splitlines() if ln.startswith("test_wx"))
    assert "| PT1H, instants |" in line
    footer = render.query_footer(cfg, catalog, ["test_wx"])
    assert "resolution: radiation PT1H; weather instants (valid_at)." in footer
    # a dataset without instants keeps the short conventions
    assert "valid_at" not in render.describe_dict(cfg, catalog["test_prices"])["conventions"]


def test_a_run_counts_as_stored_only_when_every_table_has_it(env):
    cfg, _, _ = env
    catalog = add(cfg, "test_wx", FORECAST, FORECAST_FETCH)
    ds = catalog["test_wx"]
    ingest.fetch_window(cfg, catalog, ds, t(0), t(3))
    shutil.rmtree(cfg.data_dir / "test_wx" / "weather")  # runs stored without their instants
    assert ingest.windows_to_fetch(cfg.data_dir, ds, t(0), t(3)) == [(t(0), t(3))]
    o = ingest.fetch_window(cfg, catalog, ds, t(0), t(3))
    assert o.ok and o.rows == 12 and o.rows_changed == 6, o.error  # the radiation rows were equal


@pytest.mark.parametrize("fields, message", [
    ("- {name: init_time, type: datetime}\n        - {name: cloud, type: number}", "one time field"),
    ("- {name: init_time, type: datetime}\n        - {name: valid_at, type: datetime}\n"
     "        - {name: delivery_start, type: datetime}", "one time field"),
    ("- {name: init_time, type: datetime}\n        - {name: valid_at, type: date}", "'valid_at' must have type datetime"),
])
def test_a_table_needs_exactly_one_time_field(env, fields, message):
    cfg, _, _ = env
    desc = FORECAST.replace(
        "- {name: init_time, type: datetime}\n        - {name: valid_at, type: datetime}\n"
        "        - {name: cloud, type: number, unit: \"1\"}", fields).replace("[init_time, valid_at]", "[init_time]")
    with pytest.raises(CatalogError, match=message):
        add(cfg, "test_wx", desc, FORECAST_FETCH)


# --- adele.format_version ----------------------------------------------------------------------

@pytest.mark.parametrize("line, message", [("", "adele.format_version is missing"), ("  format_version: 3\n", "adele.format_version 3 is unknown")])
def test_format_is_required_and_known(env, line, message):
    cfg, _, _ = env
    desc = FORECAST.replace("  format_version: 1\n", line)
    with pytest.raises(CatalogError, match=message):
        add(cfg, "test_wx", desc, FORECAST_FETCH)


# --- adele.secrets --------------------------------------------------------------------------

def test_a_fetch_gets_only_its_declared_secrets(env, monkeypatch):
    cfg, catalog, _ = env
    monkeypatch.setenv("TEST_OTHER_TOKEN", "not for this dataset")
    monkeypatch.setenv("ADELE_TEST_BUMP", "0")
    monkeypatch.setenv("ADELE_TEST_FAULT", "env")
    o = ingest.fetch_window(cfg, catalog, catalog["test_prices"], t(0), t(2))
    assert not o.ok and "env: ADELE_TEST_BUMP,ADELE_TEST_FAULT" in o.error  # declared; TEST_OTHER_TOKEN not passed


def test_secrets_must_be_variable_names(env):
    cfg, _, _ = env
    with pytest.raises(CatalogError, match="adele.secrets"):
        add(cfg, "test_wx", FORECAST.replace("  format_version: 1\n", "  format_version: 1\n  secrets: [entso-token]\n"), FORECAST_FETCH)


# --- datasets_dirs --------------------------------------------------------------------------

def _config(tmp_path, body):
    (tmp_path / "multi.toml").write_text(textwrap.dedent(body) + 'data_dir = "data"\n[keys]\nk = "secret-key-1"\n')
    return config_mod.load(tmp_path / "multi.toml")


def test_datasets_dirs_mix_folders_of_datasets_and_single_datasets(env, tmp_path):
    cfg, _, _ = env
    repo = tmp_path / "adele-dataset-wx"  # a dataset's own repository: its folder name is free
    repo.mkdir()
    (repo / "datapackage.yaml").write_text(FORECAST)
    (repo / "fetch.py").write_text(FORECAST_FETCH)
    multi = _config(tmp_path, 'datasets_dirs = ["datasets", "adele-dataset-wx"]\n')
    assert multi.datasets_dirs == [cfg.datasets_dir, repo.resolve()]
    assert sorted(load_catalog(multi.datasets_dirs)) == ["test_prices", "test_wx"]


def test_a_dataset_defined_twice_is_an_error(env, tmp_path):
    cfg, _, _ = env
    other = tmp_path / "other"
    shutil.copytree(cfg.datasets_dir / "test_prices", other / "test_prices")
    with pytest.raises(CatalogError, match="'test_prices' is defined twice"):
        load_catalog([cfg.datasets_dir, other])


def test_datasets_dir_and_datasets_dirs_are_exclusive(tmp_path):
    with pytest.raises(SystemExit, match="not both"):
        _config(tmp_path, 'datasets_dir = "a"\ndatasets_dirs = ["b"]\n')
    assert _config(tmp_path, 'datasets_dir = "a"\n').datasets_dirs == [(tmp_path / "a").resolve()]
