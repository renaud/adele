"""Raw answers (G4), whole files (G6) and the import of kept answers (WP4, D33), on synthetic data.

`test_raw` stands for a file that the source overwrites: download() yields the body that
ADELE_TEST_FILE holds, parse() reads it. ADELE_TEST_FAULT switches faults on.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import textwrap
from pathlib import Path

import pytest

from adele_server import engine, ingest, raw, render, state, storage
from adele_server.catalog import CatalogError, load_catalog, load_dataset

UTC = dt.timezone.utc

RAW = """\
name: test_raw
title: Synthetic file that overwrites itself
resources:
  - name: values
    schema:
      primaryKey: [delivery_start]
      fields:
        - {name: delivery_start, type: datetime}
        - {name: value, type: number, unit: MW}
adele:
  format_version: 1
  secrets: [ADELE_TEST_FILE, ADELE_TEST_FAULT]
  refresh: {every: PT1M, lookback: PT1H, horizon: PT0S}
  revisions: append-only
  raw: keep
"""

RAW_FETCH = '''\
import io
import os
import time

import pandas as pd


def download(start, end):
    fault = os.environ.get("ADELE_TEST_FAULT", "")
    body = os.environ.get("ADELE_TEST_FILE", "").encode()
    yield {"name": "values.csv", "url": "https://example.org/values.csv", "body": body}
    if fault == "two":
        yield {"name": "extra.csv", "url": "https://example.org/extra.csv", "body": b"something else"}
    if fault == "badname":
        yield {"name": "../escape.csv", "body": b"x"}
    if fault == "intname":
        yield {"name": 2026, "body": b"x"}
    if fault == "newline":
        yield {"name": "x.csv\\n", "body": b"x"}
    if fault == "hang":
        time.sleep(60)


def parse(answers):
    if os.environ.get("ADELE_TEST_FAULT") == "parse":
        raise ValueError("parser broken")
    frames = [pd.read_csv(io.BytesIO(a["body"])) for a in answers if a["name"] == "values.csv"]
    df = pd.concat(frames).drop_duplicates(subset=["delivery_start"], keep="last")
    df["delivery_start"] = pd.to_datetime(df["delivery_start"], utc=True)
    return df
'''


def body(*rows: tuple[str, float]) -> str:
    return "delivery_start,value\n" + "".join(f"{t},{v}\n" for t, v in rows)


A = body(("2026-03-01T10:00:00Z", 1.0), ("2026-03-01T10:05:00Z", 2.0))
B = body(("2026-03-01T10:15:00Z", 3.0), ("2026-03-01T10:20:00Z", 4.0))
W = (dt.datetime(2026, 3, 1, 9, tzinfo=UTC), dt.datetime(2026, 3, 1, 12, tzinfo=UTC))


@pytest.fixture
def rawenv(env, monkeypatch):
    cfg, _, key = env
    folder = cfg.datasets_dir / "test_raw"
    folder.mkdir()
    (folder / "datapackage.yaml").write_text(RAW)
    (folder / "fetch.py").write_text(RAW_FETCH)
    monkeypatch.delenv("ADELE_TEST_FAULT", raising=False)
    monkeypatch.setenv("ADELE_TEST_FILE", A)
    catalog = load_catalog(cfg.datasets_dir)
    return cfg, catalog, catalog["test_raw"]


def fetch(rawenv, window=W):
    cfg, catalog, ds = rawenv
    return ingest.fetch_window(cfg, catalog, ds, *window)


def kept(cfg) -> list[dict]:
    """The manifest lines of the archive, oldest first."""
    rows = []
    for m in sorted((cfg.data_dir / "test_raw" / "_raw").glob("*/manifest.csv")):
        with open(m, newline="") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def versions(rawenv) -> list[tuple]:
    cfg, _, ds = rawenv
    con = storage.connect()
    sql = storage.versions_sql(cfg.data_dir, ds.tables["values"])
    rows = con.execute(f"SELECT delivery_start, value, fetched_at FROM ({sql}) ORDER BY 1, 3").fetchall()
    con.close()
    return rows


# --- G4: an answer is kept before anything parses it ------------------------------------------

def test_an_answer_is_kept_as_received_and_parsed(rawenv):
    cfg, _, ds = rawenv
    o = fetch(rawenv)
    assert o.ok and (o.answers, o.answers_kept, o.rows) == (1, 1, 2)
    [line] = kept(cfg)
    assert line["name"] == "values.csv" and line["url"] == "https://example.org/values.csv"
    assert int(line["bytes"]) == len(A.encode())
    day = cfg.data_dir / "test_raw" / "_raw" / line["received_at"][:10]
    assert gzip.decompress((day / line["file"]).read_bytes()) == A.encode()
    assert line["file"].endswith("_values.csv.gz")


def test_a_scheduled_run_counts_the_answers(rawenv, monkeypatch):
    cfg, catalog, ds = rawenv
    now = dt.datetime(2026, 3, 1, 10, 30, tzinfo=UTC)
    o = ingest.scheduled_fetch(cfg, catalog, ds, now)
    assert o.ok and (o.answers, o.answers_kept) == (1, 1)


def test_an_answer_equal_to_the_last_kept_one_is_not_kept_again(rawenv, monkeypatch):
    cfg, _, _ = rawenv
    assert fetch(rawenv).answers_kept == 1
    o = fetch(rawenv)
    assert o.ok and (o.answers, o.answers_kept, o.rows_changed) == (1, 0, 0)
    monkeypatch.setenv("ADELE_TEST_FILE", B)
    assert fetch(rawenv).answers_kept == 1
    monkeypatch.setenv("ADELE_TEST_FILE", A)  # A --> B --> A: the source served the older file again
    assert fetch(rawenv).answers_kept == 1
    assert [r["sha256"] for r in kept(cfg)][0] == [r["sha256"] for r in kept(cfg)][2]
    assert len(kept(cfg)) == 3


def test_kept_when_the_parse_fails(rawenv, monkeypatch):
    cfg, _, _ = rawenv
    monkeypatch.setenv("ADELE_TEST_FAULT", "parse")
    o = fetch(rawenv)
    assert not o.ok and "parser broken" in o.error
    assert (o.answers, o.answers_kept) == (1, 1) and len(kept(cfg)) == 1
    assert state.load(cfg.data_dir, "test_raw")["status"] == "failing"


def test_kept_when_the_time_limit_stops_the_child(rawenv, monkeypatch):
    cfg, _, _ = rawenv
    cfg.fetch_timeout_s = 4
    monkeypatch.setenv("ADELE_TEST_FAULT", "hang")
    o = fetch(rawenv)
    assert not o.ok and "time limit" in o.error
    assert len(kept(cfg)) == 1


def test_kept_when_the_merge_fails(rawenv, monkeypatch):
    cfg, _, _ = rawenv
    monkeypatch.setenv("ADELE_TEST_FILE", "delivery_start,watts\n2026-03-01T10:00:00Z,1\n")
    o = fetch(rawenv)
    assert not o.ok and "columns differ" in o.error
    assert len(kept(cfg)) == 1


def test_two_answers_of_one_call_are_both_kept(rawenv, monkeypatch):
    cfg, _, _ = rawenv
    monkeypatch.setenv("ADELE_TEST_FAULT", "two")
    o = fetch(rawenv)
    assert o.ok and (o.answers, o.answers_kept) == (2, 2)
    assert sorted(r["name"] for r in kept(cfg)) == ["extra.csv", "values.csv"]


def test_a_name_that_is_not_a_file_name_fails_the_fetch(rawenv, monkeypatch):
    cfg, _, _ = rawenv
    monkeypatch.setenv("ADELE_TEST_FAULT", "badname")
    o = fetch(rawenv)
    assert not o.ok and "file name" in o.error
    assert [r["name"] for r in kept(cfg)] == ["values.csv"]  # the answer before it is kept
    assert not list((cfg.data_dir / "test_raw").rglob("escape.csv*"))


@pytest.mark.parametrize("fault", ["intname", "newline"])
def test_a_name_that_is_not_a_plain_string_fails_the_fetch(rawenv, monkeypatch, fault):
    """Review of 2026-11-15: a name 2026 passed as str(2026), and its answer was then dropped silently."""
    cfg, _, _ = rawenv
    monkeypatch.setenv("ADELE_TEST_FAULT", fault)
    o = fetch(rawenv)
    assert not o.ok and "file name" in o.error
    assert [r["name"] for r in kept(cfg)] == ["values.csv"]


def test_a_line_of_the_work_folder_that_cannot_be_read_fails(tmp_path):
    good = {"name": "a.csv", "url": None, "received_at": "2026-03-01T10:00:00+00:00", "file": "0.0.body"}
    (tmp_path / "0.0.body").write_bytes(b"a")
    lines = tmp_path / raw.ANSWERS
    lines.write_text(json.dumps(good) + "\n" + '{"name": "b.csv", "rec')  # the last line cut by the end of the child
    assert [a.name for a in raw.work_answers(tmp_path)] == ["a.csv"]
    lines.write_text(json.dumps({**good, "name": 2026}) + "\n")
    with pytest.raises(raw.RawError, match="can't be read"):
        raw.work_answers(tmp_path)
    lines.write_text(json.dumps({**good, "file": "1.0.body"}) + "\n")
    with pytest.raises(raw.RawError, match="missing"):
        raw.work_answers(tmp_path)


def test_a_query_cannot_read_the_archive(rawenv):
    cfg, catalog, _ = rawenv
    fetch(rawenv)
    [line] = kept(cfg)
    path = cfg.data_dir / "test_raw" / "_raw" / line["received_at"][:10] / "manifest.csv"
    for fn in ("read_text", "read_blob", "read_csv"):
        with pytest.raises(engine.QueryError, match="Permission"):
            engine.run(catalog, cfg.data_dir, cfg.query, f"SELECT * FROM {fn}('{path}')")
    assert engine.run(catalog, cfg.data_dir, cfg.query, "SELECT count(*) FROM test_raw.values").rows == [[2]]


def test_describe_says_that_the_answers_are_kept(rawenv):
    cfg, _, ds = rawenv
    assert render.describe_dict(cfg, ds)["raw_answers"].endswith("none yet")
    fetch(rawenv)
    today = dt.datetime.now(UTC).strftime("%Y-%m-%d")
    assert render.describe_dict(cfg, ds)["raw_answers"].endswith(f"from {today} to {today}")


@pytest.mark.parametrize("adele, source, error", [
    ("raw: keep", "def fetch(start, end):\n    pass\n", "download(start, end) and parse(answers)"),
    ("raw: keep", "def download(start, end):\n    pass\n", "download(start, end) and parse(answers)"),
    ("raw: keep", "def download(start, end):\n    pass\ndef parse(answers):\n    pass\n"
                  "def fetch(start, end):\n    pass\n", "not fetch"),
    ("", "def download(start, end):\n    pass\ndef parse(answers):\n    pass\n", "needs adele.raw: keep"),
    ("raw: always", "def download(start, end):\n    pass\ndef parse(answers):\n    pass\n", "adele.raw must be"),
])
@pytest.mark.parametrize("script", [False, True])
def test_the_catalog_refuses_half_a_raw_dataset(tmp_path, adele, source, error, script):
    folder = tmp_path / "test_raw"
    folder.mkdir()
    (folder / "datapackage.yaml").write_text(RAW.replace("  raw: keep\n", f"  {adele}\n" if adele else ""))
    head = '# /// script\n# dependencies = []\n# ///\n' if script else ""
    (folder / "fetch.py").write_text(head + source)
    with pytest.raises(CatalogError, match=error.replace("(", r"\(").replace(")", r"\)")):
        load_dataset(folder)


def test_the_catalog_accepts_a_raw_dataset_with_a_script_block(tmp_path):
    folder = tmp_path / "test_raw"
    folder.mkdir()
    (folder / "datapackage.yaml").write_text(RAW)
    (folder / "fetch.py").write_text("# /// script\n# dependencies = [\"pandas\"]\n# ///\n" + RAW_FETCH)
    ds = load_dataset(folder)
    assert ds.keeps_raw and ds.fetch is None


# --- import of answers kept by another program (WP4, point 8) ----------------------------------

def poller_folder(tmp_path, answers: list[tuple[str, str]]):
    """The Swissgrid poller's layout: <stem>/<YYYY-MM-DD>/<YYYYMMDDTHHMMSSZ>.<ext>.gz."""
    root = tmp_path / "poller"
    for stamp_, text in answers:
        d = root / "values" / f"{stamp_[:4]}-{stamp_[4:6]}-{stamp_[6:8]}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{stamp_}.csv.gz").write_bytes(gzip.compress(text.encode()))
    (root / "fetch_log_2026-03.csv").write_text("not an answer\n")
    return root / "values"


