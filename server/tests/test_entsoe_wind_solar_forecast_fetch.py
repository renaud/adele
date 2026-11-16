"""datasets/entsoe_wind_solar_forecast*/fetch.py on synthetic answers: the parser (production
types, curve type A03), the cut of each answer to its window, the split of a window that the API
refuses or cuts, an area that ended, and that the two datasets share one file apart from AREAS.
No network: entsoe-py is replaced by a stub, the answers are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
import types
from pathlib import Path

import pandas as pd
import pytest
import yaml

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
CH = DATASETS / "entsoe_wind_solar_forecast"
NEIGHBOURS = DATASETS / "entsoe_wind_solar_forecast_neighbours"
UTC = dt.timezone.utc


def load(folder: Path, monkeypatch):
    entsoe = types.ModuleType("entsoe")
    exceptions = types.ModuleType("entsoe.exceptions")

    class NoMatchingDataError(Exception):
        pass

    class PaginationError(Exception):
        pass

    exceptions.NoMatchingDataError = NoMatchingDataError
    exceptions.PaginationError = PaginationError
    entsoe.EntsoeRawClient = object
    entsoe.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "entsoe", entsoe)
    monkeypatch.setitem(sys.modules, "entsoe.exceptions", exceptions)
    spec = importlib.util.spec_from_file_location(f"{folder.name}_fetch", folder / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ws(monkeypatch):
    return load(CH, monkeypatch)


def series(psr: str, start: str, end: str, points: list[tuple[int, float]], curve: str = "A03",
           res: str = "PT60M", unit: str = "MAW") -> str:
    pts = "".join(f"<Point><position>{p}</position><quantity>{q}</quantity></Point>" for p, q in points)
    return (f"<TimeSeries><MktPSRType><psrType>{psr}</psrType></MktPSRType>"
            f"<quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name><curveType>{curve}</curveType>"
            f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
            f"<resolution>{res}</resolution>{pts}</Period></TimeSeries>")


def doc(*ts: str) -> str:
    return ('<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">'
            + "".join(ts) + "</GL_MarketDocument>")


def test_parse_names_the_production_type_and_expands_a03(ws):
    df = ws.parse(doc(series("B16", "2026-06-01T00:00Z", "2026-06-01T04:00Z", [(1, 0.0), (3, 50.0)]),
                      series("B19", "2026-06-01T00:00Z", "2026-06-01T01:00Z", [(1, 1.0), (2, 2.0), (3, 3.0), (4, 4.0)],
                             curve="A01", res="PT15M")))
    solar = df[df["production_type"] == "solar"]
    assert solar["generation"].tolist() == [0.0, 0.0, 50.0, 50.0]
    wind = df[df["production_type"] == "wind_onshore"]
    assert wind["delivery_start"].iloc[1] == pd.Timestamp("2026-06-01T00:15Z")
    assert (wind["resolution"] == pd.Timedelta(minutes=15)).all()


@pytest.mark.parametrize("kw, msg", [({"psr": "B20"}, "production type"), ({"unit": "MWH"}, "unit"),
                                      ({"curve": "A02"}, "curve type"), ({"res": "P1D"}, "resolution")])
def test_unknown_production_type_unit_curve_or_resolution_is_refused(ws, kw, msg):
    args = {"psr": "B16", **kw}
    psr = args.pop("psr")
    with pytest.raises(RuntimeError, match=msg):
        ws.parse(doc(series(psr, "2026-06-01T00:00Z", "2026-06-02T00:00Z", [(1, 1.0)], **args)))


def hourly(psr: str, s: dt.datetime, e: dt.datetime, value: float = 1.0) -> str:
    n = int((e - s) / dt.timedelta(hours=1))
    return series(psr, s.strftime("%Y-%m-%dT%H:%MZ"), e.strftime("%Y-%m-%dT%H:%MZ"),
                  [(i, value) for i in range(1, n + 1)], curve="A01")


def run(mod, monkeypatch, answer, start, end):
    """fetch(start, end) with `answer(eic, process, s, e)` as the API; returns (frame, requests)."""
    asked = []

    def fake_request(client, eic, process, s, e):
        asked.append((eic, process, s, e))
        return answer(eic, process, s, e)

    monkeypatch.setattr(mod, "_request", fake_request)
    monkeypatch.setattr(mod, "EntsoeRawClient", lambda **kw: None)
    monkeypatch.setenv("ENTSO_TOKEN", "x")
    return mod.fetch(start, end), asked


def test_each_answer_is_cut_to_its_window_and_typed(ws, monkeypatch):
    """The API serves whole days: the rows outside [start, end) go, also between two chunks."""
    monkeypatch.setattr(ws, "MAX_SPAN", dt.timedelta(days=1))
    start, end = dt.datetime(2020, 3, 1, 6, tzinfo=UTC), dt.datetime(2020, 3, 2, 18, tzinfo=UTC)

    def answer(eic, process, s, e):
        if process != "A01":
            return None
        day0 = s.replace(hour=0)
        return doc(hourly("B16", day0, day0 + dt.timedelta(days=2), value=s.day))  # whole days, more than asked

    df, asked = run(ws, monkeypatch, answer, start, end)
    assert len([a for a in asked if a[1] == "A01"]) == 2  # two chunks of at most one day
    assert df["delivery_start"].min() == pd.Timestamp(start) and df["delivery_start"].max() == pd.Timestamp(end) - pd.Timedelta(hours=1)
    # each hour once: the first chunk [1 March 06:00, 2 March 06:00) lost its rows after 06:00, which
    # would clash with the second chunk's (another value, so the same key twice: an error)
    assert len(df) == 36
    by_hour = df.set_index("delivery_start")["generation"]
    assert by_hour[pd.Timestamp("2020-03-02T05:00Z")] == 1 and by_hour[pd.Timestamp("2020-03-02T06:00Z")] == 2
    assert list(df.columns) == ["area", "forecast_type", "production_type", "delivery_start", "resolution", "generation"]
    assert set(df["forecast_type"]) == {"day_ahead"} and set(df["area"]) == {"CH"}
    assert str(df["delivery_start"].dtype) == "datetime64[ns, UTC]" and str(df["resolution"].dtype) == "timedelta64[ns]"


def test_nothing_served_gives_an_empty_table_with_the_columns(ws, monkeypatch):
    df, asked = run(ws, monkeypatch, lambda *a: None, dt.datetime(2014, 1, 1, tzinfo=UTC), dt.datetime(2014, 1, 3, tzinfo=UTC))
    assert len(df) == 0 and list(df.columns) == list(ws.COLUMNS)
    assert {a[1] for a in asked} == {"A01", "A40", "A18"}


def test_a_window_refused_as_too_large_is_asked_in_halves(ws, monkeypatch):
    start, end = dt.datetime(2020, 1, 1, tzinfo=UTC), dt.datetime(2020, 1, 5, tzinfo=UTC)

    def answer(eic, process, s, e):
        if process != "A01":
            return None
        if e - s > dt.timedelta(days=2):
            raise ws.TooLarge("too many")
        return doc(hourly("B16", s, e))

    df, asked = run(ws, monkeypatch, answer, start, end)
    assert len(df) == 96
    assert [(a[2].day, a[3].day) for a in asked if a[1] == "A01"] == [(1, 5), (1, 3), (3, 5)]


def test_a_production_type_that_ends_early_splits_the_window(ws, monkeypatch):
    """An answer cut without an error: wind ends after 10 days of a 40-day window, solar is whole."""
    start, end = dt.datetime(2020, 1, 1, tzinfo=UTC), dt.datetime(2020, 2, 10, tzinfo=UTC)

    def answer(eic, process, s, e):
        if process != "A01":
            return None
        cut = min(e, s + dt.timedelta(days=10))
        return doc(hourly("B16", s, e), hourly("B19", s, cut))

    df, asked = run(ws, monkeypatch, answer, start, end)
    wind = df[df["production_type"] == "wind_onshore"]
    assert len(wind) == 40 * 24  # the halves, and their halves, complete what the first answer cut
    assert len([a for a in asked if a[1] == "A01"]) > 1


def test_rows_that_share_a_key_with_different_values_are_an_error(ws, monkeypatch):
    s0 = dt.datetime(2020, 1, 1, tzinfo=UTC)

    def answer(eic, process, s, e):
        if process != "A01":
            return None
        return doc(hourly("B16", s0, s0 + dt.timedelta(hours=2), 1.0), hourly("B16", s0, s0 + dt.timedelta(hours=2), 2.0))

    with pytest.raises(RuntimeError, match="share a key"):
        run(ws, monkeypatch, answer, s0, s0 + dt.timedelta(hours=2))


class FakeClient:
    """Answers each call with the next item of `answers`: a text, or an exception to raise."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def query_wind_and_solar_forecast(self, eic, start, end, process_type):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def http_error(status: int):
    import requests
    resp = requests.Response()
    resp.status_code = status
    url = "https://web-api.tp.entsoe.eu/api?documentType=A69&securityToken=SECRET-TOKEN&periodStart=202401010000"
    return requests.HTTPError(f"{status} Server Error: for url: {url}", response=resp)


