"""Computed facts that agents read: resolution periods, their gaps, the footer, the describe card."""
from __future__ import annotations

import datetime as dt

import pytest
import yaml

from adele_server import ingest, render

UTC = dt.timezone.utc


def test_the_card_counts_the_gaps_of_a_period(env):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    ingest.fetch_window(cfg, catalog, ds, dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 2, tzinfo=UTC))
    ingest.fetch_window(cfg, catalog, ds, dt.datetime(2026, 1, 5, tzinfo=UTC), dt.datetime(2026, 1, 6, tzinfo=UTC))
    card = yaml.safe_load(render.render_describe(cfg, ds))
    gap = "no rows from 2026-01-02 00:00Z until 2026-01-05 00:00Z"
    assert card["tables"][0]["resolution"] == [
        f"{z}: PT1H 2026-01-01 00:00Z .. 2026-01-05 23:00Z (1 gap: {gap})" for z in "AB"]
    ingest.fetch_window(cfg, catalog, ds, dt.datetime(2026, 1, 6, 6, tzinfo=UTC), dt.datetime(2026, 1, 7, tzinfo=UTC))
    card = yaml.safe_load(render.render_describe(cfg, ds))
    assert card["tables"][0]["resolution"][0] == ("A: PT1H 2026-01-01 00:00Z .. 2026-01-06 23:00Z (2 gaps, the longest "
                                                  "from 2026-01-02 00:00Z until 2026-01-05 00:00Z)")
    p = render.merged_descriptor(cfg, ds)["adele"]["computed"]["tables"]["prices"]["resolution_periods"][0]
    assert (p["gaps"], p["longest_gap"]) == (2, ["2026-01-02 00:00:00Z", "2026-01-05 00:00:00Z"])


def period(series, resolution, day=1):
    return {"series": series, "resolution": resolution, "first": dt.datetime(2026, 1, day, tzinfo=UTC)}


@pytest.mark.parametrize("periods, text", [
    ([], "not declared"),
    ([period("A", "PT1H")], "PT1H"),
    ([period("A", "PT1H"), period("B", "PT1H")], "PT1H"),
    ([period("A", "PT1H"), period("A", "PT15M", 5)], "PT1H, PT15M from 2026-01-05 00:00Z"),
    ([period("A", "PT1H"), period("B", "PT15M"), period("C", "PT1H")], "A, C: PT1H; B: PT15M"),
    ([period(z, "PT1H") for z in "ABCDE"] + [period("F", "PT15M")], "A, B, C and 2 more: PT1H; F: PT15M"),
    ([period("A", "PT1H" if d % 2 else "PT15M", d) for d in range(1, 8)], "PT15M and PT1H (6 changes, see the card)"),
    ([{"series": None, "resolution": "PT1H", "first": "2015-01-01", "last": None},
      {"series": None, "resolution": "PT15M", "first": "2025-10-01", "last": None}], "PT1H, PT15M from 2025-10-01"),
])
def test_the_footer_groups_the_series_that_share_a_resolution(periods, text):
    assert render.resolution_summary(periods) == text


def test_the_length_of_the_footer_does_not_depend_on_the_number_of_series():
    def footer(n):  # n series, each with its own date of change
        start = dt.datetime(2020, 1, 1, tzinfo=UTC)
        return render.resolution_summary([x for i in range(n) for x in (
            period(f"zone {i:05d}", "PT1H"),
            {**period(f"zone {i:05d}", "PT15M"), "first": start + dt.timedelta(days=i)})])
    assert len(footer(2000)) < 400 and footer(2000).endswith("; 1994 more series: see the card")


def test_quotes_are_not_doubled(env):
    cfg, catalog, _ = env
    text = render.render_describe(cfg, catalog["test_prices"])
    assert "''" not in text and "date_trunc('day'" in text