REVISED = body(("2026-03-01T10:00:00Z", 1.5), ("2026-03-01T10:05:00Z", 2.0))
POLLER = [("20260301T101501Z", A), ("20260301T102001Z", REVISED), ("20260301T103001Z", B)]


def test_import_makes_versions_stamped_with_the_time_of_reception(rawenv, tmp_path):
    cfg, catalog, ds = rawenv
    r = ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path, POLLER))
    assert (r.answers, r.skipped, r.groups, r.kept, r.rows_changed) == (3, 0, 3, 3, 5)
    t1, t2, t3 = (dt.datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) for s, _ in POLLER)
    assert versions(rawenv) == [
        (dt.datetime(2026, 3, 1, 10, 0, tzinfo=UTC), 1.0, t1),
        (dt.datetime(2026, 3, 1, 10, 0, tzinfo=UTC), 1.5, t2),
        (dt.datetime(2026, 3, 1, 10, 5, tzinfo=UTC), 2.0, t1),
        (dt.datetime(2026, 3, 1, 10, 15, tzinfo=UTC), 3.0, t3),
        (dt.datetime(2026, 3, 1, 10, 20, tzinfo=UTC), 4.0, t3),
    ]
    st = state.load(cfg.data_dir, "test_raw")
    assert st["versions_since"] == t1 and st["imported"] == [t1.isoformat(), t3.isoformat()]
    # as adele held it between the first two answers: the first value
    q = engine.run(catalog, cfg.data_dir, cfg.query, "SELECT value FROM test_raw.values ORDER BY delivery_start",
                   as_of=t1 + dt.timedelta(minutes=1))
    assert q.rows == [[1.0], [2.0]]
    assert [r_["received_at"] for r_ in kept(cfg)] == [t.isoformat() for t in (t1, t2, t3)]
    assert [r_["name"] for r_ in kept(cfg)] == ["values.csv"] * 3
    card = render.describe_dict(cfg, ds)
    assert "imported with their time of reception" in card["imported"]


