# /// script
# requires-python = ">=3.12"
# dependencies = ["entsoe-py==0.8.1", "pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E wind and solar generation forecasts (document A69, article 14.1.D) for the
areas of AREAS: day-ahead (process type A01), intraday (A40) and current (A18), each production
type that the answer holds (solar B16, wind offshore B18, wind onshore B19).

The same file serves two datasets: `entsoe_wind_solar_forecast` (CH) and
`entsoe_wind_solar_forecast_neighbours` (16 areas). The two files differ only in AREAS
(server/tests/test_entsoe_wind_solar_forecast_fetch.py checks it).

Draft by Claude, 2026-11-15 (WP5.3).

The fetch: one request per area, process type and year at most (MAX_SPAN). Each answer is cut to
its own window, so that two answers never hold the same key. A window is asked again in two
halves when the API refuses it as too large, or when a production type ends more than LAG
before the end of the window or before now (an answer cut without an error, as the prices were:
skills/common-traps.md). DE_AT_LU is not asked after 2018-09-30 22:00 UTC, when the zone ended.

Measured on 2026-11-15, raw answers (kept in the session's scratchpad only):

- One TimeSeries per production type; holes split it into several Periods (IT_NORD intraday,
  July 2024 to June 2025: 29 Periods per type). Curve type A03 in every answer (a value holds
  until the next point), unit MAW (MW), business type A94 solar and A93 wind. No position twice
  in a Period, no key twice in an answer.
- A request of one year comes whole: CH day-ahead 2025, 8,757 hours per type (the 3 missing
  hours are holes of the platform, below); DE_TENNET day-ahead and current 2025, 3 x 35,040
  quarter-hours. An answer took 6 to 17 s (evening).
- CH: current (A18) is "no data" for 2025, as in every year of the swissgrid project's download
  (swissgrid_project/data/entsoe/README.md). Intraday (A40) starts 2025-03-31 22:00 UTC.
- Resolutions: CH PT60M. In the swissgrid project's download of the neighbours: Germany and AT
  PT15M; FR PT60M until 2026-01-08 22:00 UTC, then PT15M; IT PT60M until 2024-12-31 22:00 UTC and
  the Italian zones until 2024-12-30 23:00 UTC, then PT15M. No quarter-hour falls inside an hour
  of the same series, and the key (area, process type, production type, start) is unique
  (235,094 rows for CH, 22,423,581 for the neighbours).

Versions. The day-ahead and intraday forecasts are fixed once published, the current forecast
is updated (ENTSO-E, Detailed Data Descriptions v3r4, p. 66). Of the 235,094 Swiss values that
the swissgrid project downloaded on 2026-10-31, 3 differ in adele's backfill of 2026-11-15:
day-ahead wind, 2026-10-26 23:00 to 2026-10-27 01:00 UTC, 4.875 --> 4.65 MW and two similar
(qa/revisions_entsoe_ch.md found the same three). The project's collector of forecast versions
(two runs, 2026-10-28 and 2026-11-01) saw one version of each hour; its 438 A69 values equal
adele's except those three.

Backfill on the Mac (2026-11-15), CH from 2014-12-31 23:00 UTC: 236,584 rows in 12 windows of a
year, 4 min. Holes as published: day-ahead 75 hours per type (the warnings of the descriptor),
intraday 2 hours.

Neighbours, the same evening: 22,567,278 rows in 12 windows of a year, 4 to 5 min each with 4
requests at a time. Two windows (2024 and 2025) failed at first: the API answered HTTP 599
("Unable to access service within time limit") while three other sessions backfilled ENTSO-E
series with the same token. Hence the retries of an answer 5xx; the two windows passed at the
second backfill. The error text of requests holds the URL with the token: _request removes it
(it reached a log of the session before this was fixed). Against the swissgrid project's download
of 2026-11-01: every key it holds is in adele; values differ only for delivery from October 2026
(587 current, 229 day-ahead, no intraday), that is updates of recent and future values.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from entsoe import EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError, PaginationError

UTC = dt.timezone.utc
# --- the only part that differs between the two datasets ---------------------------------------
AREAS = {  # area --> EIC code of its domain
    "DE_LU": "10Y1001A1001A82H", "DE_AT_LU": "10Y1001A1001A63L", "DE_50HZ": "10YDE-VE-------2",
    "DE_AMPRION": "10YDE-RWENET---I", "DE_TENNET": "10YDE-EON------1", "DE_TRANSNETBW": "10YDE-ENBW-----N",
    "FR": "10YFR-RTE------C", "AT": "10YAT-APG------L", "IT": "10YIT-GRTN-----B", "IT_NORD": "10Y1001A1001A73I",
    "IT_CNOR": "10Y1001A1001A70O", "IT_CSUD": "10Y1001A1001A71M", "IT_SUD": "10Y1001A1001A788",
    "IT_SICI": "10Y1001A1001A75E", "IT_SARD": "10Y1001A1001A74G", "IT_CALA": "10Y1001C--00096J",
}
# --- end of the part that differs ----------------------------------------------------------------
ENDS = {"DE_AT_LU": dt.datetime(2018, 9, 30, 22, tzinfo=UTC)}  # an area that ended: not asked after
FORECAST_TYPES = {"A01": "day_ahead", "A40": "intraday", "A18": "current"}  # process type --> forecast_type
PRODUCTION_TYPES = {"B16": "solar", "B18": "wind_offshore", "B19": "wind_onshore"}  # psrType --> production_type
MAX_SPAN = dt.timedelta(days=365)  # the API serves at most one year per request
LAG = dt.timedelta(days=2)  # a series may end this much before now without counting as cut
MIN_SPAN = dt.timedelta(days=1)  # a window is not split below this length
TIMEOUT_S = 60
ATTEMPTS = 4
RETRY_S = 20  # wait before attempt n + 1: n x RETRY_S
WORKERS = 4
RESOLUTION = {"PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30), "PT60M": pd.Timedelta(hours=1)}
KEY = ["area", "forecast_type", "production_type", "delivery_start"]
COLUMNS = {"area": "object", "forecast_type": "object", "production_type": "object",
           "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]", "generation": "float64"}


class TooLarge(Exception):
    """The API refused the window as too large: ask two halves."""


def parse(xml: str) -> pd.DataFrame:
    """The points of an A69 answer: production_type, delivery_start, resolution, generation (MW)."""
    root = ET.fromstring(xml)
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    rows = []
    for ts in root.iter(f"{ns}TimeSeries"):
        psr = ts.findtext(f"{ns}MktPSRType/{ns}psrType")
        if psr not in PRODUCTION_TYPES:
            raise RuntimeError(f"production type {psr!r}, expected one of {sorted(PRODUCTION_TYPES)}")
        unit = ts.findtext(f"{ns}quantity_Measure_Unit.name")
        if unit != "MAW":
            raise RuntimeError(f"unit {unit!r}, expected MAW (MW)")
        curve = ts.findtext(f"{ns}curveType") or "A01"
        if curve not in ("A01", "A03"):
            raise RuntimeError(f"curve type {curve!r}, expected A01 or A03")
        for period in ts.iter(f"{ns}Period"):
            start = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}start")).tz_convert("UTC")
            end = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}end")).tz_convert("UTC")
            res_text = period.findtext(f"{ns}resolution")
            if res_text not in RESOLUTION:
                raise RuntimeError(f"resolution {res_text!r}")
            res = RESOLUTION[res_text]
            n = int((end - start) / res)
            points = sorted((int(p.findtext(f"{ns}position")), float(p.findtext(f"{ns}quantity")))
                            for p in period.iter(f"{ns}Point"))
            for i, (pos, q) in enumerate(points):
                # A03: the value holds until the next point (or the end of the period); A01: one position
                last = (points[i + 1][0] if i + 1 < len(points) else n + 1) if curve == "A03" else pos + 1
                rows += [(PRODUCTION_TYPES[psr], start + (k - 1) * res, res, q) for k in range(pos, last)]
    return pd.DataFrame(rows, columns=["production_type", "delivery_start", "resolution", "generation"])