def test_an_answer_5xx_is_asked_again(ws, monkeypatch):
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    s0 = dt.datetime(2020, 1, 1, tzinfo=UTC)
    client = FakeClient([http_error(599), http_error(503), doc(hourly("B16", s0, s0 + dt.timedelta(hours=2)))])
    assert ws.parse(ws._request(client, "eic", "A01", s0, s0 + dt.timedelta(hours=2)))["generation"].tolist() == [1.0, 1.0]
    assert client.calls == 3


@pytest.mark.parametrize("status", [599, 400])
def test_an_error_never_shows_the_token(ws, monkeypatch, status):
    """requests puts the URL in its message, and the URL holds the token: adele stores error texts."""
    monkeypatch.setattr(ws.time, "sleep", lambda s: None)
    monkeypatch.setenv("ENTSO_TOKEN", "SECRET-TOKEN")
    client = FakeClient([http_error(status)] * ws.ATTEMPTS)
    s0 = dt.datetime(2020, 1, 1, tzinfo=UTC)
    with pytest.raises(RuntimeError) as err:
        ws._request(client, "eic", "A01", s0, s0 + dt.timedelta(hours=2))
    assert "SECRET-TOKEN" not in str(err.value) and "securityToken=***" in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__  # no chained traceback with the URL
    assert client.calls == (ws.ATTEMPTS if status >= 500 else 1)


