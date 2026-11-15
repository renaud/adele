"""The lockdown of agent SQL (SPEC.md, Security; TODOs.md, step 1)."""
from __future__ import annotations

import datetime as dt
import os
import shutil

import duckdb
import pytest

from adele_server import engine, ingest
from adele_server.catalog import load_catalog
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


def other_files(cfg):
    """Put in the data folder what a query must not reach; returns the folder of the table."""
    table = cfg.data_dir / "test_prices" / "prices"
    shutil.copytree(table, table.with_name("prices.old"))  # a sibling folder, as repartition makes
    (cfg.data_dir / "logs" / "queries.jsonl").write_text('{"key": "another member", "sql": "SELECT 1"}\n')
    os.symlink(cfg.data_dir / "logs" / "queries.jsonl", table / "link.txt")
    os.symlink(cfg.data_dir / "logs", table / "linkdir")
    os.symlink(cfg.data_dir, cfg.data_dir.parent / "data_link")
    for name in ("logs/alerts.log", "test_prices/state.json", "test_prices/.lock"):  # written by the fetch
        assert (cfg.data_dir / name).exists()
    return table


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_json('{data}/logs/queries.jsonl')",
    "SELECT * FROM read_csv('{data}/logs/queries.jsonl')",
    "SELECT * FROM read_text('{data}/logs/queries.jsonl')",
    "SELECT * FROM '{data}/logs/queries.jsonl'",
    "SELECT * FROM read_blob('{data}/logs/alerts.log')",
    "SELECT * FROM read_json('{data}/test_prices/state.json')",
    "SELECT * FROM read_blob('{data}/test_prices/.lock')",
    "SELECT * FROM glob('{data}/**')",
    "SELECT * FROM glob('{data}/test_prices/*')",
    "SELECT * FROM read_json('{table}/../state.json')",
    "SELECT * FROM read_text('{table}/../../logs/queries.jsonl')",
    "SELECT * FROM read_text('{table}/link.txt')",
    "SELECT * FROM read_text('{table}/linkdir/queries.jsonl')",
    "SELECT * FROM read_text('{root}/data_link/logs/queries.jsonl')",
    "SELECT * FROM read_parquet('{data}/test_prices/prices.old/*.parquet')",
    "DESCRIBE SELECT * FROM read_json('{data}/logs/queries.jsonl')",
])
def test_reads_in_the_data_folder_outside_the_tables_fail(loaded, sql):
    """The data folder also holds the query log of every member and a state file per dataset."""
    cfg, _ = loaded
    table = other_files(cfg)
    with pytest.raises(engine.QueryError, match="Permission"):
        run(loaded, sql.format(root=cfg.data_dir.parent, data=cfg.data_dir, table=table))
    assert run(loaded, "SELECT count(*) FROM test_prices.prices").rows == [[96]]


def test_files_of_a_table_answer_by_their_path(loaded):
    cfg, _ = loaded
    table = cfg.data_dir / "test_prices" / "prices"
    assert run(loaded, f"SELECT count(*) FROM read_parquet('{table}/2026-01.parquet')").rows == [[96]]
    assert run(loaded, f"SELECT count(*) FROM glob('{table}/*')").rows == [[1]]


def test_a_table_without_a_folder_still_answers(loaded):
    """A dataset that was never fetched has no folder: the lockdown lists it anyway, and the table is empty."""
    cfg, _ = loaded
    src, dst = cfg.datasets_dir / "test_prices", cfg.datasets_dir / "test_never"
    dst.mkdir()
    (dst / "datapackage.yaml").write_text((src / "datapackage.yaml").read_text().replace("test_prices", "test_never"))
    shutil.copy(src / "fetch.py", dst)
    both = cfg, load_catalog(cfg.datasets_dir)
    assert not (cfg.data_dir / "test_never").exists()
    r = run(both, "SELECT * FROM test_never.prices")
    assert (r.columns, r.rows, r.total) == (["zone", "delivery_start", "resolution", "price"], [], 0)
    assert r.types == ["VARCHAR", "TIMESTAMP WITH TIME ZONE", "INTERVAL", "DOUBLE"]
    counts = "SELECT (SELECT count(*) FROM test_prices.prices), (SELECT count(*) FROM test_never.prices)"
    assert run(both, counts).rows == [[96, 0]]
    with pytest.raises(engine.QueryError, match="Permission"):
        run(both, f"SELECT * FROM read_json('{cfg.data_dir}/test_prices/state.json')")


