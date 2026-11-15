"""Catch-up: a scheduled run fetches [last scheduled run - lookback, now + horizon), so a stop
longer than the lookback leaves no hole. `adele.refresh.max_window` cuts a long window into pieces.
A stretch that keeps failing is retried for one lookback after its first failed run, then given up.

The tests pass `now` to the scheduled run instead of sleeping.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil

import duckdb
import pytest

from adele_server import cli, ingest, render, state
from adele_server.catalog import CatalogError, load_catalog

UTC = dt.timezone.utc
H, D = dt.timedelta(hours=1), dt.timedelta(days=1)
NOW0 = dt.datetime(2026, 3, 10, 12, tzinfo=UTC)  # the first scheduled run
LATER = NOW0 + 10 * D  # the next one, after a stop of 10 days (lookback: 3 days)

REFRESH = "refresh: {every: PT1H, lookback: P3D, horizon: P1D}"
CATCH = f"""\
name: test_catch
title: Synthetic hourly values
resources:
  - name: v
    schema:
      primaryKey: [delivery_start]
      fields:
        - {{name: delivery_start, type: datetime}}
        - {{name: value, type: number}}
adele:
  format_version: 1
  secrets: [ADELE_TEST_CALLS, ADELE_TEST_STORE, ADELE_TEST_FAIL_AT]
  {REFRESH}
  revisions: overwrite
"""

# One value per hour. Logs each window it is called with, and the number of rows stored at that
# time (so a test sees that a piece was merged before the next one started). ADELE_TEST_FAIL_AT:
# `all` fails every call, a timestamp fails the call whose window holds it.
CATCH_FETCH = """\
import glob
import json
import os

import duckdb
import pandas as pd

def fetch(start, end):
    store = os.environ["ADELE_TEST_STORE"]
    stored = 0
    if glob.glob(store + "/*.parquet"):
        stored = duckdb.execute(f"SELECT count(*) FROM read_parquet('{store}/*.parquet')").fetchone()[0]
    with open(os.environ["ADELE_TEST_CALLS"], "a") as fh:
        fh.write(json.dumps([start.isoformat(), end.isoformat(), stored]) + "\\n")
    fail_at = os.environ.get("ADELE_TEST_FAIL_AT", "")
    if fail_at == "all" or (fail_at and start <= pd.Timestamp(fail_at) < end):
        raise RuntimeError("source down")
    idx = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    return pd.DataFrame({"delivery_start": idx, "value": [float(t.hour) for t in idx]}).astype({"value": "float64"})
"""

RUNS = """\
name: test_catch_runs
title: Synthetic forecast runs
resources:
  - name: runs
    schema:
      primaryKey: [init_time, delivery_start]
      fields:
        - {name: init_time, type: datetime}
        - {name: delivery_start, type: datetime}
        - {name: value, type: number}
adele:
  format_version: 1
  secrets: [ADELE_TEST_CALLS]
  refresh: {every: PT1H, lookback: PT12H, horizon: PT1H}
  revisions: none
  window: init_time
  partition: day
"""

# One run per hour, leads 1-2 h. Logs each window it is called with.
RUNS_FETCH = """\
import json
import os

import pandas as pd

def fetch(start, end):
    with open(os.environ["ADELE_TEST_CALLS"], "a") as fh:
        fh.write(json.dumps([start.isoformat(), end.isoformat(), 0]) + "\\n")
    first = start.replace(minute=0, second=0, microsecond=0)
    inits = [i for i in pd.date_range(first, end, freq="h", inclusive="left", tz="UTC") if i >= start]
    rows = [(i, i + pd.Timedelta(hours=lead - 1), float(lead)) for i in inits for lead in (1, 2)]
    return pd.DataFrame(rows, columns=["init_time", "delivery_start", "value"]).astype(
        {"init_time": "datetime64[ns, UTC]", "delivery_start": "datetime64[ns, UTC]", "value": "float64"})
