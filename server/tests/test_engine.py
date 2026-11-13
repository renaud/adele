"""The lockdown of agent SQL (SPEC.md, Security; TODOs.md, step 1)."""
from __future__ import annotations

import datetime as dt
import os

import duckdb
import pytest

from adele_server import engine, ingest
from adele_server.config import QueryLimits

UTC = dt.timezone.utc


@pytest.fixture
def loaded(env):
    cfg, catalog, _ = env
    ingest.fetch_window(cfg, catalog, catalog["test_prices"], dt.datetime(2026, 1, 1, tzinfo=UTC),
                        dt.datetime(2026, 1, 3, tzinfo=UTC))
    return cfg, catalog


def run(loaded, sql, **kw):
    cfg, catalog = loaded
    return engine.run(catalog, cfg.data_dir, cfg.query, sql, **kw)


def test_select_and_cap(loaded):
    r = run(loaded, "SELECT * FROM test_prices.prices ORDER BY delivery_start, zone")
    assert r.columns == ["zone", "delivery_start", "resolution", "price"]
    assert len(r.rows) == 10 and r.truncated and r.total == 96
    assert r.rows[0] == ["A", "2026-01-01 00:00:00Z", "PT1H", 0.0]
    assert r.datasets == ["test_prices"]


def test_unqualified_name_error_names_the_table(loaded):
    with pytest.raises(engine.QueryError, match="test_prices.prices"):
        run(loaded, "SELECT * FROM prices")


def test_timestamp_literal_with_z_round_trips(loaded):
    r = run(loaded, "SELECT count(*) FROM test_prices.prices WHERE delivery_start = '2026-01-01 00:00:00Z'")
    assert r.rows == [[2]]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_text('{root}/secret.txt')",
    "SELECT * FROM read_text('{data}/../secret.txt')",
    "SELECT * FROM read_text('{data}/link.txt')",
    "SELECT * FROM glob('/*')",
    "SELECT * FROM read_parquet('https://example.com/x.parquet')",
])
def test_reads_outside_the_data_folder_fail(loaded, sql):
    cfg, _ = loaded
    os.symlink(cfg.data_dir.parent / "secret.txt", cfg.data_dir / "link.txt")
    with pytest.raises(engine.QueryError, match="Permission|disabled"):
        run(loaded, sql.format(root=cfg.data_dir.parent, data=cfg.data_dir))


@pytest.mark.parametrize("sql", [
    "COPY (SELECT 1 AS x) TO '{data}/test_prices/prices/2026-02.parquet'",
    "EXPORT DATABASE '{data}/exp'",
    "ATTACH '{data}/x.duckdb' AS x",
    "CREATE TABLE t AS SELECT 1",
    "DROP VIEW test_prices.prices",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET enable_external_access = true",
    "PRAGMA threads=64",
    "CALL pragma_version()",
    "SELECT 1; SELECT 2",
])
def test_writes_and_settings_are_refused(loaded, sql):
    cfg, _ = loaded
    before = sorted(p.relative_to(cfg.data_dir) for p in cfg.data_dir.rglob("*"))
    with pytest.raises(engine.QueryError):
        run(loaded, sql.format(data=cfg.data_dir))
    assert sorted(p.relative_to(cfg.data_dir) for p in cfg.data_dir.rglob("*")) == before


def test_engine_settings_hold_without_the_statement_filter(loaded):
    """The statement filter is the second layer; the engine settings must hold on their own."""
    cfg, catalog = loaded
    con = engine.connect(catalog, cfg.data_dir, cfg.query)
    with pytest.raises(duckdb.PermissionException):
        con.execute(f"SELECT * FROM read_text('{cfg.data_dir.parent}/secret.txt')").fetchall()
    with pytest.raises(duckdb.Error, match="locked"):
        con.execute("SET enable_external_access = true")
    with pytest.raises(duckdb.Error, match="locked"):
        con.execute("SET allowed_directories = ['/']")
    with pytest.raises(duckdb.Error):
        con.execute("LOAD httpfs")
    con.close()


def test_time_limit(loaded):
    cfg, catalog = loaded
    limits = QueryLimits(max_rows=10, timeout_s=0.5, memory_limit="500MB", threads=2)
    with pytest.raises(engine.QueryError, match="time limit"):
        engine.run(catalog, cfg.data_dir, limits, "SELECT sum(hash(i)) FROM range(100000000000) t(i)")


def test_memory_limit(loaded):
    cfg, catalog = loaded
    limits = QueryLimits(max_rows=10, timeout_s=20, memory_limit="100MB", threads=2)
    with pytest.raises(engine.QueryError, match="memory"):
        engine.run(catalog, cfg.data_dir, limits, "SELECT string_agg(repeat('x', 1000), '') FROM range(1000000)")


def test_describe_and_summarize_are_allowed(loaded):
    assert run(loaded, "DESCRIBE test_prices.prices").rows
    assert run(loaded, "SUMMARIZE test_prices.prices").rows


def test_iso_duration():
    assert engine.iso_duration(dt.timedelta(minutes=15)) == "PT15M"
    assert engine.iso_duration(dt.timedelta(days=1, hours=2)) == "P1DT2H"
    assert engine.iso_duration(dt.timedelta(0)) == "PT0S"