def _redact(text: str) -> str:
    """The text of an error without the token: requests puts the URL, token included, in its messages."""
    token = os.environ.get("ENTSO_TOKEN")
    text = re.sub(r"securityToken=[^&\s'\"]+", "securityToken=***", text)
    return text.replace(token, "***") if token else text


def _request(client: EntsoeRawClient, eic: str, process: str, s: dt.datetime, e: dt.datetime) -> str | None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return client.query_wind_and_solar_forecast(eic, start=pd.Timestamp(s), end=pd.Timestamp(e),
                                                        process_type=process)
        except NoMatchingDataError:
            return None
        except PaginationError as err:
            raise TooLarge(_redact(str(err))) from None
        except requests.RequestException as err:
            status = getattr(err.response, "status_code", None)
            # a timeout, a lost connection or an answer 5xx (599: "Unable to access service within time
            # limit", seen when several backfills ran at once): try again; any other answer is an error
            if (isinstance(err, (requests.Timeout, requests.ConnectionError)) or (status or 0) >= 500) and attempt < ATTEMPTS:
                time.sleep(RETRY_S * attempt)
                continue
            # `from None`: the chained traceback would print the URL with the token
            raise RuntimeError(f"{eic} {process} [{s}, {e}): {type(err).__name__} after {attempt} attempts: "
                               f"{_redact(str(err))}") from None
    return None