"""


class Catch:
    """The dataset test_catch (or test_catch_runs), alone in the catalog, with its log of calls."""

    def __init__(self, cfg, log, ds_id="test_catch", descriptor=CATCH, fetch=CATCH_FETCH):
        self.cfg, self.log, self.id, self.descriptor = cfg, log, ds_id, descriptor
        self.folder = cfg.datasets_dir / ds_id
        self.folder.mkdir()
        (self.folder / "fetch.py").write_text(fetch)
        self.declare()

    def declare(self, max_window=None):
        """Write the descriptor, with or without adele.refresh.max_window, and load the catalog."""
        text = self.descriptor
        if max_window is not None:
            text = text.replace("horizon: P1D}", f"horizon: P1D, max_window: {max_window}}}")
            text = text.replace("horizon: PT1H}", f"horizon: PT1H, max_window: {max_window}}}")
        (self.folder / "datapackage.yaml").write_text(text)
        self.catalog = load_catalog(self.cfg.datasets_dir)
        self.ds = self.catalog[self.id]
        return self

    def run(self, now):
        """One scheduled run at `now` --> (outcome, the windows that fetch() was called with)."""
        self.log.write_text("")
        o = ingest.scheduled_fetch(self.cfg, self.catalog, self.ds, now)
        return o, self.calls()

    def backfill(self, start, end, step, now):
        self.log.write_text("")
        return ingest.backfill(self.cfg, self.catalog, self.ds, start, end, step, now=now)

    def calls(self, with_stored=False):
        lines = [json.loads(ln) for ln in self.log.read_text().splitlines()]
        windows = [(dt.datetime.fromisoformat(s), dt.datetime.fromisoformat(e)) for s, e, _ in lines]
        return (windows, [n for _, _, n in lines]) if with_stored else windows

    def state(self):
        return state.load(self.cfg.data_dir, self.id)

    def anchor(self):
        return self.state().get("last_scheduled_at")

    def stored(self):
        """The distinct stored values of the window column, in order."""
        table = next(iter(self.ds.tables))
        con = duckdb.connect()
        con.execute("SET TimeZone = 'UTC'")
        return [r[0] for r in con.execute(
            f"SELECT DISTINCT {self.ds.window} FROM read_parquet('{self.cfg.data_dir}/{self.id}/{table}/*.parquet') "
            "ORDER BY 1").fetchall()]

    def alerts(self):
        lines = (self.cfg.log_dir / "alerts.log").read_text().splitlines()
        return [a.split(": ", 1)[1].split(" |")[0] for a in lines]


def hours(start, end):
    """Every hour of [start, end): what a table without a hole holds."""
    return [start + i * H for i in range(int((end - start) / H))]


@pytest.fixture
def catch(env, tmp_path, monkeypatch):
    cfg, _, _ = env
    shutil.rmtree(cfg.datasets_dir / "test_prices")
    monkeypatch.setenv("ADELE_TEST_CALLS", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("ADELE_TEST_STORE", str(cfg.data_dir / "test_catch" / "v"))
    monkeypatch.delenv("ADELE_TEST_FAIL_AT", raising=False)
    return Catch(cfg, tmp_path / "calls.jsonl")


@pytest.fixture
def runs(env, tmp_path, monkeypatch):
    cfg, _, _ = env
    shutil.rmtree(cfg.datasets_dir / "test_prices")
    monkeypatch.setenv("ADELE_TEST_CALLS", str(tmp_path / "calls.jsonl"))
    return Catch(cfg, tmp_path / "calls.jsonl", "test_catch_runs", RUNS, RUNS_FETCH)


# --- the scheduled window starts at the last scheduled run that succeeded --------------------

def test_first_run_fetches_now_minus_lookback(catch):
    assert ingest.scheduled_window(catch.ds, NOW0) == (NOW0 - 3 * D, NOW0 + D)  # no state: as before
    o, calls = catch.run(NOW0)
    assert o.ok and (o.start, o.end) == (NOW0 - 3 * D, NOW0 + D) and calls == [(o.start, o.end)], o.error
    assert catch.anchor() == NOW0


def test_a_stop_of_10_days_leaves_no_hole(catch):
    catch.run(NOW0)
    o, calls = catch.run(LATER)
    # [LATER - 3 days, ...) would leave [NOW0 + 1 day, NOW0 + 7 days) out for good
    assert o.ok and calls == [(NOW0 - 3 * D, LATER + D)], o.error
    assert catch.stored() == hours(NOW0 - 3 * D, LATER + D)
    assert catch.anchor() == LATER and catch.state()["status"] == "ok"


def test_nothing_changes_when_no_run_was_missed(catch):
    o, calls = catch.run(NOW0)
    assert calls == [(NOW0 - 3 * D, NOW0 + D)] and o.rows_changed == 96
    for n in (1, 2):
        now = NOW0 + n * H
        o, calls = catch.run(now)
        # one fetch per run, of the usual window plus the hour since the run before
        assert o.ok and o.pieces == 1 and calls == [(now - H - 3 * D, now + D)], o.error
        assert o.rows == 97 and o.rows_changed == 1 and o.problems == []
        assert catch.anchor() == now
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + 2 * H + D)
    st = catch.state()
    assert st["status"] == "ok" and "last_error" not in st and st["last_rows"] == {"fetched": 97, "changed": 1}
    assert st["last_window"] == [(NOW0 + H - 3 * D).isoformat(), (NOW0 + 2 * H + D).isoformat()]
    assert catch.alerts() == ["failing --> ok"]  # the first fetch only
    assert not ingest.is_due(catch.ds, st, st["last_attempt_at"])  # is_due still reads last_attempt_at


def test_a_max_window_longer_than_the_window_changes_nothing(catch):
    catch.declare(max_window="P5D")
    assert catch.run(NOW0)[1] == [(NOW0 - 3 * D, NOW0 + D)]
    o, calls = catch.run(NOW0 + H)
    assert o.ok and o.pieces == 1 and calls == [(NOW0 - 3 * D, NOW0 + H + D)]


def test_a_failed_run_keeps_the_anchor(catch, monkeypatch):
    catch.run(NOW0)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", "all")
    for now in (NOW0 + D, NOW0 + 2 * D):  # the window grows at each failed run
        o, calls = catch.run(now)
        assert not o.ok and o.error.endswith("source down") and calls == [(NOW0 - 3 * D, now + D)]
        assert catch.anchor() == NOW0 and catch.state()["status"] == "failing"
        assert catch.state()["failing_since"] == NOW0 + D  # the first run that failed
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + D)
    monkeypatch.delenv("ADELE_TEST_FAIL_AT")
    now = NOW0 + 4 * D  # one lookback after the first failure, not longer: still from the anchor
    o, calls = catch.run(now)
    assert o.ok and calls == [(NOW0 - 3 * D, now + D)], o.error
    assert catch.stored() == hours(NOW0 - 3 * D, now + D)
    st = catch.state()
    assert catch.anchor() == now and st["status"] == "ok" and "failing_since" not in st
    assert catch.alerts() == ["failing --> ok", "ok --> failing", "failing --> ok"]


def test_a_run_skipped_because_of_the_lock_keeps_the_anchor(catch):
    catch.run(NOW0)
    catch.log.write_text("")
    with ingest.dataset_lock(catch.cfg.data_dir, catch.id):
        with pytest.raises(ingest.FetchError, match="another fetch"):
            ingest.scheduled_fetch(catch.cfg, catch.catalog, catch.ds, LATER)
    assert catch.calls() == [] and catch.anchor() == NOW0


def test_an_anchor_later_than_now_counts_as_now(catch):
    catch.run(LATER)
    o, calls = catch.run(NOW0)  # the clock was set back
    assert o.ok and calls == [(NOW0 - 3 * D, NOW0 + D)], o.error
    assert catch.anchor() == NOW0


def test_a_failed_catch_up_in_one_window_says_how_long_the_window_is(catch, monkeypatch):
    catch.run(NOW0)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", "all")
    o, _ = catch.run(LATER)  # the first run after a stop of 10 days
    assert o.error.endswith("(one window of 14 d 0 h: the last scheduled run that succeeded was at 2026-03-10 12:00 UTC)")
    assert catch.state()["problems"][0] == f"last fetch failed: {o.error}"


# --- giving up: a stretch that fails is retried for one lookback after its first failed run ------

def test_giving_up_starts_after_one_lookback(catch):
    st = {"last_scheduled_at": NOW0, "failing_since": NOW0 + D}
    now = NOW0 + 4 * D
    assert ingest.scheduled_window(catch.ds, now, st) == (NOW0 - 3 * D, now + D)  # one lookback exactly: not yet
    now += dt.timedelta(seconds=1)
    assert ingest.scheduled_window(catch.ds, now, st) == (now - 3 * D, now + D)
    assert ingest.scheduled_window(catch.ds, now, {"failing_since": NOW0}) == (now - 3 * D, now + D)  # no anchor


def test_a_source_that_fails_longer_than_the_lookback_is_given_up(catch, monkeypatch):
    catch.run(NOW0)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", "all")
    first = NOW0 + D
    for now in (first, first + 3 * D):  # retried for one lookback: the window starts at the anchor
        o, calls = catch.run(now)
        assert not o.ok and calls == [(NOW0 - 3 * D, now + D)]
    assert catch.state()["failing_since"] == first and "given_up" not in catch.state()
    for now in (first + 3 * D + H, first + 5 * D):  # longer than one lookback: [now - lookback, now + horizon)
        o, calls = catch.run(now)
        assert not o.ok and o.error.endswith("source down") and calls == [(now - 3 * D, now + D)]
        assert catch.anchor() == NOW0 and catch.state()["failing_since"] == first
    assert catch.state()["given_up"] == [(NOW0 - 3 * D).isoformat(), (first + H).isoformat()]
    monkeypatch.delenv("ADELE_TEST_FAIL_AT")
    o, calls = catch.run(LATER)
    assert o.ok and calls == [(LATER - 3 * D, LATER + D)], o.error
    st = catch.state()
    assert catch.anchor() == LATER and st["status"] == "ok" and "failing_since" not in st and "given_up" not in st
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + D) + hours(LATER - 3 * D, LATER + D)  # the hole that was given up
    # one line for the stretch, written by the first run that gave up
    assert catch.alerts() == ["failing --> ok", "ok --> failing", (
        "gave up on delivery_start [2026-03-07 12:00, 2026-03-11 13:00) UTC: the scheduled runs have failed since "
        "2026-03-11 12:00 UTC, longer than the lookback. The window is [now - lookback, now + horizon) again"),
        "failing --> ok"]


def test_one_piece_that_always_fails_is_retried_for_one_lookback_then_given_up(catch, monkeypatch):
    catch.declare(max_window="P1D")
    catch.run(NOW0)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", (NOW0 + D + 6 * H).isoformat())  # the piece that holds it fails at every run
    first = NOW0 + D

    def stored_but_the_bad_day(now):
        return hours(NOW0 - 3 * D, NOW0 + D) + hours(NOW0 + 2 * D, now + D)

    for now in (first, first + D, first + 3 * D):  # one lookback: failing, and the pieces after the bad one come in
        o, calls = catch.run(now)
        assert not o.ok and calls == ingest.split_window(NOW0 - 3 * D, now + D, D)  # every piece, from the anchor
        assert o.error.startswith(f"1 of {len(calls)} pieces failed: [2026-03-11 12:00, 2026-03-12 12:00) (UTC); first error: ")
        assert catch.state()["status"] == "failing" and catch.anchor() == NOW0
        assert catch.stored() == stored_but_the_bad_day(now)
    for now in (first + 3 * D + H, first + 3 * D + 2 * H):  # given up: the plain window, which still holds the bad time
        o, calls = catch.run(now)
        assert not o.ok and calls == ingest.split_window(now - 3 * D, now + D, D)
        assert catch.state()["status"] == "failing" and catch.anchor() == NOW0
        assert catch.stored() == stored_but_the_bad_day(now)
    now = first + 4 * D  # the bad time has left the window
    o, calls = catch.run(now)
    assert o.ok and calls == ingest.split_window(now - 3 * D, now + D, D), o.error
    st = catch.state()
    assert st["status"] == "ok" and catch.anchor() == now and "failing_since" not in st
    assert catch.stored() == stored_but_the_bad_day(now)  # only the piece that failed is missing
    alerts = catch.alerts()
    assert len(alerts) == 4 and alerts[2].startswith("gave up on delivery_start [2026-03-07 12:00, 2026-03-11 13:00) UTC")
    assert [alerts[0], alerts[1], alerts[3]] == ["failing --> ok", "ok --> failing", "failing --> ok"]


def test_without_pieces_nothing_is_stored_until_the_window_is_plain_again(catch, monkeypatch):
    catch.run(NOW0)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", (NOW0 + D + 6 * H).isoformat())
    first = NOW0 + D
    for now in (first, first + D, first + 3 * D):  # one window, which fails as a whole
        o, calls = catch.run(now)
        assert not o.ok and calls == [(NOW0 - 3 * D, now + D)]
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + D)  # nothing new for one lookback
    now = first + 3 * D + 12 * H
    o, calls = catch.run(now)  # given up: the plain window, which starts after the bad time
    assert o.ok and calls == [(now - 3 * D, now + D)], o.error
    assert catch.anchor() == now and catch.state()["status"] == "ok"
    # 12 hours are left out, for one bad hour: without pieces the whole stretch is given up
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + D) + hours(now - 3 * D, now + D)
    assert catch.alerts()[2].startswith("gave up on delivery_start [2026-03-07 12:00, 2026-03-12 00:00) UTC")


# --- backfill and explicit windows -----------------------------------------------------------

@pytest.mark.parametrize("scheduled_before", [False, True])
def test_a_long_backfill_then_a_scheduled_run_leaves_no_hole(catch, scheduled_before):
    if scheduled_before:
        catch.run(NOW0 - D)
    # started at NOW0, to its default end NOW0 + horizon; it finishes 5 days later
    outs = catch.backfill(NOW0 - 30 * D, NOW0 + D, 10 * D, now=NOW0)
    assert len(outs) == 4 and all(o.ok for o in outs)
    assert catch.anchor() == NOW0  # the time at which it started, not the time of its last window
    o, calls = catch.run(NOW0 + 5 * D)
    assert o.ok and calls == [(NOW0 - 3 * D, NOW0 + 6 * D)], o.error
    assert catch.stored() == hours(NOW0 - 30 * D, NOW0 + 6 * D)
    assert catch.anchor() == NOW0 + 5 * D


def test_a_partial_backfill_does_not_move_the_anchor(catch):
    catch.run(NOW0)
    # stopped before the present
    outs = catch.backfill(NOW0 - 30 * D, NOW0 - 10 * D, None, now=LATER)
    assert [o.ok for o in outs] == [True] and catch.anchor() == NOW0
    # reached the present, but started after anchor - lookback: the time before its start is
    # still to fetch
    outs = catch.backfill(LATER - D, LATER + D, None, now=LATER)
    assert [o.ok for o in outs] == [True] and catch.anchor() == NOW0
    assert NOW0 + 2 * D not in catch.stored()
    # the scheduled run fetches what the backfills left out
    o, calls = catch.run(LATER + H)
    assert o.ok and calls == [(NOW0 - 3 * D, LATER + H + D)], o.error
    assert catch.stored() == hours(NOW0 - 30 * D, NOW0 - 10 * D) + hours(NOW0 - 3 * D, LATER + H + D)


def test_a_backfill_to_the_present_moves_the_anchor_although_a_window_failed(catch, monkeypatch):
    catch.run(NOW0)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", "all")
    catch.run(NOW0 + D)  # a scheduled run fails
    assert catch.state()["failing_since"] == NOW0 + D
    outs = catch.backfill(NOW0 - 3 * D, LATER + D, 7 * D, now=LATER)  # every window fails: nothing was backfilled
    assert [o.ok for o in outs] == [False, False]
    assert catch.anchor() == NOW0 and catch.state()["failing_since"] == NOW0 + D
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", (NOW0 + 2 * D).isoformat())
    outs = catch.backfill(NOW0 - 3 * D, LATER + D, 7 * D, now=LATER)
    assert [(o.ok, o.start, o.end) for o in outs] == [(False, NOW0 - 3 * D, NOW0 + 4 * D), (True, NOW0 + 4 * D, LATER + D)]
    # it counts as a scheduled run made when it started, and the scheduled runs start again from it
    assert catch.anchor() == LATER and "failing_since" not in catch.state()
    monkeypatch.delenv("ADELE_TEST_FAIL_AT")
    o, calls = catch.run(LATER + 5 * D)  # from the backfill on, although the first failure is 14 days old
    assert o.ok and calls == [(LATER - 3 * D, LATER + 6 * D)], o.error
    # the window that failed stays out: the backfill listed it, the scheduled run starts at LATER - lookback
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + D) + hours(NOW0 + 4 * D, LATER + 6 * D)


def test_cli_backfill_lists_the_failed_windows(catch, monkeypatch, capsys):
    monkeypatch.setattr(state, "now", lambda: LATER)
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", (NOW0 + 2 * D).isoformat())
    rc = cli.main(["--config", str(catch.cfg.path), "backfill", "test_catch", "--start", "2026-03-07T12:00",
                   "--step-days", "7"])
    out = capsys.readouterr().out
    assert rc == 1 and "test_catch: 2 windows, 168 rows, 1 failed" in out
    assert "  failed [2026-03-07 12:00, 2026-03-14 12:00) UTC: FetchError" in out
    assert "  the scheduled runs fetch again from 2026-03-17 12:00 UTC on" in out
    assert catch.anchor() == LATER


def test_a_backfill_never_moves_the_anchor_back(catch):
    catch.run(LATER)
    outs = catch.backfill(NOW0 - 30 * D, NOW0 + D, None, now=NOW0)  # e.g. started before that run, finished after
    assert all(o.ok for o in outs) and catch.anchor() == LATER


def test_backfill_steps_by_max_window_unless_a_step_is_given(catch):
    outs = catch.backfill(NOW0 - 4 * D, NOW0, None, now=LATER)
    assert [(o.start, o.end) for o in outs] == [(NOW0 - 4 * D, NOW0)]  # default: 365 days
    catch.declare(max_window="P2D")
    outs = catch.backfill(NOW0 - 4 * D, NOW0, None, now=LATER)
    assert [(o.start, o.end) for o in outs] == [(NOW0 - 4 * D, NOW0 - 2 * D), (NOW0 - 2 * D, NOW0)]
    outs = catch.backfill(NOW0 - 4 * D, NOW0, 3 * D, now=LATER)
    assert [(o.start, o.end) for o in outs] == [(NOW0 - 4 * D, NOW0 - D), (NOW0 - D, NOW0)]
    assert catch.anchor() is None  # none of them reached the present


def test_cli_fetch_with_start_or_end_does_not_move_the_anchor(catch, monkeypatch, capsys):
    main = lambda *args: cli.main(["--config", str(catch.cfg.path), *args])  # noqa: E731
    monkeypatch.setattr(state, "now", lambda: NOW0)
    assert main("fetch", "test_catch") == 0  # a scheduled run
    assert catch.anchor() == NOW0
    monkeypatch.setattr(state, "now", lambda: LATER)
    assert main("fetch", "test_catch", "--start", "2026-03-19") == 0
    assert main("fetch", "test_catch", "--end", "2026-03-19") == 0  # [LATER - lookback, end)
    assert main("backfill", "test_catch", "--start", "2026-03-19", "--end", "2026-03-20", "--step-hours", "12") == 0
    assert catch.anchor() == NOW0
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + D) + hours(LATER - 3 * D, LATER + D)  # a hole, for now
    assert main("fetch", "--due") == 0  # not due: the fetches above were attempts at LATER
    assert catch.anchor() == NOW0
    monkeypatch.setattr(state, "now", lambda: LATER + H)
    capsys.readouterr()
    assert main("fetch", "--due") == 0  # the scheduled run fills the hole
    assert "test_catch [2026-03-07 12:00, 2026-03-21 13:00) UTC: ok" in capsys.readouterr().out
    assert catch.anchor() == LATER + H
    assert catch.stored() == hours(NOW0 - 3 * D, LATER + H + D)


def test_cli_backfill_to_the_present_moves_the_anchor(catch, monkeypatch, capsys):
    catch.declare(max_window="P2D")
    monkeypatch.setattr(state, "now", lambda: NOW0)
    assert cli.main(["--config", str(catch.cfg.path), "backfill", "test_catch", "--start", "2026-03-05"]) == 0
    assert "test_catch: 4 windows, 156 rows, 0 failed" in capsys.readouterr().out  # 6.5 days in steps of max_window
    assert catch.anchor() == NOW0


# --- pieces (adele.refresh.max_window) --------------------------------------------------------

def test_pieces_oldest_first_each_merged_and_a_failing_piece_does_not_stop_the_run(catch, monkeypatch):
    catch.declare(max_window="P2D")
    o, calls = catch.run(NOW0)  # 4 days: 2 pieces
    assert o.ok and o.pieces == 2 and calls == [(NOW0 - 3 * D, NOW0 - D), (NOW0 - D, NOW0 + D)], o.error
    pieces = [(NOW0 - 3 * D + 2 * i * D, NOW0 - D + 2 * i * D) for i in range(7)]  # 14 days after the stop
    monkeypatch.setenv("ADELE_TEST_FAIL_AT", (NOW0 + 5 * D + 6 * H).isoformat())  # in piece 5
    catch.log.write_text("")
    o = ingest.scheduled_fetch(catch.cfg, catch.catalog, catch.ds, LATER)
    calls, stored_at_call = catch.calls(with_stored=True)
    assert calls == pieces  # oldest first, every piece, also after the one that failed
    assert stored_at_call == [96, 96, 96, 144, 192, 192, 240]  # each piece is merged before the next starts
    assert not o.ok and o.pieces == 7 and (o.start, o.end) == (NOW0 - 3 * D, LATER + D)
    assert o.error.startswith("1 of 7 pieces failed: [2026-03-15 12:00, 2026-03-17 12:00) (UTC); first error: FetchError: ")
    assert "source down" in o.error and o.rows == 6 * 48 and o.rows_changed == 4 * 48
    assert catch.stored() == hours(NOW0 - 3 * D, NOW0 + 5 * D) + hours(NOW0 + 7 * D, LATER + D)
    st = catch.state()
    assert catch.anchor() == NOW0 and st["status"] == "failing" and st["failing_since"] == LATER
    assert st["problems"] == [f"last fetch failed: {o.error}"] and st["last_error"] == o.error
    assert st["last_window"] == [(NOW0 - 3 * D).isoformat(), (LATER + D).isoformat()]
    assert catch.alerts() == ["failing --> ok", "ok --> failing"]  # one alert for the run, not one per piece

    monkeypatch.setenv("ADELE_TEST_FAIL_AT", "all")  # the text names three failed pieces at most
    o, calls = catch.run(LATER)
    assert calls == pieces and o.error.startswith(
        "7 of 7 pieces failed: [2026-03-07 12:00, 2026-03-09 12:00), [2026-03-09 12:00, 2026-03-11 12:00), "
        "[2026-03-11 12:00, 2026-03-13 12:00) and 4 more (UTC); first error: FetchError: ")

    monkeypatch.delenv("ADELE_TEST_FAIL_AT")
    o, calls = catch.run(LATER)  # the same anchor: every piece again (revisions: overwrite)
    assert o.ok and calls == pieces and o.rows == 14 * 24 and o.rows_changed == 2 * 24, o.error
    assert catch.stored() == hours(NOW0 - 3 * D, LATER + D)
    st = catch.state()
    assert catch.anchor() == LATER and st["status"] == "ok" and "last_error" not in st and "failing_since" not in st
    assert st["last_rows"] == {"fetched": 14 * 24, "changed": 2 * 24}
    assert catch.alerts() == ["failing --> ok", "ok --> failing", "failing --> ok"]


def test_the_last_piece_may_be_shorter(catch):
    catch.declare(max_window="P3D")
    _, calls = catch.run(NOW0)
    assert calls == [(NOW0 - 3 * D, NOW0), (NOW0, NOW0 + D)]
    assert ingest.split_window(NOW0, NOW0 + 6 * D, 3 * D) == [(NOW0, NOW0 + 3 * D), (NOW0 + 3 * D, NOW0 + 6 * D)]
    assert ingest.split_window(NOW0, NOW0 + 6 * D, None) == [(NOW0, NOW0 + 6 * D)]


def test_describe_shows_the_pieces(catch):
    card = render.describe_dict(catch.cfg, catch.ds)
    assert card["freshness"]["refresh"] == "every PT1H, window on delivery_start [last scheduled run - P3D, now + P1D)"
    card = render.describe_dict(catch.cfg, catch.declare(max_window="PT36H").ds)
    assert card["freshness"]["refresh"].endswith("[last scheduled run - P3D, now + P1D), in pieces of P1DT12H")


@pytest.mark.parametrize("value", ["P1M", "soon", "PT0S", 3600, "null"])
def test_a_bad_max_window_is_refused_by_validate(catch, capsys, value):
    with pytest.raises(CatalogError, match="adele.refresh.max_window"):
        catch.declare(max_window=value)
    assert cli.main(["--config", str(catch.cfg.path), "validate"]) == 2
    assert "adele.refresh.max_window" in capsys.readouterr().err


def test_a_good_max_window_is_accepted(catch, capsys):
    assert catch.ds.refresh.max_window is None
    assert catch.declare(max_window="PT6H").ds.refresh.max_window == 6 * H
    assert cli.main(["--config", str(catch.cfg.path), "validate"]) == 0


# --- revisions: none --------------------------------------------------------------------------

@pytest.mark.parametrize("max_window, pieces", [(None, 1), ("PT12H", 4)])
def test_revisions_none_fetches_only_what_is_missing(runs, max_window, pieces):
    runs.declare(max_window=max_window)
    o, _ = runs.run(NOW0)
    assert o.ok and runs.stored() == hours(NOW0 - 12 * H, NOW0 + H), o.error
    before = runs.stored()
    later = NOW0 + D  # a stop of 1 day, lookback 12 h
    o, calls = runs.run(later)
    assert o.ok and o.pieces == pieces and (o.start, o.end) == (NOW0 - 12 * H, later + H), o.error
    assert not [(s, e, v) for s, e in calls for v in before if s <= v < e]  # no stored run is asked again
    assert calls == sorted(calls) and o.windows_fetched == len(calls)
    assert o.rows == o.rows_changed == 24 * 2  # the 24 runs since the first fetch, 2 leads each
    assert runs.stored() == hours(NOW0 - 12 * H, later + H)
    assert runs.anchor() == later