def test_tables_answer_through_symlinks(loaded):
    """The views name the folders as given, the lockdown lists them resolved: DuckDB resolves both."""
    cfg, catalog = loaded
    link = cfg.data_dir.parent / "data_link"
    os.symlink(cfg.data_dir, link)  # the data folder is a symlink
    assert engine.run(catalog, link, cfg.query, "SELECT count(*) FROM test_prices.prices").rows == [[96]]
    with pytest.raises(engine.QueryError, match="Permission"):
        engine.run(catalog, link, cfg.query, f"SELECT * FROM read_text('{link}/logs/alerts.log')")
    table = cfg.data_dir / "test_prices" / "prices"
    table.rename(cfg.data_dir.parent / "elsewhere")
    os.symlink(cfg.data_dir.parent / "elsewhere", table)  # the folder of a table is a symlink
    assert run(loaded, "SELECT count(*) FROM test_prices.prices").rows == [[96]]


@pytest.mark.parametrize("sql", [
    "COPY (SELECT 1 AS x) TO '{data}/test_prices/prices/2026-02.parquet'",
    "EXPORT DATABASE '{data}/exp'",
    "ATTACH '{data}/x.duckdb' AS x",
    "CREATE TABLE t AS SELECT 1",
    "DROP VIEW test_prices.prices",
    "INSTALL httpfs",
    "LOAD httpfs",
    "SET enable_external_access = true",
    "SET allowed_directories = ['{data}/']",
    "RESET allowed_directories",
    "RESET enable_external_access",
    "PRAGMA threads=64",
    "CALL pragma_version()",
    "SELECT 1; SELECT 2",
    "SELECT 1; COPY (SELECT 1 AS x) TO '{data}/test_prices/prices/2026-02.parquet'",
])
def test_writes_and_settings_are_refused(loaded, sql):
    cfg, _ = loaded
    before = sorted(p.relative_to(cfg.data_dir) for p in cfg.data_dir.rglob("*"))
    with pytest.raises(engine.QueryError):
        run(loaded, sql.format(data=cfg.data_dir))
    assert sorted(p.relative_to(cfg.data_dir) for p in cfg.data_dir.rglob("*")) == before


# DuckDB may write inside the folder of a table, and these statements are of type SELECT.
# Before the checks of engine.read_statement, a COPY in a CTE added a partition to the table.
COPY = "COPY (SELECT 1 AS x) TO '{table}/2031-01.parquet' (FORMAT parquet)"
SERIALIZED = "json_serialize_sql('WITH w AS (COPY (SELECT 1 AS x) TO ''{table}/2031-01.parquet'') SELECT 1')"
QUOTED = SERIALIZED.replace("'", "''")  # the same, inside a string


