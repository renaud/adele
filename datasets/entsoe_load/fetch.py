# /// script
# requires-python = ">=3.12"
# dependencies = ["entsoe-py==0.8.1", "pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E total load (document A65) for the bidding zones of the descriptor: the actual
load (process type A16, table `actual`) and the day-ahead forecast (A01, table `forecast`).

Draft by Claude, 2026-11-15 (WP3, step 4). Facts measured before, by the swissgrid project
(`swissgrid_project/data/entsoe/README.md`, download of 2026-10-31, QA 5 c3 and c5):

- CH: one time series per answer, hourly (PT60M), unit MAW (MW, the mean power of the hour),
  curve type A03: a point holds until the next position, so a run of equal values comes as one
  point. The parser expands it; it refuses another unit or curve type.
- The actual load of CH (A16) is stamped at the END of the hour until 2024-12-31 22:00 UTC (as
  served), and at the start from 2024-12-31 23:00 UTC. Evidence: the correlation of its hourly
  changes with Swissgrid's Energy Statistic is 0.996 to 1.000 with the statistic one hour later
  in 2015-2022 (0.90 in 2024), against 0.21 to 0.53 at the same hour; 2023 shows no clear lag
  from January to August. This file moves A16 before that time back by one hour, as the
  swissgrid project did; the hour 2024-12-31 22:00 UTC then has no actual load. The forecast
  (A01) is not moved.
- The day-ahead forecast showed no revision in the swissgrid project's collector (122 hours,
  two runs on 2026-10-28 and 2026-11-01).

Measured on 2026-11-15 (WP3; `docs/work-packages/WP3-versions.md`, "How late ENTSO-E corrects
the load"):

- No correction in 15 days. The raw answers that the swissgrid project downloaded on
  2026-10-31 (one per year, 2015 to 2026-10-31 08:00 UTC) and fresh answers for the same
  windows, parsed by this file: 103,714 hours of A16 and 103,728 of A01 in both, 0 different,
  also for the hours that were less than a day old on 2026-10-31.
- Backfill 2015-01-01 to now on the Mac (12 windows of 365 days, 3 min): 104,079 hours of
  A16, 104,087 of A01, all PT60M, no null. Equal to the swissgrid project's load.parquet
  (`datetime_start`, `value_mw`) on every common hour (103,712 and 103,727).
- Holes: A16 2024-12-31 22:00 UTC (the shift above); A01 2015-08-30 22:00 to 2015-08-31
  21:00 UTC (24 hours, not served).
- A16 far below A01 (the source's values, kept as served): 3,747 MW for 10 hours from
  2023-02-16 23:00 UTC (the same value repeated); about 3,000 MW from 2024-12-04 23:00 to
  2024-12-05 21:00 UTC; nights of 2026-11-03, 11-10 and 11-14 at 2,816 to 3,900 MW, against
  a forecast of about 7,000.
- A request of 365 days comes whole (one time series, 8,760 points).

The HTTP requests go through entsoe-py's raw client (its errors for "no data"), with a timeout
and retries as in `entsoe_day_ahead_prices`; the XML is parsed here, not by entsoe-py.
"""
from __future__ import annotations

import datetime as dt
import os
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from entsoe import EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError

UTC = dt.timezone.utc
ZONES = ["CH"]
SERIES = {"actual": "A16", "forecast": "A01"}  # table --> process type
END_STAMPED_BEFORE = {"CH": dt.datetime(2024, 12, 31, 23, tzinfo=UTC)}  # A16 stamped at the end of the hour before
MAX_SPAN = dt.timedelta(days=365)  # the API serves at most one year per request
LAG = dt.timedelta(days=2)  # a response may end this much before now without counting as cut
TIMEOUT_S = 60
ATTEMPTS = 3
RESOLUTION = {"PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30), "PT60M": pd.Timedelta(hours=1)}
COLUMNS = {"bidding_zone": "object", "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]",
           "load": "float64"}


def parse(xml: str) -> pd.DataFrame:
    """The points of an A65 answer: delivery_start (as served), resolution, load (MW)."""
    root = ET.fromstring(xml)
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    rows = []
    for ts in root.iter(f"{ns}TimeSeries"):
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
                rows += [(start + (k - 1) * res, res, q) for k in range(pos, last)]
    return pd.DataFrame(rows, columns=["delivery_start", "resolution", "load"])


def _request(client: EntsoeRawClient, zone: str, process: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            if process == "A16":
                xml = client.query_load(zone, start=pd.Timestamp(s), end=pd.Timestamp(e))
            else:
                xml = client.query_load_forecast(zone, start=pd.Timestamp(s), end=pd.Timestamp(e), process_type=process)
            break
        except NoMatchingDataError:
            return None
        except requests.Timeout:
            if attempt == ATTEMPTS:
                raise RuntimeError(f"{zone} {process} [{s}, {e}): no answer after {ATTEMPTS} attempts of {TIMEOUT_S} s")
    df = parse(xml)
    return df if len(df) else None


def _one(client: EntsoeRawClient, zone: str, process: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; split in two when the answer ends well before what it should cover (a cut answer)."""
    df = _request(client, zone, process, s, e)
    data_end = None if df is None else (df["delivery_start"] + df["resolution"]).max()
    if df is not None and data_end < min(e, dt.datetime.now(UTC)) - LAG and e - s > dt.timedelta(days=1):
        mid = s + (e - s) / 2
        parts = [p for p in (_one(client, zone, process, s, mid), _one(client, zone, process, mid, e)) if p is not None]
        return pd.concat(parts, ignore_index=True).drop_duplicates(ignore_index=True) if parts else None
    return df


def _chunks(start: dt.datetime, end: dt.datetime):
    s = start
    while s < end:
        e = min(s + MAX_SPAN, end)
        yield s, e
        s = e


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    client = EntsoeRawClient(api_key=os.environ["ENTSO_TOKEN"], timeout=TIMEOUT_S)
    jobs = []
    for table, process in SERIES.items():
        for zone in ZONES:
            # an end-stamped hour is served one hour later than the hour it covers: ask one hour more
            shifted = process == "A16" and zone in END_STAMPED_BEFORE and start < END_STAMPED_BEFORE[zone]
            ask_end = end + dt.timedelta(hours=1) if shifted else end
            jobs += [(table, zone, process, cs, ce) for cs, ce in _chunks(start, ask_end)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda j: (j[0], j[1], j[2], _one(client, *j[1:])), jobs))
    out = {}
    for table in SERIES:
        frames = []
        for t, zone, process, df in answers:
            if t != table or df is None:
                continue
            df = df.assign(bidding_zone=zone)
            if process == "A16" and zone in END_STAMPED_BEFORE:
                early = df["delivery_start"] < END_STAMPED_BEFORE[zone]
                df.loc[early, "delivery_start"] -= pd.Timedelta(hours=1)
            frames.append(df)
        df = pd.concat(frames, ignore_index=True) if frames else _empty()
        df = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)]
        # chunks may meet inside one answer's day: keep one copy of identical rows
        out[table] = df[list(COLUMNS)].drop_duplicates(ignore_index=True).astype(COLUMNS)
    return out
