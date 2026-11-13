"""Fetch --> checks --> merge --> state; the three faults of POC step 6, and more."""
from __future__ import annotations

import datetime as dt

import duckdb
import pytest

from adele_server import ingest, state

UTC = dt.timezone.utc
JAN1, JAN3 = dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 3, tzinfo=UTC)


def stored(cfg, sql="SELECT count(*) FROM t"):
    con = duckdb.connect()
    con.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{cfg.data_dir}/test_prices/prices/*.parquet')")
    return con.execute(sql).fetchall()


def fetch(env, start=JAN1, end=JAN3):
    cfg, catalog, _ = env
    return ingest.fetch_window(cfg, catalog, catalog["test_prices"], start, end)


def test_fetch_stores_and_is_idempotent(env):
    cfg, _, _ = env
    o = fetch(env)
    assert o.ok and o.rows == 96 and o.rows_changed == 96 and o.problems == []
    assert state.load(cfg.data_dir, "test_prices")["status"] == "ok"
    o2 = fetch(env)
    assert o2.ok and o2.rows_changed == 0 and o2.months_written == 0
    assert stored(cfg) == [(96,)]


def test_window_is_half_open_and_partitioned_by_month(env):
    cfg, _, _ = env
    fetch(env, dt.datetime(2026, 1, 31, 22, tzinfo=UTC), dt.datetime(2026, 2, 1, 2, tzinfo=UTC))
    files = sorted(p.name for p in (cfg.data_dir / "test_prices" / "prices").glob("*.parquet"))
    assert files == ["2026-01.parquet", "2026-02.parquet"]
    assert stored(cfg, "SELECT min(delivery_start), max(delivery_start), count(*) FROM t")[0][2] == 8


def test_revision_overwrites(env, monkeypatch):
    cfg, _, _ = env
    fetch(env)
    monkeypatch.setenv("ADELE_TEST_BUMP", "100")
    o = fetch(env, JAN1, dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert o.rows_changed == 48
    assert stored(cfg, "SELECT count(*), count(*) FILTER (WHERE price >= 100) FROM t") == [(96, 48)]


@pytest.mark.parametrize("fault, message", [
    ("dup", "duplicates"),
    ("undeclared", "not declared in categories"),
    ("rename", "columns differ"),
    ("naive", "timezone-aware"),
    ("error", "source down"),
])
def test_faults_set_failing_and_keep_the_data(env, monkeypatch, fault, message):
    cfg, _, _ = env
    fetch(env)
    before = stored(cfg, "SELECT * FROM t ORDER BY ALL")
    monkeypatch.setenv("ADELE_TEST_FAULT", fault)
    o = fetch(env)
    assert not o.ok and message in o.error
    st = state.load(cfg.data_dir, "test_prices")
    assert st["status"] == "failing" and message in st["problems"][0]
    assert stored(cfg, "SELECT * FROM t ORDER BY ALL") == before
    monkeypatch.delenv("ADELE_TEST_FAULT")
    assert fetch(env).ok
    assert state.load(cfg.data_dir, "test_prices")["status"] == "ok"
    alerts = (cfg.log_dir / "alerts.log").read_text().splitlines()
    assert [a.split(": ", 1)[1].split(" |")[0] for a in alerts] == [
        "failing --> ok", "ok --> failing", "failing --> ok"]


def test_failing_example_sets_failing(env):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    ds.descriptor["adele"]["examples"].append({"question": "broken", "sql": "SELECT nope FROM test_prices.prices"})
    o = fetch(env)
    assert o.ok and any("broken" in p for p in o.problems)
    assert state.load(cfg.data_dir, "test_prices")["status"] == "failing"


def test_due(env):
    cfg, catalog, _ = env
    ds = catalog["test_prices"]
    now = state.now()
    assert ingest.is_due(ds, {}, now)
    assert not ingest.is_due(ds, {"last_attempt_at": now}, now)
    assert ingest.is_due(ds, {"last_attempt_at": now - dt.timedelta(hours=1)}, now)


def test_hung_fetch_is_stopped(env, monkeypatch):
    cfg, _, _ = env
    fetch(env)
    cfg.fetch_timeout_s = 3
    monkeypatch.setenv("ADELE_TEST_FAULT", "hang")
    o = fetch(env)
    assert not o.ok and "time limit" in o.error
    assert state.load(cfg.data_dir, "test_prices")["status"] == "failing"
    monkeypatch.delenv("ADELE_TEST_FAULT")
    assert fetch(env).ok  # the lock was released
