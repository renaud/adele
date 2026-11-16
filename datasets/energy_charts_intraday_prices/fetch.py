# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the hourly intraday prices of CH and DE from the year files behind Energy-Charts' chart.

Source: https://www.energy-charts.info/charts/price_spot_market/data/<ch|de>/year_<year>.json,
no key. A list of series (`name`: a label per language, `data`: one value or null per stamp) and
one hourly axis (`xAxisValues`, unix ms, UTC, start of the hour). The files are rewritten in place
(Last-Modified of 2026-07-31 for every CH file, 2026-10-26 to 2026-10-27 for the DE files).
Parser after SED (`sources/eu_energy_charts/build.py`) and swissgrid_project
(`code/da_id_spread_de/fetch_energy_charts_de.py`).

Measured on 2026-11-15 (all year files 2015-2026 of both countries, scratch measurements):

- Every file has an hourly axis from 00:00 local on 1 January (23:00 UTC the day before) to the end
  of the year, 8,760 or 8,784 stamps; the file of the current year runs to tomorrow, with nulls
  after the last value.
- Series kept (EUR/MWh): Intraday Continuous Average, Low and High Price (CH and DE, 2015-), ID3
  (DE, from 2015-06-28 local) and ID1 (DE, from 2018-02-05 local), Intraday Auction IDA1 and IDA2
  (CH, 2020-2025), "Intraday auction, average of the 15 min auctions" (DE, to 2024-06-13).
  DE series are labelled (DE-AT-LU) in 2015-2017, (DE-AT-LU, DE-LU) in 2018 and (DE-LU) from 2019:
  the rows take DE_AT_LU before 2018-10-01 00:00 local and DE_LU after, as entsoe_day_ahead_prices.
- Series left out: the day-ahead prices (CH to 2026-11-03, DE-LU to 2025-09-30 in these files;
  after that the auction runs in quarter-hours and the files stop carrying it). They equal
  entsoe_day_ahead_prices at shift 0 in 99.97 % of DE hours and in all CH hours except 277 hours of
  2015, 4,140 hours of 2017 and 22 hours of 2018-09-21. In 2015 and 2017 ENTSO-E's CH is the one
  that is one hour late: its hourly changes follow DE_AT_LU's at a lag of one hour from May to
  October 2017, where Energy-Charts' CH follows them at lag 0 (and the intraday average fits
  Energy-Charts' day-ahead at lag 0 in every month). Also left out: Day Ahead Auction
  (IT-North-CH) (2015-2017), gas, CO2 and production series.
- Against SED's copy of the CH files (Carlo's download of 2026-10-28): no value of 2019-2026
  changed. But the 2026 file no longer carries IDA1 and IDA2: SED holds 7,223 and 3,612 values of
  2026 that the source dropped between 2026-10-28 and 2026-11-15.
- CH, intraday average: no value from 2020-10-12 07:00 to 2020-12-31 22:00 UTC (a gap of the
  source: low and high stop too) and hours without a trade, null until 2020.
- CH, 2021-2025: 257 hours where the average, the low and the high are all exactly 0.00
  (1 in 2021, 102 in 2022, 113 in 2023, 31 in 2024, 10 in 2025), 214 of them between 00:00 and
  08:00 local. The day-ahead price of those hours: median 236.5 EUR/MWh in 2022, 93.0 in 2023,
  near 0 in only 3 of them. Read as hours without a trade, written as 0 once the null of the
  earlier years stopped; SED's note (the last hour without a trade is 2021-12-21) missed them.
  DE has 4 hours with an average of exactly 0.00, each with a low below 0 or a high above 0:
  real averages, kept.

What this file does:

- Stores an hour whose average, low and high are all exactly 0 as null (no trade), in every zone.

- Keeps each file's rows up to its last stamp with a kept value; the rows after it (the future
  hours of the current year) are dropped. A row before it can be all null (an hour without a
  trade, the gap of 2020).
- Stops on a series that it doesn't know (EUR/MWh), on an axis that is not hourly from 1 January
  00:00 local, on a missing average, low or high price, and on a DE label that doesn't match the
  date. Each needs a person: a new series is a new column, a new axis a new resolution.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from zoneinfo import ZoneInfo

import pandas as pd
import requests

URL = "https://www.energy-charts.info/charts/price_spot_market/data/{country}/year_{year}.json"
UTC = dt.timezone.utc
TZ = ZoneInfo("Europe/Berlin")  # 1 January 00:00 local: the first stamp of a year file (same offsets as Zurich)
FIRST_YEAR = 2015
COUNTRIES = ("ch", "de")
DE_LU_FROM = pd.Timestamp("2018-09-30 22:00", tz="UTC")  # delivery day 2018-10-01: DE_AT_LU --> DE_LU
TIMEOUT_S = 120
ATTEMPTS = 4
KEPT = {  # English series name without its zone label --> column
    "Intraday Continuous Average Price": "id_avg",
    "Intraday Continuous Low Price": "id_low",
    "Intraday Continuous High Price": "id_high",
    "Intraday Continuous ID3-Price": "id3",
    "Intraday Continuous ID1-Price": "id1",
    "Intraday Auction IDA1-Price": "ida1",
    "Intraday Auction IDA2-Price": "ida2",
    "Intraday auction, average of the 15 min auctions": "ida15",
}
REQUIRED = ("id_avg", "id_low", "id_high")
LEFT_OUT = ("Day Ahead Auction", "Gas (NCG, THE)", "2 × Gas + 0.4 × CO2")  # EUR/MWh series not kept (prefixes)
LABELS = {"ch": {None}, "de": {"DE-AT-LU", "DE-AT-LU, DE-LU", "DE-LU"}}
PRICES = list(dict.fromkeys(KEPT.values()))
COLUMNS = ["bidding_zone", "delivery_start", *PRICES]