def test_import_keeps_the_window_of_a_scheduled_run_at_that_time(rawenv, tmp_path):
    cfg, catalog, ds = rawenv
    old = body(("2026-03-01T08:00:00Z", 9.0), ("2026-03-01T10:10:00Z", 5.0))  # 08:00 is older than lookback + every
    r = ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path, [("20260301T101501Z", old)]))
    assert r.rows == 1
    assert [v[1] for v in versions(rawenv)] == [5.0]


def test_import_goes_on_where_it_stopped(rawenv, tmp_path):
    cfg, catalog, ds = rawenv
    ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path / "a", POLLER[:1]))
    r = ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path / "b", POLLER))
    # the group of the newest stored version is merged again (a hard stop may have left it in part): it adds nothing
    assert (r.answers, r.skipped, r.groups) == (3, 0, 3)
    assert len(versions(rawenv)) == 5 and len(kept(cfg)) == 3
    st = state.load(cfg.data_dir, "test_raw")
    assert st["imported"] == [POLLER_T(0).isoformat(), POLLER_T(2).isoformat()]


def POLLER_T(i):  # noqa: N802
    return dt.datetime.strptime(POLLER[i][0], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def test_answers_received_at_the_same_time_are_parsed_together(rawenv, tmp_path):
    cfg, catalog, ds = rawenv
    root = poller_folder(tmp_path, POLLER[:1])
    extra = root.parent / "extra" / "2026-03-01"
    extra.mkdir(parents=True)
    (extra / "20260301T101501Z.csv.gz").write_bytes(gzip.compress(b"something else"))
    r = ingest.import_answers(cfg, catalog, ds, root.parent)
    assert (r.answers, r.groups, r.kept) == (2, 1, 2)
    assert sorted(x["name"] for x in kept(cfg)) == ["extra.csv", "values.csv"]


def test_import_is_refused_once_scheduled_runs_have_started(rawenv, tmp_path):
    cfg, catalog, ds = rawenv
    st = state.load(cfg.data_dir, "test_raw")
    st["last_scheduled_at"] = dt.datetime(2026, 3, 2, tzinfo=UTC)
    state.save(cfg.data_dir, "test_raw", st)
    with pytest.raises(ingest.FetchError, match="before the first one"):
        ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path, POLLER))


