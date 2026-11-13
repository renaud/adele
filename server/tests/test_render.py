"""Computed facts that agents read: resolution periods (with gaps), the describe card."""
from __future__ import annotations

import datetime as dt

import yaml

from adele_server import ingest, render

UTC = dt.timezone.utc


def test_gap_splits_resolution_periods(env):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    ingest.fetch_window(cfg, catalog, ds, dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 2, tzinfo=UTC))
    ingest.fetch_window(cfg, catalog, ds, dt.datetime(2026, 1, 5, tzinfo=UTC), dt.datetime(2026, 1, 6, tzinfo=UTC))
    card = yaml.safe_load(render.render_describe(cfg, ds))
    assert card["tables"][0]["resolution"][:2] == [
        "A: PT1H 2026-01-01 00:00Z .. 2026-01-01 23:00Z",
        "A: PT1H 2026-01-05 00:00Z .. 2026-01-05 23:00Z",
    ]


def test_quotes_are_not_doubled(env):
    cfg, catalog, _ = env
    text = render.render_describe(cfg, catalog["test_prices"])
    assert "''" not in text and "date_trunc('day'" in text
