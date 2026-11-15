"""End to end: the real HTTP server and the real client library and CLI (D5: client by path)."""
from __future__ import annotations

import datetime as dt
import socket
import threading
import time

import pytest
import uvicorn
import yaml

import adele
from adele import cli as adele_cli
from adele_server import ingest
from adele_server.app import create_app

UTC = dt.timezone.utc


@pytest.fixture
def server(env, monkeypatch):
    cfg, catalog, key = env
    ingest.fetch_window(cfg, catalog, catalog["test_prices"], dt.datetime(2026, 1, 1, tzinfo=UTC),
                        dt.datetime(2026, 1, 3, tzinfo=UTC))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg, catalog), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    monkeypatch.setenv("ADELE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("ADELE_API_KEY", key)
    yield cfg
    srv.should_exit = True
    th.join(timeout=5)


def test_list(server):
    out = adele.datasets()
    assert out.splitlines()[1] == (
        "test_prices | Synthetic prices | PT1H | 2026-01-01 00:00Z .. 2026-01-02 23:00Z | ok")


def test_describe(server):
    card = yaml.safe_load(adele.describe("test_prices"))
    tbl = card["tables"][0]
    assert tbl["table"] == "test_prices.prices"
    assert tbl["grain"] == "one row per (zone, delivery_start)"
    assert tbl["rows"] == 96
    assert tbl["resolution"] == ["A: PT1H 2026-01-01 00:00Z .. 2026-01-02 23:00Z",
                                 "B: PT1H 2026-01-01 00:00Z .. 2026-01-02 23:00Z"]
    price = next(f for f in tbl["fields"] if f["name"] == "price")
    assert price == {"name": "price", "type": "number (DOUBLE)", "unit": "EUR/MWh"}
    assert len(tbl["sample_rows"].splitlines()) == 6
    assert card["warnings"] == ["Synthetic data, do not use."]
    assert card["status"] == "ok"


def test_describe_unknown_dataset_suggests(server):
    with pytest.raises(adele.AdeleError, match="Did you mean test_prices"):
        adele.describe("test_price")


def test_query_rows_cap_and_footer(server):
    r = adele.query("SELECT * FROM test_prices.prices ORDER BY delivery_start, zone")
    assert r.total == 96 and r.truncated and len(r.rows) == 10
    text = str(r)
    assert text.startswith("zone,delivery_start,resolution,price\nA,2026-01-01 00:00:00Z,PT1H,0.0\n")
    assert "-- showing 10 of 96 rows." in text
    assert "-- test_prices: units: price EUR/MWh. resolution: A PT1H; B PT1H. status ok" in text
    assert "-- warning (test_prices): Synthetic data, do not use." in text


def test_query_error_and_log(server):
    with pytest.raises(adele.AdeleError, match="only SELECT statements"):
        adele.query("COPY test_prices.prices TO 'x.csv'")
    log = (server.log_dir / "queries.jsonl").read_text().splitlines()
    assert '"key": "tester"' in log[-1] and "COPY" in log[-1]


def test_bad_key(server, monkeypatch):
    monkeypatch.setenv("ADELE_API_KEY", "wrong")
    with pytest.raises(adele.AdeleError, match="unknown API key"):
        adele.datasets()


def test_cli(server, capsys):
    assert adele_cli.main(["query", "SELECT count(*) AS n FROM test_prices.prices"]) == 0
    assert capsys.readouterr().out.startswith("n\n96\n")
    assert adele_cli.main(["describe", "nope"]) == 1


def test_cli_as_of_reaches_the_server(server, capsys):
    # test_prices keeps only the latest values: the server refuses as_of (D30), and says why.
    assert adele_cli.main(["query", "--as-of", "2026-01-02", "SELECT count(*) FROM test_prices.prices"]) == 1
    assert "as_of applies only to append-only datasets" in capsys.readouterr().err
    assert adele_cli.main(["query", "--as-of", "soon", "SELECT 1"]) == 1
    assert "ISO 8601" in capsys.readouterr().err
    log = (server.log_dir / "queries.jsonl").read_text().splitlines()
    assert '"as_of": "soon"' in log[-1]