def test_an_answer_that_cannot_be_parsed_does_not_stop_the_import(rawenv, tmp_path):
    """Review of 2026-11-15: one bad answer made the whole import fail, every time, without its name."""
    cfg, catalog, ds = rawenv
    answers = [POLLER[0], ("20260301T102001Z", "<html>maintenance</html>"), POLLER[2]]
    folder = poller_folder(tmp_path, answers)
    r = ingest.import_answers(cfg, catalog, ds, folder)
    assert (r.answers, r.groups, r.kept) == (3, 2, 3)
    [(at, files, error)] = r.failed
    assert at == POLLER_T(1) and files[0].name == "20260301T102001Z.csv.gz" and "KeyError" in error
    assert [v[1] for v in versions(rawenv)] == [1.0, 2.0, 3.0, 4.0]
    assert len(kept(cfg)) == 3  # the bad answer is kept too: a parser fixed later can read it


def test_import_is_refused_after_a_fetch_by_adele(rawenv, tmp_path):
    """Review of 2026-11-15: after a fetch with --start/--end every older answer was skipped, with exit 0."""
    cfg, catalog, ds = rawenv
    fetch(rawenv)
    with pytest.raises(ingest.FetchError, match="versions that adele fetched"):
        ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path, POLLER))


def test_import_goes_on_after_a_hard_stop_inside_a_group(rawenv, tmp_path):
    """Review of 2026-11-15: a hard stop between two partitions of one group left the other
    partition without that version for good. The group of the newest version is merged again."""
    cfg, catalog, ds = rawenv
    feb = body(("2026-02-28T23:40:00Z", 1.0))
    both = body(("2026-02-28T23:55:00Z", 2.0), ("2026-03-01T00:05:00Z", 3.0))  # two month partitions
    answers = [("20260228T235001Z", feb), ("20260301T001001Z", both)]
    t1, t2 = (dt.datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC) for s, _ in answers)
    ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path / "a", answers[:1]))
    # the stop: the second group reached the state and the March partition, not February
    st = state.load(cfg.data_dir, "test_raw")
    st["imported"] = [t1.isoformat(), t2.isoformat()]
    state.save(cfg.data_dir, "test_raw", st)
    con = storage.connect()
    con.execute("CREATE TEMP TABLE _batch_values AS SELECT TIMESTAMPTZ '2026-03-01 00:05:00Z' AS delivery_start, "
                "3.0::DOUBLE AS value")
    storage.merge_versions(con, cfg.data_dir, ds.tables["values"], "_batch_values", fetched_at=t2)
    con.close()
    r = ingest.import_answers(cfg, catalog, ds, poller_folder(tmp_path / "b", answers))
    assert (r.skipped, r.groups) == (1, 1)
    assert versions(rawenv) == [(dt.datetime(2026, 2, 28, 23, 40, tzinfo=UTC), 1.0, t1),
                                (dt.datetime(2026, 2, 28, 23, 55, tzinfo=UTC), 2.0, t2),
                                (dt.datetime(2026, 3, 1, 0, 5, tzinfo=UTC), 3.0, t2)]


