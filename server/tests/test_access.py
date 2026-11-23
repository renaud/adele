"""Access from outside (D35): limits on queries, the client's rules on URLs, HTTPS with adele's own root certificate."""
from __future__ import annotations

import http.server
import shutil
import socket
import subprocess
import threading
import time

import duckdb
import pytest
import uvicorn

import adele
from adele import _api
from adele_server import checks, engine
from adele_server import config as config_mod
from adele_server.app import create_app
from adele_server.config import QueryLimits


def serve(app, **kw):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", **kw))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    return srv, th, port


@pytest.fixture
def start(env, monkeypatch):
    cfg, catalog, key = env
    running = []

    def go(**kw):
        srv, th, port = serve(create_app(cfg, catalog), **kw)
        running.append((srv, th))
        monkeypatch.setenv("ADELE_URL", f"http{'s' if kw else ''}://127.0.0.1:{port}")
        monkeypatch.setenv("ADELE_API_KEY", key)
        return cfg

    yield go
    for srv, th in running:
        srv.should_exit = True
        th.join(timeout=5)


# limits


def test_default_limits(tmp_path):
    (tmp_path / "c.toml").write_text('datasets_dirs = ["d"]\ndata_dir = "data"\n')
    cfg = config_mod.load(tmp_path / "c.toml")
    assert (cfg.query.max_rows, cfg.query.memory_limit, cfg.query.temp_limit) == (1000, "1GB", "2GB")
    assert (cfg.query.max_concurrent, cfg.query.timeout_s + cfg.query.max_wait_s < _api.TIMEOUT_S) == (2, True)
    assert (cfg.checks.memory_limit, cfg.checks.temp_limit) == ("2GB", None)


def test_limits_of_agents_do_not_apply_to_the_checks(tmp_path):
    (tmp_path / "c.toml").write_text('datasets_dirs = ["d"]\ndata_dir = "data"\n[query]\nmemory_limit = "10MB"\n'
                                     '[checks]\ntimeout_s = 7\n')
    cfg = config_mod.load(tmp_path / "c.toml")
    assert cfg.query.memory_limit == "10MB"
    assert (cfg.checks.memory_limit, cfg.checks.timeout_s, cfg.checks.temp_limit) == ("2GB", 7, None)


def test_the_checks_after_a_fetch_get_their_own_limits(env, monkeypatch):
    import datetime as dt

    from adele_server import ingest
    cfg, catalog, _ = env
    seen = []
    real = checks.run_checks
    monkeypatch.setattr(checks, "run_checks", lambda c, d, p, limits: seen.append(limits) or real(c, d, p, limits))
    day = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    ingest.fetch_window(cfg, catalog, catalog["test_prices"], day, day + dt.timedelta(days=1))
    assert seen == [cfg.checks] and seen[0] is not cfg.query


def test_temporary_files_are_limited(env, tmp_path, monkeypatch):
    cfg, catalog, _ = env
    monkeypatch.chdir(tmp_path)  # DuckDB writes .tmp in the working directory
    sql = "SELECT count(*) FROM (SELECT DISTINCT hash(i), hash(i + 1), hash(i + 2) FROM range(6000000) t(i))"
    wide = QueryLimits(memory_limit="100MB", temp_limit=None, threads=2)
    assert engine.run(catalog, cfg.data_dir, wide, sql).rows == [[6000000]]  # it fits when it may write to disk
    narrow = QueryLimits(memory_limit="100MB", temp_limit="20MB", threads=2)
    with pytest.raises(engine.QueryError, match="memory limit .100MB and 20MB of temporary files"):
        engine.run(catalog, cfg.data_dir, narrow, sql)


def test_a_query_cannot_lift_the_limit_on_temporary_files(env):
    cfg, catalog, _ = env
    con = engine.connect(catalog, cfg.data_dir, QueryLimits(temp_limit="20MB"))
    with pytest.raises(duckdb.Error, match="locked"):
        con.execute("SET max_temp_directory_size = '1TB'")
    con.close()


@pytest.fixture
def held(monkeypatch):
    """engine.run that holds until released, and counts how many run at once."""
    release, lock, now, peak = threading.Event(), threading.Lock(), [0], [0]
    real = engine.run

    def run(*a, **kw):
        with lock:
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        try:
            release.wait(10)
            return real(*a, **kw)
        finally:
            with lock:
                now[0] -= 1

    monkeypatch.setattr(engine, "run", run)
    return release, now, peak


def ask(n):
    out: list = [None] * n

    def one(i):
        try:
            out[i] = adele.query("SELECT 1 AS x").rows
        except adele.AdeleError as e:
            out[i] = str(e)

    ths = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for th in ths:
        th.start()
    return out, ths


def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    assert cond()


def test_queries_wait_for_a_slot(start, held):
    release, now, peak = held
    start()
    out, ths = ask(5)
    wait_for(lambda: now[0] == 2)
    time.sleep(0.5)
    assert now[0] == 2  # the three others wait
    assert adele.datasets().startswith("id | title")  # list doesn't wait
    release.set()
    for th in ths:
        th.join(10)
    assert out == [[[1]]] * 5 and peak[0] == 2