@pytest.mark.parametrize("sql", [
    # the body of a CTE can be a COPY, INSERT, UPDATE or DELETE
    "WITH w AS ({copy}) SELECT 1",
    "with w as (copy (select 1 as x) to '{table}/2031-01.parquet') select 1",
    "WITH w AS MATERIALIZED ({copy}) SELECT 1",
    "WITH a AS (SELECT 1), w AS ({copy}) SELECT * FROM a",
    "WITH a AS (WITH w AS ({copy}) SELECT 1) SELECT * FROM a",
    "SELECT * FROM (WITH w AS ({copy}) SELECT 1) s",
    "SELECT (WITH w AS ({copy}) SELECT 1)",
    "SELECT 1 UNION ALL (WITH w AS ({copy}) SELECT 1)",
    "DESCRIBE WITH w AS ({copy}) SELECT 1",
    "SUMMARIZE WITH w AS ({copy}) SELECT 1",
    "WITH w AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM w",
    "WITH w AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM w",
    "WITH w AS (DELETE FROM t RETURNING *) SELECT * FROM w",
    # table functions that run SQL given as data: the parse tree doesn't show what they run
    "SELECT * FROM json_execute_serialized_sql({serialized})",
    "SELECT * FROM system.main.\"JSON_EXECUTE_SERIALIZED_SQL\"({serialized})",
    "SELECT (SELECT count(*) FROM json_execute_serialized_sql({serialized}))",
    "SELECT * FROM range(3), LATERAL json_execute_serialized_sql({serialized})",
    "UNPIVOT json_execute_serialized_sql({serialized}) ON x",
    "SELECT * FROM query('SELECT * FROM json_execute' || '_serialized_sql({quoted})')",
    "SELECT * FROM destroy_external_resource('json_execute_serialized_sql', {serialized})",
    "SELECT * FROM destroy_external_resource('json_execute' || '_serialized_sql', {serialized})",
])
def test_a_query_cannot_write(loaded, sql):
    cfg, _ = loaded
    table = cfg.data_dir / "test_prices" / "prices"

    def files():
        return sorted((str(p.relative_to(cfg.data_dir)), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in cfg.data_dir.rglob("*") if p.is_file())

    before = files()
    with pytest.raises(engine.QueryError, match="read-only|is not allowed in queries"):
        run(loaded, sql.format(copy=COPY, serialized=SERIALIZED, quoted=QUOTED, table=table).format(table=table))
    assert files() == before
    assert run(loaded, "SELECT count(*) FROM test_prices.prices").rows == [[96]]


@pytest.mark.parametrize("sql", [
    "EXPLAIN SELECT count(*) FROM test_prices.prices",
    "explain analyze select count(*) from test_prices.prices",
    "EXPLAIN ANALYZE {copy}",
    "EXPLAIN /* why */ ANALYZE -- now\n {copy}",
    "EXPLAIN (ANALYZE, FORMAT json) {copy}",
    "EXPLAIN ANALYZE WITH w AS ({copy}) SELECT 1",
])
def test_explain_is_refused_and_writes_nothing(loaded, sql):
    """No EXPLAIN at all (D29). EXPLAIN ANALYZE runs the statement that follows it: before the
    checks, `EXPLAIN ANALYZE COPY ...` added a partition to the table."""
    cfg, _ = loaded
    table = cfg.data_dir / "test_prices" / "prices"

    def files():
        return sorted((str(p.relative_to(cfg.data_dir)), p.stat().st_size, p.stat().st_mtime_ns)
                      for p in cfg.data_dir.rglob("*") if p.is_file())

    before = files()
    with pytest.raises(engine.QueryError, match=r"only SELECT statements are allowed \(got EXPLAIN\)"):
        run(loaded, sql.format(copy=COPY).format(table=table))
    assert files() == before


@pytest.mark.parametrize("sql, rows", [
    ("WITH a AS (SELECT zone, avg(price) AS p FROM test_prices.prices GROUP BY zone) SELECT * FROM a ORDER BY zone",
     [["A", 11.5], ["B", 12.0]]),
    ("WITH a AS (WITH b AS (SELECT 1 AS x) SELECT * FROM b) SELECT * FROM a", [[1]]),
    ("WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r WHERE i < 5) SELECT sum(i) FROM r", [[15]]),
    ("FROM test_prices.prices SELECT count(*)", [[96]]),
    ("SELECT * FROM (SELECT zone, price FROM test_prices.prices) PIVOT (avg(price) FOR zone IN ('A', 'B'))",
     [[11.5, 12.0]]),
    ("UNPIVOT (SELECT 1 AS a, 2 AS b) ON a, b INTO NAME k VALUE v", [["a", 1], ["b", 2]]),
    ("SELECT zone, price FROM test_prices.prices QUALIFY row_number() OVER (PARTITION BY zone ORDER BY price DESC) = 1 "
     "ORDER BY zone", [["A", 23.0], ["B", 23.5]]),
    ("SELECT zone, price - lag(price) OVER w FROM test_prices.prices WINDOW w AS (PARTITION BY zone ORDER BY "
     "delivery_start) ORDER BY ALL LIMIT 1", [["A", -23.0]]),
    ("SELECT * EXCLUDE (resolution, delivery_start) FROM test_prices.prices ORDER BY ALL LIMIT 1", [["A", 0.0]]),
    ("(SELECT 1 EXCEPT SELECT 2) INTERSECT SELECT 1 UNION ALL SELECT 3", [[1], [3]]),
    ("SELECT sum(i) FROM range(10) t(i)", [[45]]),
    ("SELECT count(*) FROM generate_series(1, 3), unnest([1, 2])", [[6]]),
    ("SELECT table_schema, table_name FROM information_schema.tables", [["test_prices", "prices"]]),
    ("SELECT schema_name, view_name FROM duckdb_views() WHERE NOT internal", [["test_prices", "prices"]]),
    ("SHOW test_prices.prices", [["zone", "VARCHAR", "YES", None, None, None]]),
])
def test_usual_forms_of_a_select_still_answer(loaded, sql, rows):
    assert run(loaded, sql, max_rows=1 if sql.startswith("SHOW") else None).rows == rows


def test_a_statement_that_duckdb_cannot_serialize_is_refused(loaded):
    """Fail closed. With duckdb 2.0.0, every statement of type SELECT serializes; this one is not a SELECT."""
    cfg, catalog = loaded
    con = engine.connect(catalog, cfg.data_dir, cfg.query)
    with pytest.raises(engine.QueryError, match="can't be checked"):
        engine.read_only_tree(con, "COPY (SELECT 1 AS x) TO 'x.csv'")
    con.close()
    with pytest.raises(engine.QueryError, match="got MULTI.*For PIVOT"):
        run(loaded, "PIVOT test_prices.prices ON zone USING avg(price)")


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


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_json('{data}/logs/queries.jsonl')",
    "SELECT * FROM read_json('{data}/test_prices/state.json')",
    "SELECT * FROM glob('{data}/**')",
    "SELECT * FROM read_text('{table}/../state.json')",
    "SELECT * FROM read_text('{table}/link.txt')",
    "COPY (SELECT 1 AS x) TO '{data}/logs/queries.jsonl'",
    "COPY (SELECT 1 AS x) TO '{data}/test_prices/state.json'",
    "COPY (SELECT 1 AS x) TO '{data}/x.csv'",
    "COPY (SELECT 1 AS x) TO '{table}/../x.csv'",
    "EXPORT DATABASE '{data}/exp'",
    "ATTACH '{data}/x.duckdb' AS x",
    "ATTACH '{data}/logs/queries.jsonl' AS x",
    "SET allowed_directories = ['{data}/']",
    "RESET allowed_directories",
    "RESET enable_external_access",
    "SET lock_configuration = false",
])
def test_engine_settings_keep_the_log_and_the_state_out_of_reach(loaded, sql):
    """Without the statement filter: outside the folders of the tables, no read and no write."""
    cfg, catalog = loaded
    table = other_files(cfg)

    def content():
        return {p.relative_to(cfg.data_dir): p.read_bytes() for p in cfg.data_dir.rglob("*") if p.is_file()}

    before = content()
    con = engine.connect(catalog, cfg.data_dir, cfg.query)
    with pytest.raises(duckdb.Error, match="Permission|locked"):
        con.execute(sql.format(data=cfg.data_dir, table=table)).fetchall()
    con.close()
    assert content() == before


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
