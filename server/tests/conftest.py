"""A synthetic dataset `test_prices` (zones A and B, hourly) with faults switched on by env vars."""
from __future__ import annotations

import datetime as dt
import secrets
import textwrap
from pathlib import Path

import pytest

from adele_server import config as config_mod
from adele_server.catalog import load_catalog

UTC = dt.timezone.utc

DESCRIPTOR = """\
name: test_prices
title: Synthetic prices
resources:
  - name: prices
    schema:
      primaryKey: [zone, delivery_start]
      fields:
        - {name: zone, type: string, categories: [{value: A, label: Zone A}, {value: B, label: Zone B}]}
        - {name: delivery_start, type: datetime}
        - {name: resolution, type: duration}
        - {name: price, type: number, unit: EUR/MWh}
adele:
  format_version: 1
  secrets: [ADELE_TEST_FAULT, ADELE_TEST_BUMP]
  refresh: {every: PT1H, lookback: P1D, horizon: P1D}
  revisions: overwrite
  warnings: ["Synthetic data, do not use."]
  examples:
    - question: Average price per zone?
      sql: SELECT zone, avg(price) FROM test_prices.prices GROUP BY zone ORDER BY zone
"""

FETCH = '''\
import os
import time
import pandas as pd

def fetch(start, end):
    fault = os.environ.get("ADELE_TEST_FAULT", "")
    if fault == "error":
        raise RuntimeError("source down")
    if fault == "hang":
        time.sleep(60)
    if fault == "env":  # which variables did the fetch get?
        raise RuntimeError("env: " + ",".join(sorted(k for k in os.environ if k.startswith(("ADELE_", "TEST_")))))
    bump = float(os.environ.get("ADELE_TEST_BUMP", "0"))
    idx = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    zones = ["A", "B"] + (["Z"] if fault == "undeclared" else [])
    df = pd.DataFrame([(z, t, pd.Timedelta(hours=1), t.hour + (0.5 if z == "B" else 0.0) + bump)
                       for z in zones for t in idx], columns=["zone", "delivery_start", "resolution", "price"])
    if fault == "dup":
        df = pd.concat([df, df.iloc[:1]], ignore_index=True)
    if fault == "rename":
        df = df.rename(columns={"price": "price_eur"})
    if fault == "naive":
        df["delivery_start"] = df["delivery_start"].dt.tz_localize(None)
    return df
'''


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ADELE_TEST_FAULT", raising=False)
    monkeypatch.delenv("ADELE_TEST_BUMP", raising=False)
    ds = tmp_path / "datasets" / "test_prices"
    ds.mkdir(parents=True)
    (ds / "datapackage.yaml").write_text(DESCRIPTOR)
    (ds / "fetch.py").write_text(FETCH)
    (tmp_path / "secret.txt").write_text("TOP SECRET\n")
    key = secrets.token_urlsafe(16)
    (tmp_path / "adele-server.toml").write_text(textwrap.dedent(f"""\
        datasets_dir = "datasets"
        data_dir = "data"
        cache_dir = "cache"
        [query]
        max_rows = 10
        timeout_s = 5
        memory_limit = "500MB"
        threads = 2
        [keys]
        tester = "{key}"
        """))
    cfg = config_mod.load(tmp_path / "adele-server.toml")
    cfg.data_dir.mkdir()
    catalog = load_catalog(cfg.datasets_dir)
    return cfg, catalog, key


def t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)