def _halves(client, area, process, s, e) -> pd.DataFrame | None:
    mid = s + (e - s) / 2
    parts = [p for p in (_one(client, area, process, s, mid), _one(client, area, process, mid, e)) if p is not None]
    return pd.concat(parts, ignore_index=True) if parts else None


def _one(client: EntsoeRawClient, area: str, process: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request, cut to [s, e). Split in two when the API refuses it as too large, or when a
    production type ends well before the end of the window (an answer cut without an error)."""
    try:
        xml = _request(client, AREAS[area], process, s, e)
    except TooLarge:
        if e - s <= MIN_SPAN:
            raise
        return _halves(client, area, process, s, e)
    if xml is None:
        return None
    df = parse(xml)
    df = df[(df["delivery_start"] >= s) & (df["delivery_start"] < e)]
    if df.empty:
        return None
    ends = (df["delivery_start"] + df["resolution"]).groupby(df["production_type"]).max()
    if (ends < min(e, dt.datetime.now(UTC)) - LAG).any() and e - s > MIN_SPAN:
        return _halves(client, area, process, s, e)
    return df


def _chunks(start: dt.datetime, end: dt.datetime):
    s = start
    while s < end:
        e = min(s + MAX_SPAN, end)
        yield s, e
        s = e


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    client = EntsoeRawClient(api_key=os.environ["ENTSO_TOKEN"], timeout=TIMEOUT_S)
    jobs = [(area, process, cs, ce)
            for area in AREAS if start < ENDS.get(area, end)
            for process in FORECAST_TYPES
            for cs, ce in _chunks(start, min(end, ENDS.get(area, end)))]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(lambda j: (j[0], j[1], _one(client, *j)), jobs))
    frames = [df.assign(area=area, forecast_type=FORECAST_TYPES[process])
              for area, process, df in answers if df is not None]
    if not frames:
        return _empty()
    df = pd.concat(frames, ignore_index=True)[list(COLUMNS)].drop_duplicates(ignore_index=True)
    dup = df[df.duplicated(KEY, keep=False)]
    if len(dup):
        raise RuntimeError(f"{len(dup)} rows share a key with different values, e.g.\n{dup.head(4).to_string()}")
    return df.astype(COLUMNS)
