"""datasets/entsoe_load/fetch.py on synthetic answers: the parser (curve types A01 and A03), the
one-hour shift of the Swiss actual load before 2024-12-31 23:00 UTC, the cut to the window.
No network: entsoe-py is replaced by a stub, the answers are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

FETCH = Path(__file__).resolve().parents[2] / "datasets" / "entsoe_load" / "fetch.py"
UTC = dt.timezone.utc


@pytest.fixture
def fl(monkeypatch):
    entsoe = types.ModuleType("entsoe")
    exceptions = types.ModuleType("entsoe.exceptions")

    class NoMatchingDataError(Exception):
        pass

    exceptions.NoMatchingDataError = NoMatchingDataError
    entsoe.EntsoeRawClient = object
    entsoe.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "entsoe", entsoe)
    monkeypatch.setitem(sys.modules, "entsoe.exceptions", exceptions)
    spec = importlib.util.spec_from_file_location("entsoe_load_fetch", FETCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def answer(start: str, end: str, points: list[tuple[int, float]], curve: str = "A03", res: str = "PT60M",
           unit: str = "MAW") -> str:
    pts = "".join(f"<Point><position>{p}</position><quantity>{q}</quantity></Point>" for p, q in points)
    return (f'<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">'
            f"<TimeSeries><quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name><curveType>{curve}</curveType>"
            f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
            f"<resolution>{res}</resolution>{pts}</Period></TimeSeries></GL_MarketDocument>")


def test_a03_holds_a_value_until_the_next_point(fl):
    df = fl.parse(answer("2026-03-01T00:00Z", "2026-03-01T05:00Z", [(1, 10.0), (2, 20.0), (4, 40.0)]))
    assert df["load"].tolist() == [10.0, 20.0, 20.0, 40.0, 40.0]
    assert df["delivery_start"].iloc[-1] == pd.Timestamp("2026-03-01T04:00Z")
    assert (df["resolution"] == pd.Timedelta(hours=1)).all()


def test_a01_is_one_value_per_position(fl):
    df = fl.parse(answer("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0), (2, 2.0), (3, 3.0), (4, 4.0)],
                         curve="A01", res="PT15M"))
    assert df["load"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert df["delivery_start"].iloc[1] == pd.Timestamp("2026-03-01T00:15Z")


@pytest.mark.parametrize("kw, msg", [({"unit": "MWH"}, "unit"), ({"curve": "A02"}, "curve type"),
                                      ({"res": "P1D"}, "resolution")])
def test_unknown_unit_curve_or_resolution_is_refused(fl, kw, msg):
    with pytest.raises(RuntimeError, match=msg):
        fl.parse(answer("2026-03-01T00:00Z", "2026-03-02T00:00Z", [(1, 1.0)], **kw))


def test_actual_load_before_2025_moves_back_one_hour_and_is_cut_to_the_window(fl, monkeypatch):
    """Served stamps 2024-12-31 20:00 .. 2025-01-01 00:00 (UTC). Before 23:00 they are end stamps."""
    asked = []

    def fake_request(client, zone, process, s, e):
        asked.append((process, s, e))
        if process != "A16":
            return None
        return fl.parse(answer("2024-12-31T20:00Z", "2025-01-01T01:00Z", [(1, 20.0), (2, 21.0), (3, 22.0), (4, 23.0),
                                                                           (5, 0.0)], curve="A01"))

    monkeypatch.setattr(fl, "_request", fake_request)
    monkeypatch.setattr(fl, "EntsoeRawClient", lambda **kw: None)
    monkeypatch.setenv("ENTSO_TOKEN", "x")
    start, end = dt.datetime(2024, 12, 31, 20, tzinfo=UTC), dt.datetime(2025, 1, 1, 0, tzinfo=UTC)
    out = fl.fetch(start, end)
    a = out["actual"]
    # 20:00 served --> 19:00, outside the window; 21:00 --> 20:00; 22:00 --> 21:00; 22:00 has no value; 23:00 stays
    assert a["delivery_start"].dt.strftime("%H:%M").tolist() == ["20:00", "21:00", "23:00"]
    assert a["load"].tolist() == [21.0, 22.0, 23.0]
    assert ("A16", start, end + dt.timedelta(hours=1)) in asked  # one hour more for the end-stamped series
    assert ("A01", start, end) in asked
    assert list(out["forecast"].columns) == ["bidding_zone", "delivery_start", "resolution", "load"]
    assert len(out["forecast"]) == 0
