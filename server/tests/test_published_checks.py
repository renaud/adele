"""checks.yaml: published figures that the data must reproduce, run after each fetch."""
from __future__ import annotations

import datetime as dt

import pytest
import yaml

from adele_server import ingest, render, state
from adele_server.catalog import CatalogError, load_catalog

UTC = dt.timezone.utc
JAN1, JAN3 = dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 3, tzinfo=UTC)

# Synthetic prices: zone A = hour of the day (0..23), so its mean over whole days is 11.5.
GOOD = {"name": "a_mean", "question": "Mean price of zone A?",
        "sql": "SELECT avg(price) FROM test_prices.prices WHERE zone = 'A'",
        "expected": 11.5, "tolerance": 0.01, "source": "Test report, https://example.org/report.pdf"}


def write_checks(cfg, entries):
    (cfg.datasets_dir / "test_prices" / "checks.yaml").write_text(yaml.safe_dump({"checks": entries}))
    return load_catalog(cfg.datasets_dir)


def fetch(cfg, catalog):
    return ingest.fetch_window(cfg, catalog, catalog["test_prices"], JAN1, JAN3)


def test_matching_figure_keeps_status_ok(env):
    cfg, _, _ = env
    catalog = write_checks(cfg, [GOOD])
    o = fetch(cfg, catalog)
    assert o.ok and o.problems == []
    st = state.load(cfg.data_dir, "test_prices")
    assert st["status"] == "ok"
    line = render.describe_dict(cfg, catalog["test_prices"])["published_figures"]
    assert line.startswith("1 figures published by Test report") and line.endswith("all match")


def test_figure_outside_tolerance_sets_failing(env):
    cfg, _, _ = env
    fetch(cfg, write_checks(cfg, [GOOD]))  # status ok first, so that the change raises an alert
    catalog = write_checks(cfg, [GOOD, {**GOOD, "name": "a_mean_wrong", "expected": 12.0}])
    o = fetch(cfg, catalog)
    assert o.ok  # the fetch worked; the data disagrees with a published figure
    st = state.load(cfg.data_dir, "test_prices")
    assert st["status"] == "failing"
    assert st["problems"] == ["check a_mean_wrong: got 11.5, published 12 (tolerance 0.01; Test report)"]
    assert render.describe_dict(cfg, catalog["test_prices"])["published_figures"].endswith("1 differ (a_mean_wrong)")
    assert "a_mean_wrong" in (cfg.log_dir / "alerts.log").read_text()


@pytest.mark.parametrize("sql, message", [
    ("SELECT avg(price) FROM test_prices.nope", "check broken fails: Catalog Error"),
    ("SELECT avg(price) FROM test_prices.prices WHERE false", "check broken returns None, not a number"),
    ("SELECT 'x'", "check broken returns 'x', not a number"),
    ("SELECT 1 WHERE false", "check broken returns no row"),
])
def test_broken_check_is_a_problem(env, sql, message):
    cfg, _, _ = env
    catalog = write_checks(cfg, [{**GOOD, "name": "broken", "sql": sql}])
    fetch(cfg, catalog)
    st = state.load(cfg.data_dir, "test_prices")
    assert st["status"] == "failing"
    assert st["problems"][0].startswith(message)


def test_describe_says_not_run_before_the_first_check(env):
    cfg, _, _ = env
    catalog = write_checks(cfg, [GOOD])
    assert render.describe_dict(cfg, catalog["test_prices"])["published_figures"].endswith("not run yet")


@pytest.mark.parametrize("entries, message", [
    ([{k: v for k, v in GOOD.items() if k != "source"}], r"missing \['source'\]"),
    ([GOOD, GOOD], "two checks are named 'a_mean'"),
    ([{**GOOD, "name": "A-mean"}], "name must match"),
    ([{**GOOD, "expected": "11.5"}], "expected must be a number"),
    ([{**GOOD, "tolerance": -1}], "tolerance must be >= 0"),
    ([{**GOOD, "unit": "EUR/MWh"}], r"unknown keys \['unit'\]"),
])
def test_invalid_checks_are_refused(env, entries, message):
    cfg, _, _ = env
    with pytest.raises(CatalogError, match=message):
        write_checks(cfg, entries)


def test_checks_yaml_must_hold_a_list(env):
    cfg, _, _ = env
    (cfg.datasets_dir / "test_prices" / "checks.yaml").write_text("a_mean: 11.5\n")
    with pytest.raises(CatalogError, match="list `checks`"):
        load_catalog(cfg.datasets_dir)