def english(name) -> str | None:
    """`name` is {"en": ...}, or a list of such dicts in some files."""
    if isinstance(name, dict):
        return name.get("en")
    if isinstance(name, list):
        return next((e for e in map(english, name) if e), None)
    return name


def split_label(name: str) -> tuple[str, str | None]:
    """'Intraday Continuous Low Price (DE-LU)' --> ('Intraday Continuous Low Price', 'DE-LU')."""
    m = re.fullmatch(r"(.*?) \(([^()]*)\)", name)
    return (m[1], m[2]) if m else (name, None)


def parse_year(js: list, country: str, year: int) -> pd.DataFrame:
    """One year file --> rows (bidding_zone, delivery_start, prices...)."""
    axes = [s["xAxisValues"] for s in js if s.get("xAxisValues")]
    if not axes:
        raise RuntimeError(f"{country} {year}: no time axis")
    t = pd.to_datetime(pd.Series(axes[0]), unit="ms", utc=True)
    first = pd.Timestamp(dt.datetime(year, 1, 1, tzinfo=TZ)).tz_convert("UTC")
    if t.iloc[0] != first or not (t.diff().dropna() == pd.Timedelta(hours=1)).all():
        raise RuntimeError(f"{country} {year}: the axis is not hourly from {first} (steps "
                           f"{t.diff().dropna().value_counts().to_dict()}); a new resolution needs a decision")
    df = pd.DataFrame({"delivery_start": t})
    labels = {}
    for s in js:
        name = english(s.get("name"))
        if s.get("unit") != "EUR/MWh" or name is None:
            continue
        base, label = split_label(name)
        if base not in KEPT:
            if name.startswith(LEFT_OUT):
                continue
            raise RuntimeError(f"{country} {year}: unknown price series {name!r}; decide whether it becomes a column")
        if label not in LABELS[country]:
            raise RuntimeError(f"{country} {year}: {name!r}: zone label {label!r} not expected")
        col = KEPT[base]
        if col in df:
            raise RuntimeError(f"{country} {year}: two series for {col}")
        if len(s["data"]) != len(t):
            raise RuntimeError(f"{country} {year}: {name!r}: {len(s['data'])} values for {len(t)} stamps")
        values = pd.to_numeric(pd.Series(s["data"], dtype="object"), errors="coerce")
        if values.isna().sum() != sum(v is None for v in s["data"]):
            raise RuntimeError(f"{country} {year}: {name!r}: a value that is not a number")
        df[col] = values.astype("float64")
        labels[col] = label
    missing = [c for c in REQUIRED if c not in df]
    if missing:
        raise RuntimeError(f"{country} {year}: series {missing} not in the file")
    no_trade = (df["id_avg"] == 0) & (df["id_low"] == 0) & (df["id_high"] == 0)
    df.loc[no_trade, list(REQUIRED)] = float("nan")  # an hour without a trade, written as 0 from 2021 (docstring)
    for col in PRICES:
        if col not in df:
            df[col] = float("nan")
    if country == "ch":
        df.insert(0, "bidding_zone", "CH")
    else:
        df.insert(0, "bidding_zone", (df["delivery_start"] >= DE_LU_FROM).map({True: "DE_LU", False: "DE_AT_LU"}))
        for col, label in labels.items():
            has = df[col].notna()
            if label == "DE-AT-LU" and (has & (df["delivery_start"] >= DE_LU_FROM)).any() or \
               label == "DE-LU" and (has & (df["delivery_start"] < DE_LU_FROM)).any():
                raise RuntimeError(f"{country} {year}: {col} labelled {label} holds values of the other zone")
    any_value = df[PRICES].notna().any(axis=1)
    if not any_value.any():
        return df.iloc[0:0][COLUMNS]
    last = df.loc[any_value, "delivery_start"].max()
    return df.loc[df["delivery_start"] <= last, COLUMNS].reset_index(drop=True)


def _get(session: requests.Session, url: str) -> requests.Response:
    """GET with retries on connection errors, HTTP 429 and 5xx. Other statuses (404) come back as they are."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = session.get(url, timeout=TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == ATTEMPTS:
                raise
            wait = 10 * attempt
        else:
            if r.status_code != 429 and r.status_code < 500:
                return r
            if attempt == ATTEMPTS:
                r.raise_for_status()
            ra = r.headers.get("Retry-After", "")
            wait = int(ra) if ra.isdigit() else 10 * attempt
        time.sleep(wait)
    raise AssertionError("unreachable")


def years(start: dt.datetime, end: dt.datetime, now: dt.datetime) -> list[int]:
    """The local years whose file can hold rows of [start, end), from FIRST_YEAR to the current year."""
    lo = max(start.astimezone(TZ).year, FIRST_YEAR)
    hi = min((end - dt.timedelta(microseconds=1)).astimezone(TZ).year, now.astimezone(TZ).year)
    return list(range(lo, hi + 1))


def fetch(start: dt.datetime, end: dt.datetime, now: dt.datetime | None = None) -> pd.DataFrame:
    now = now or dt.datetime.now(UTC)
    session = requests.Session()
    frames = []
    for country in COUNTRIES:
        for year in years(start, end, now):
            r = _get(session, URL.format(country=country, year=year))
            if r.status_code == 404 and year == now.astimezone(TZ).year and now.astimezone(TZ).timetuple().tm_yday <= 3:
                continue  # the file of a new year may appear a day or two late
            r.raise_for_status()
            frames.append(parse_year(r.json(), country, year))
    if not frames:
        return pd.DataFrame({"bidding_zone": pd.Series(dtype="object"),
                             "delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                             **{c: pd.Series(dtype="float64") for c in PRICES}})
    return pd.concat(frames, ignore_index=True)
