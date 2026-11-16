"""datasets/energy_charts_intraday_prices/fetch.py on synthetic year files: the series kept and left out, the German
zone before and after 2018-10-01, the hours written as 0 without a trade, the future hours of the current year, and
the stops (unknown series, axis, label). No network: the files are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

FETCH = Path(__file__).resolve().parents[2] / "datasets" / "energy_charts_intraday_prices" / "fetch.py"
UTC = dt.timezone.utc


@pytest.fixture
def ec():
    spec = importlib.util.spec_from_file_location("energy_charts_intraday_prices_fetch", FETCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def year_file(year: int, series: dict[str, list], hours: int | None = None, step_h: int = 1) -> list:
    """A year file: an hourly axis from 1 January 00:00 local, and one entry per series (name as a list of labels)."""
    first = pd.Timestamp(f"{year}-01-01", tz="Europe/Berlin").tz_convert("UTC")
    n = hours or len(pd.date_range(first, pd.Timestamp(f"{year + 1}-01-01", tz="Europe/Berlin").tz_convert("UTC"), freq="h", inclusive="left"))
    axis = [int((first + pd.Timedelta(hours=i * step_h)).timestamp() * 1000) for i in range(n)]
    out = [{"name": [{"en": "Load"}], "xAxisValues": axis, "data": [1.0] * n, "unit": None}]
    for name, values in series.items():
        data = (values * n)[:n] if len(values) < n else values[:n]
        out.append({"name": [{"en": name, "de": name}], "unit": "EUR/MWh", "data": data})
    return out


CH = {"Intraday Continuous Average Price": [10.0], "Intraday Continuous Low Price": [5.0],
      "Intraday Continuous High Price": [15.0], "Day Ahead Auction (CH)": [9.0], "Day Ahead Auction (IT-North-CH)": [8.0],
      "Intraday Auction IDA1-Price": [11.0], "Gas (NCG, THE)": [30.0]}


def test_ch_keeps_intraday_and_leaves_out_day_ahead_and_gas(ec):
    df = ec.parse_year(year_file(2023, CH), "ch", 2023)
    assert list(df.columns) == ec.COLUMNS
    assert len(df) == 8760 and (df["bidding_zone"] == "CH").all()
    assert (df["ida1"] == 11.0).all() and df["id3"].isna().all()
    assert df["delivery_start"].iloc[0] == pd.Timestamp("2022-12-31 23:00", tz="UTC")


def test_hour_written_as_zero_is_null(ec):
    series = dict(CH)
    for k in ("Intraday Continuous Average Price", "Intraday Continuous Low Price", "Intraday Continuous High Price"):
        series[k] = [0.0, 0.0] + [7.0] * 8758
    series["Intraday Continuous Low Price"] = [0.0, -1.0] + [7.0] * 8758  # hour 2: a real average of 0, kept
    df = ec.parse_year(year_file(2023, series), "ch", 2023)
    assert df.loc[0, ["id_avg", "id_low", "id_high"]].isna().all()
    assert df.loc[1, "id_avg"] == 0.0


def test_future_hours_of_the_current_year_are_dropped(ec):
    series = {"Intraday Continuous Average Price": [10.0] * 100 + [None] * 8660,
              "Intraday Continuous Low Price": [5.0] * 100 + [None] * 8660,
              "Intraday Continuous High Price": [15.0] * 100 + [None] * 8660}
    series["Intraday Continuous Average Price"][50] = None  # an hour without a trade inside stays, as null
    df = ec.parse_year(year_file(2026, series), "ch", 2026)
    assert len(df) == 100 and df["id_avg"].isna().sum() == 1


def test_germany_switches_zone_on_2018_10_01(ec):
    s = {f"{k} (DE-AT-LU, DE-LU)": [1.0] for k in ("Intraday Continuous Average Price", "Intraday Continuous Low Price",
                                                    "Intraday Continuous High Price", "Intraday Continuous ID3-Price")}
    df = ec.parse_year(year_file(2018, s), "de", 2018)
    last_at = df.loc[df["bidding_zone"] == "DE_AT_LU", "delivery_start"].max()
    first_lu = df.loc[df["bidding_zone"] == "DE_LU", "delivery_start"].min()
    assert last_at == pd.Timestamp("2018-09-30 21:00", tz="UTC") and first_lu == pd.Timestamp("2018-09-30 22:00", tz="UTC")
    assert (df["id3"] == 1.0).all()


def test_a_label_that_does_not_match_the_date_is_refused(ec):
    s = {f"{k} (DE-AT-LU)": [1.0] for k in ("Intraday Continuous Average Price", "Intraday Continuous Low Price",
                                            "Intraday Continuous High Price")}
    with pytest.raises(RuntimeError, match="other zone"):
        ec.parse_year(year_file(2019, s), "de", 2019)


@pytest.mark.parametrize("change, msg", [
    (lambda js: js.append({"name": {"en": "Intraday Continuous ID2-Price"}, "unit": "EUR/MWh", "data": [1.0] * 8760}), "unknown price series"),
    (lambda js: js.pop(1), "not in the file"),
    (lambda js: js.__setitem__(1, {**js[1], "name": {"en": "Intraday Continuous Average Price (FR)"}}), "zone label"),
])
def test_stops_that_need_a_person(ec, change, msg):
    js = year_file(2023, CH)
    change(js)
    with pytest.raises(RuntimeError, match=msg):
        ec.parse_year(js, "ch", 2023)


def test_an_axis_that_is_not_hourly_is_refused(ec):
    with pytest.raises(RuntimeError, match="not hourly"):
        ec.parse_year(year_file(2023, CH, hours=100, step_h=2), "ch", 2023)


def test_years_and_a_missing_file(ec, monkeypatch):
    now = dt.datetime(2027, 1, 2, 12, tzinfo=UTC)
    assert ec.years(dt.datetime(2010, 1, 1, tzinfo=UTC), dt.datetime(2016, 1, 1, tzinfo=UTC), now) == [2015, 2016]  # 2015-12-31 23:00 UTC is in the 2016 file
    assert ec.years(dt.datetime(2026, 12, 31, 22, tzinfo=UTC), dt.datetime(2027, 6, 1, tzinfo=UTC), now) == [2026, 2027]

    class R:
        def __init__(self, status, js=None):
            self.status_code, self._js = status, js

        def json(self):
            return self._js

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    def fake_get(session, url):  # the file of 2027 isn't there yet on 2 January
        return R(404) if "2027" in url else R(200, year_file(2026, CH if "/ch/" in url else {
            f"{k} (DE-LU)": [1.0] for k in ("Intraday Continuous Average Price", "Intraday Continuous Low Price",
                                            "Intraday Continuous High Price")}))

    monkeypatch.setattr(ec, "_get", fake_get)
    df = ec.fetch(dt.datetime(2026, 12, 31, 20, tzinfo=UTC), dt.datetime(2027, 1, 2, tzinfo=UTC), now=now)
    assert set(df["bidding_zone"]) == {"CH", "DE_LU"}
    with pytest.raises(RuntimeError, match="404"):
        ec.fetch(dt.datetime(2026, 12, 31, 20, tzinfo=UTC), dt.datetime(2027, 1, 2, tzinfo=UTC),
                 now=dt.datetime(2027, 1, 10, tzinfo=UTC))