def test_import_takes_a_relative_folder(rawenv, tmp_path, monkeypatch):
    cfg, catalog, ds = rawenv
    poller_folder(tmp_path, POLLER)
    monkeypatch.chdir(tmp_path)
    r = ingest.import_answers(cfg, catalog, ds, Path("poller/values"))
    assert (r.groups, r.failed) == (3, [])


def test_import_needs_a_dataset_that_keeps_raw_answers(env, tmp_path):
    cfg, catalog, _ = env
    with pytest.raises(ingest.FetchError, match="adele.raw: keep"):
        ingest.import_answers(cfg, catalog, catalog["test_prices"], tmp_path)


def test_an_archive_of_adele_can_be_imported_again(rawenv, tmp_path, monkeypatch):
    """The tables are lost, the archive is not: an import of the archive into the same dataset
    rebuilds every version, and adds no file to the archive."""
    cfg, catalog, ds = rawenv
    # rows of the last minutes: the import keeps the window of a scheduled run at the time of reception
    t0 = dt.datetime.now(UTC).replace(second=0, microsecond=0) - dt.timedelta(minutes=20)
    stamps = [f"{t0 + dt.timedelta(minutes=5 * i):%Y-%m-%dT%H:%M:%SZ}" for i in range(2)]
    window = (t0 - dt.timedelta(hours=1), t0 + dt.timedelta(hours=1))
    monkeypatch.setenv("ADELE_TEST_FILE", body((stamps[0], 1.0), (stamps[1], 2.0)))
    fetch(rawenv, window)
    monkeypatch.setenv("ADELE_TEST_FILE", body((stamps[0], 1.5), (stamps[1], 2.0)))
    fetch(rawenv, window)
    before = versions(rawenv)
    assert len(before) == 3
    for p in (cfg.data_dir / "test_raw" / "values").glob("*.parquet"):
        p.unlink()
    (cfg.data_dir / "test_raw" / "state.json").unlink()
    r = ingest.import_answers(cfg, catalog, ds, cfg.data_dir / "test_raw" / "_raw")
    assert (r.answers, r.groups, r.kept) == (2, 2, 0)
    after = versions(rawenv)
    assert [v[:2] for v in after] == [v[:2] for v in before]
    # rebuilt versions carry the time of reception, a little before the time at which fetch.py returned (D30)
    assert all(dt.timedelta(0) <= b[2] - a[2] < dt.timedelta(seconds=1) for a, b in zip(after, before))
    assert len(kept(cfg)) == 2
    # the URL comes back from the manifest
    assert all(a.url == "https://example.org/values.csv" for a in raw.find_answers(cfg.data_dir / "test_raw" / "_raw"))