def test_a_query_that_waits_too_long_is_told_that_the_server_is_busy(start, held, env):
    release, now, _ = held
    cfg = env[0]
    cfg.query.max_wait_s = 0.3
    start()
    out, ths = ask(2)
    wait_for(lambda: now[0] == 2)
    with pytest.raises(adele.AdeleError, match="server is busy"):
        adele.query("SELECT 1")
    release.set()
    for th in ths:
        th.join(10)
    assert out == [[[1]]] * 2
    assert adele.query("SELECT 1 AS x").rows == [[1]]  # the slots are free again
    log = (cfg.log_dir / "queries.jsonl").read_text()
    assert '"error": "the server is busy' in log and '"waited_ms"' in log


def test_a_query_that_fails_gives_its_slot_back(start):
    start()
    for _ in range(5):
        with pytest.raises(adele.AdeleError, match="only SELECT"):
            adele.query("CREATE TABLE x(i int)")
    assert adele.query("SELECT 1 AS x").rows == [[1]]


# the client's rules on URLs


@pytest.mark.parametrize("url", ["http://example.org", "http://192.0.2.1:8443", "example.org:8443", "example.org",
                                 "ftp://example.org", "https://", "http://localhost.example.org", "http://[::1"])
def test_the_client_refuses_a_url_that_would_send_the_key_unencrypted(monkeypatch, url):
    monkeypatch.setenv("ADELE_URL", url)
    monkeypatch.setenv("ADELE_API_KEY", "k")
    monkeypatch.setattr(_api, "_opener", lambda: pytest.fail("a connection was opened"))
    with pytest.raises(adele.AdeleError, match="must start with https://"):
        adele.datasets()


@pytest.mark.parametrize("url", ["https://example.org:8443", "http://localhost:8000", "http://127.0.0.1:8000",
                                 "http://[::1]:8000"])
def test_the_client_accepts_https_and_this_machine(url):
    _api._check_url(url)


def test_the_client_does_not_follow_a_redirect(monkeypatch):
    seen = []

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ADELE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("ADELE_API_KEY", "k")
    with pytest.raises(adele.AdeleError, match="redirects to /elsewhere"):
        adele.datasets()
    srv.shutdown()
    srv.server_close()
    assert seen == ["/datasets"]


# HTTPS with adele's own authority


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    """Root, intermediate and leaf as Caddy's `tls internal` makes them: the leaf has no subject."""
    if not shutil.which("openssl"):
        pytest.skip("needs openssl")
    d = tmp_path_factory.mktemp("tls")

    def o(*args):
        subprocess.run(["openssl", *args], cwd=d, check=True, capture_output=True)

    ca = "basicConstraints=critical,CA:TRUE{}\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n"
    (d / "root.ext").write_text(ca.format(""))
    (d / "mid.ext").write_text(ca.format(",pathlen:0") + "authorityKeyIdentifier=keyid\n")
    (d / "leaf.ext").write_text("keyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth,clientAuth\n"
                                "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n"
                                "subjectAltName=critical,IP:127.0.0.1\n")
    (d / "req.cnf").write_text("[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=placeholder\n")
    for name in ("root", "mid", "leaf"):
        o("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", f"{name}.key")
        o("req", "-new", "-config", "req.cnf", "-key", f"{name}.key", "-out", f"{name}.csr",
          "-subj", "/" if name == "leaf" else f"/CN=adele test {name}")
    o("x509", "-req", "-in", "root.csr", "-signkey", "root.key", "-days", "2", "-extfile", "root.ext", "-out", "root.pem")
    o("x509", "-req", "-in", "mid.csr", "-CA", "root.pem", "-CAkey", "root.key", "-CAcreateserial", "-days", "2",
      "-extfile", "mid.ext", "-out", "mid.pem")
    o("x509", "-req", "-in", "leaf.csr", "-CA", "mid.pem", "-CAkey", "mid.key", "-CAcreateserial", "-days", "2",
      "-extfile", "leaf.ext", "-out", "leaf.pem")
    (d / "served.pem").write_text((d / "leaf.pem").read_text() + (d / "mid.pem").read_text())
    return d


def test_https_with_the_root_certificate_of_the_package(start, chain, monkeypatch):
    start(ssl_certfile=str(chain / "served.pem"), ssl_keyfile=str(chain / "leaf.key"))
    monkeypatch.setattr(_api, "CA_FILE", chain / "root.pem")
    assert adele.query("SELECT 1 AS x").rows == [[1]]


def test_https_without_it_is_refused(start, chain, monkeypatch, tmp_path):
    start(ssl_certfile=str(chain / "served.pem"), ssl_keyfile=str(chain / "leaf.key"))
    monkeypatch.setattr(_api, "CA_FILE", tmp_path / "absent.pem")
    with pytest.raises(adele.AdeleError, match="CERTIFICATE_VERIFY_FAILED"):
        adele.datasets()
