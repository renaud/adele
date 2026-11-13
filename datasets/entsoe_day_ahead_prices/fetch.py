"""Fetch ENTSO-E day-ahead prices (document A44) for the bidding zones of the descriptor.

Measured on 2026-11-13 (scratch measurements, ENTSO-E Transparency Platform API):

- Resolution depends on the zone: FR 15 min from delivery day 2025-09-30, DE_LU (sequence 1)
  from 2025-10-01, CH from 2026-11-04. Each row carries its `resolution`.
- DE_LU publishes two series: sequence 1 (the SDAC auction, hourly then 15 min) and sequence 2
  (15 min since 2018). Without a sequence filter each timestamp comes twice. We keep sequence 1.
- Responses are cut without an error. A one-year request returned 100 days (100 daily time
  series); a 90-day request for FR (2026-06-26 to 2026-09-24) returned 73 days, although the
  days after exist. So requests span at most 90 days, and a response whose data ends before
  min(requested end, now) is split in two and asked again, down to one day.
- entsoe-py's pandas client is not used: before 2025-10-01 it resamples every series to
  hourly with `.first()`, which would keep only the first quarter-hour of FR on 2025-09-30.
- The raw client has no timeout by default: on 2026-11-13 a request of the backfill waited
  28 minutes without an answer. Each request now has a timeout and is retried.
"""
from __future__ import annotations

import datetime as dt
import os
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from entsoe import EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError
from entsoe.parsers import _extract_timeseries, parse_prices

UTC = dt.timezone.utc
# zone --> (first, end) of validity as UTC instants, and the sequence to request
ZONES = {
    "CH": (None, None, None),
    "FR": (None, None, None),
    "DE_AT_LU": (None, dt.datetime(2018, 9, 30, 22, tzinfo=UTC), None),  # ended with delivery day 2018-09-30
    "DE_LU": (dt.datetime(2018, 9, 30, 22, tzinfo=UTC), None, 1),
}
MAX_SPAN = dt.timedelta(days=90)
TIMEOUT_S = 60
ATTEMPTS = 3
RESOLUTION = {"15min": pd.Timedelta(minutes=15), "30min": pd.Timedelta(minutes=30), "60min": pd.Timedelta(hours=1)}


def _chunks(start: dt.datetime, end: dt.datetime):
    s = start
    while s < end:
        e = min(s + MAX_SPAN, end)
        yield s, e
        s = e


def _one(client: EntsoeRawClient, zone: str, seq: int | None, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    df = _request(client, zone, seq, s, e)
    expected_end = min(e, dt.datetime.now(UTC))
    data_end = None if df is None else (df["delivery_start"] + df["resolution"]).max()
    if df is not None and data_end < expected_end and e - s > dt.timedelta(days=1):
        mid = s + (e - s) / 2
        parts = [p for p in (_one(client, zone, seq, s, mid), _one(client, zone, seq, mid, e)) if p is not None]
        return pd.concat(parts, ignore_index=True).drop_duplicates(ignore_index=True) if parts else None
    return df


def _request(client: EntsoeRawClient, zone: str, seq: int | None, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            xml = client.query_day_ahead_prices(zone, start=pd.Timestamp(s), end=pd.Timestamp(e), sequence=seq)
            break
        except NoMatchingDataError:
            return None
        except requests.Timeout:
            if attempt == ATTEMPTS:
                raise RuntimeError(f"{zone} [{s}, {e}): no answer after {ATTEMPTS} attempts of {TIMEOUT_S} s")
    n_series = len(list(_extract_timeseries(xml)))
    if n_series >= 100:
        raise RuntimeError(f"{zone} [{s}, {e}): {n_series} time series in one response, it may be truncated")
    frames = []
    for res, ser in parse_prices(xml).items():
        if len(ser):
            frames.append(pd.DataFrame({"bidding_zone": zone, "delivery_start": ser.index.tz_convert("UTC"),
                                        "resolution": RESOLUTION[res], "price": ser.values.astype("float64")}))
    return pd.concat(frames, ignore_index=True) if frames else None


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    client = EntsoeRawClient(api_key=os.environ["ENTSO_TOKEN"], timeout=TIMEOUT_S)
    jobs = []
    for zone, (first, last, seq) in ZONES.items():
        s = max(start, first) if first else start
        e = min(end, last) if last else end
        jobs += [(zone, seq, cs, ce) for cs, ce in _chunks(s, e)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        parts = [p for p in pool.map(lambda j: _one(client, *j), jobs) if p is not None]
    if not parts:
        return pd.DataFrame({"bidding_zone": pd.Series(dtype="object"),
                             "delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                             "resolution": pd.Series(dtype="timedelta64[ns]"),
                             "price": pd.Series(dtype="float64")})
    df = pd.concat(parts, ignore_index=True)
    # chunks overlap at their borders (the API returns whole days): keep one copy of identical rows
    return df.drop_duplicates(ignore_index=True)