# --- G6: a file revised in place, compared whole at each fetch ----------------------------------

YEAR = """\
name: test_year
title: Synthetic year file revised in place
resources:
  - name: daily
    schema:
      primaryKey: [delivery_start]
      fields:
        - {name: delivery_start, type: datetime}
        - {name: value, type: number}
adele:
  format_version: 1
  secrets: [ADELE_TEST_REVISE]
  refresh: {every: PT6H, lookback: LOOKBACK, horizon: PT0S}
  revisions: append-only
"""

# The whole file at each fetch, whatever the window: one value per day of January and February,
# the day of the month; ADELE_TEST_REVISE (JSON {"YYYY-MM-DD": value}) revises some.
YEAR_FETCH = """\
import json
import os

import pandas as pd

def fetch(start, end):
    revise = json.loads(os.environ.get("ADELE_TEST_REVISE") or "{}")
    idx = pd.date_range("2026-01-01", "2026-03-01", freq="D", inclusive="left", tz="UTC")
    return pd.DataFrame({"delivery_start": idx,
                         "value": [revise.get(f"{t:%Y-%m-%d}", float(t.day)) for t in idx]})
"""


@pytest.mark.parametrize("lookback, kept_revision", [("P800D", True), ("P3D", False)])
def test_a_long_lookback_keeps_a_revision_six_weeks_back(env, monkeypatch, lookback, kept_revision):
    cfg, _, _ = env
    folder = cfg.datasets_dir / "test_year"
    folder.mkdir()
    (folder / "datapackage.yaml").write_text(YEAR.replace("LOOKBACK", lookback))
    (folder / "fetch.py").write_text(YEAR_FETCH)
    catalog = load_catalog(cfg.datasets_dir)
    ds = catalog["test_year"]
    now = dt.datetime(2026, 3, 1, 6, tzinfo=UTC)
    monkeypatch.delenv("ADELE_TEST_REVISE", raising=False)
    first = ingest.scheduled_fetch(cfg, catalog, ds, now)
    assert first.ok
    monkeypatch.setenv("ADELE_TEST_REVISE", json.dumps({"2026-01-15": 99.0}))
    second = ingest.scheduled_fetch(cfg, catalog, ds, now + dt.timedelta(hours=6))
    assert second.ok
    con = storage.connect()
    rows = con.execute(f"SELECT value FROM ({storage.versions_sql(cfg.data_dir, ds.tables['daily'])}) "
                       "WHERE delivery_start = '2026-01-15 00:00Z' ORDER BY fetched_at").fetchall()
    con.close()
    if kept_revision:
        assert first.rows == 59 and rows == [(15.0,), (99.0,)]
        assert (second.rows_changed, second.partitions_written) == (1, 1)  # February is not written again
    else:  # the window of 3 days drops the revision: the gap G6 of the inventory
        assert rows == [] and second.rows_changed == 0


def test_the_runner_text_has_no_stray_escape():
    """The runner is a Python string inside Python: its line continuation and newline must survive."""
    src = ingest._RUNNER_BODY
    compile(src, "runner", "exec")
    assert '"\\n"' in src and "\\\n" in src
    assert textwrap.dedent(src) == src