def test_an_area_that_ended_is_not_asked_after_its_end(monkeypatch):
    nb = load(NEIGHBOURS, monkeypatch)
    end_de_at_lu = nb.ENDS["DE_AT_LU"]
    _, asked = run(nb, monkeypatch, lambda *a: None, end_de_at_lu, end_de_at_lu + dt.timedelta(days=1))
    assert nb.AREAS["DE_AT_LU"] not in {a[0] for a in asked}
    assert nb.AREAS["DE_LU"] in {a[0] for a in asked}
    _, asked = run(nb, monkeypatch, lambda *a: None, end_de_at_lu - dt.timedelta(days=1), end_de_at_lu + dt.timedelta(days=1))
    assert {a[3] for a in asked if a[0] == nb.AREAS["DE_AT_LU"]} == {end_de_at_lu}  # asked up to its end only


def _without_areas(text: str) -> str:
    return re.sub(r"# --- the only part that differs.*?# --- end of the part that differs", "", text, flags=re.S)


def test_the_two_datasets_share_one_fetch_py_apart_from_the_areas():
    ch, nb = (p.joinpath("fetch.py").read_text() for p in (CH, NEIGHBOURS))
    assert "# --- end of the part that differs" in ch and _without_areas(ch) == _without_areas(nb)


def test_the_areas_of_each_fetch_py_are_the_categories_of_its_descriptor(monkeypatch):
    for folder in (CH, NEIGHBOURS):
        mod = load(folder, monkeypatch)
        desc = yaml.safe_load(folder.joinpath("datapackage.yaml").read_text())
        fields = {f["name"]: f for f in desc["resources"][0]["schema"]["fields"]}
        assert [c["value"] for c in fields["area"]["categories"]] == list(mod.AREAS)
        assert [c["value"] for c in fields["forecast_type"]["categories"]] == list(mod.FORECAST_TYPES.values())
        assert sorted(c["value"] for c in fields["production_type"]["categories"]) == sorted(mod.PRODUCTION_TYPES.values())
        assert [f["name"] for f in desc["resources"][0]["schema"]["fields"]] == list(mod.COLUMNS)
