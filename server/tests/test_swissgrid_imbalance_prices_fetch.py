"""datasets/swissgrid_imbalance_prices/fetch.py on synthetic files: the names of the monthly files, the local months
of a window, the parser (units, offsets, a whole month), the dual and the single price, and where fetch finds a month
(the page, the zip of its year, or nowhere yet). No network: the page and the files are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

FETCH = Path(__file__).resolve().parents[2] / "datasets" / "swissgrid_imbalance_prices" / "fetch.py"
UTC = dt.timezone.utc


@pytest.fixture
def sg():
    spec = importlib.util.spec_from_file_location("swissgrid_imbalance_prices_fetch", FETCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def month_xml(sg, month: dt.date, series: dict[str, float], unit: str = "ct/kWh", drop_last: bool = False) -> bytes:
    """A price notice for one month: every quarter-hour of the local month, each series at a constant value."""
    start = sg._month_start_utc(month)
    end = sg._month_start_utc(sg._next_month(month))
    stamps = pd.date_range(start, end, freq="15min", inclusive="left")
    if drop_last:
        stamps = stamps[:-1]
    parts = []
    for title, value in series.items():
        points = "".join(f"<DATAVALUE><TIME>{t.tz_convert('Europe/Zurich').isoformat()}</TIME><VALUE>{value:.6f}</VALUE></DATAVALUE>"
                         for t in stamps)
        parts.append(f"<timeSeries><Report_TS_Titel_en>{title}</Report_TS_Titel_en><unit>{unit}</unit>"
                     f"<timeSeriesData>{points}</timeSeriesData></timeSeries>")
    return (f'<?xml version="1.0" encoding="ISO-8859-1" ?><template><printedAt>2026-01-01T00:00:00+01:00</printedAt>'
            f"<timeSeriesGroup><timeSeriesGroupLink>{''.join(parts)}</timeSeriesGroupLink></timeSeriesGroup></template>").encode()


def test_month_of_reads_page_and_zip_names(sg):
    assert sg.month_of("swissgrid-prices-for-imbalance-energy-260101-260201.xml") == dt.date(2026, 1, 1)
    assert sg.month_of("swissgrid-prices-for-balance-energy-251201-260101.xml") == dt.date(2025, 12, 1)
    assert sg.month_of("swissgrid-prices-for-balance-energy_240101-240201.xml") == dt.date(2024, 1, 1)
    assert sg.month_of("swissgrid-prices-for-imbalance-energy-260101-260201.xlsx") is None
    assert sg.month_of("balance-energy-2025.zip") is None
    with pytest.raises(RuntimeError, match="one month"):
        sg.month_of("swissgrid-prices-for-imbalance-energy-260101-260301.xml")


def test_months_are_local_and_clipped(sg):
    now = dt.datetime(2026, 11, 15, tzinfo=UTC)
    # 2026-02-28 23:30 UTC is 2026-03-01 00:30 local: March only
    assert sg.months(dt.datetime(2026, 2, 28, 23, 30, tzinfo=UTC), dt.datetime(2026, 3, 2, tzinfo=UTC), now) == [dt.date(2026, 3, 1)]
    assert sg.months(dt.datetime(2020, 1, 1, tzinfo=UTC), dt.datetime(2023, 2, 1, tzinfo=UTC), now)[0] == dt.date(2023, 1, 1)
    assert sg.months(dt.datetime(2026, 11, 1, tzinfo=UTC), dt.datetime(2027, 3, 1, tzinfo=UTC), now)[-1] == dt.date(2026, 11, 1)
    assert sg.months(dt.datetime(2020, 1, 1, tzinfo=UTC), dt.datetime(2022, 12, 31, 23, tzinfo=UTC), now) == []


def test_parse_converts_ct_per_kwh_exactly_and_covers_the_clock_change(sg):
    df = sg.parse_xml(month_xml(sg, dt.date(2026, 3, 1), {"BG-AEP": 171.93}), "m.xml", dt.date(2026, 3, 1))
    assert len(df) == 2972  # 31 days less one hour
    assert (df["price"] == 1719.3).all()
    assert df["delivery_start"].min() == pd.Timestamp("2026-02-28 23:00", tz="UTC")


@pytest.mark.parametrize("kw, msg", [({"unit": "EUR/MWh"}, "unit"), ({"drop_last": True}, "quarter-hours")])
def test_parse_refuses_a_wrong_unit_or_a_short_month(sg, kw, msg):
    with pytest.raises(RuntimeError, match=msg):
        sg.parse_xml(month_xml(sg, dt.date(2026, 4, 1), {"BG-AEP": 10.0}, **kw), "m.xml", dt.date(2026, 4, 1))


def test_parse_refuses_an_unknown_series_and_a_stamp_of_another_month(sg):
    with pytest.raises(RuntimeError, match="unknown series"):
        sg.parse_xml(month_xml(sg, dt.date(2026, 4, 1), {"BG-new": 1.0}), "m.xml", dt.date(2026, 4, 1))
    with pytest.raises(RuntimeError, match="outside the month"):
        sg.parse_xml(month_xml(sg, dt.date(2026, 4, 1), {"BG-AEP": 1.0}), "m.xml", dt.date(2026, 5, 1))


def test_dual_and_single_price(sg):
    dual = sg.parse_xml(month_xml(sg, dt.date(2025, 7, 1), {"BG-long": 1.0, "BG-short": 3.0, "BG-AEP": 2.0}), "a", dt.date(2025, 7, 1))
    single = sg.parse_xml(month_xml(sg, dt.date(2026, 1, 1), {"BG-AEP": 5.0}), "b", dt.date(2026, 1, 1))
    old = sg.parse_xml(month_xml(sg, dt.date(2024, 1, 1), {"BG-long": 1.0, "BG-short": 3.0}), "c", dt.date(2024, 1, 1))
    t = sg.to_table(pd.concat([old, dual, single]))
    assert list(t.columns) == sg.COLUMNS
    jul = t[t["delivery_start"] == pd.Timestamp("2025-07-01 12:00", tz="UTC")].iloc[0]
    assert (jul["price_regime"], jul["price_long"], jul["price_short"], jul["price_single"]) == ("dual", 10.0, 30.0, 20.0)
    jan = t[t["delivery_start"] == pd.Timestamp("2026-01-01 12:00", tz="UTC")].iloc[0]
    assert (jan["price_regime"], jan["price_long"], jan["price_short"], jan["price_single"]) == ("single", 50.0, 50.0, 50.0)
    assert t.loc[t["delivery_start"] < pd.Timestamp("2025-01-01", tz="UTC"), "price_single"].isna().all()


def test_long_without_short_is_refused(sg):
    df = sg.parse_xml(month_xml(sg, dt.date(2024, 1, 1), {"BG-long": 1.0}), "c", dt.date(2024, 1, 1))
    with pytest.raises(RuntimeError, match="BG-long without BG-short"):
        sg.to_table(df)


def test_fetch_takes_the_page_then_the_zip_and_waits_for_a_new_month(sg, monkeypatch):
    """2025-12 is in balance-energy-2025.zip, 2026-01 is on the page, 2026-02 has no file yet (not late)."""
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("swissgrid-prices-for-balance-energy-251201-260101.xml",
                    month_xml(sg, dt.date(2025, 12, 1), {"BG-long": 1.0, "BG-short": 2.0}))
    files = {
        sg.PAGE: ('<a href="/dam/jcr:1/swissgrid-prices-for-imbalance-energy-260101-260201.xml">x</a>'
                  '<a href="/dam/jcr:2/balance-energy-2025.zip">y</a>').encode(),
        "https://www.swissgrid.ch/dam/jcr:1/swissgrid-prices-for-imbalance-energy-260101-260201.xml":
            month_xml(sg, dt.date(2026, 1, 1), {"BG-AEP": 4.0}),
        "https://www.swissgrid.ch/dam/jcr:2/balance-energy-2025.zip": z.getvalue(),
    }
    monkeypatch.setattr(sg, "_get", lambda session, url: files[url])
    now = dt.datetime(2026, 3, 10, tzinfo=UTC)
    t = sg.fetch(dt.datetime(2025, 12, 15, tzinfo=UTC), dt.datetime(2026, 3, 1, tzinfo=UTC), now=now)
    assert t["delivery_start"].min() == pd.Timestamp("2025-11-30 23:00", tz="UTC")  # the whole month; the server cuts
    assert t["delivery_start"].max() == pd.Timestamp("2026-01-31 22:45", tz="UTC")
    assert set(t["price_regime"]) == {"dual", "single"}
    with pytest.raises(RuntimeError, match="no price file for 2026-02"):
        sg.fetch(dt.datetime(2026, 2, 1, tzinfo=UTC), dt.datetime(2026, 3, 1, tzinfo=UTC), now=dt.datetime(2026, 4, 20, tzinfo=UTC))
