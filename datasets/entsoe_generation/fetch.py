# /// script
# requires-python = ">=3.12"
# dependencies = ["entsoe-py==0.8.1", "pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E actual generation per production type (document A75, process type A16) for CH.

Draft by Claude, 2026-11-15 (WP5.2). Measured on raw answers of 2026-11-15 (2026-11-01 to now,
and the year 2025), and taken from the swissgrid project's download of 2026-10-31
(`swissgrid_project/data/entsoe/README.md`):

- One time series per production type, hourly (PT60M), unit MAW (MW, the mean power of the
  hour), curve type A03 (a point holds until the next position; the parser expands it), business
  type A01, `inBiddingZone_Domain` CH. No consumption series (`outBiddingZone_Domain`) for CH:
  the parser refuses one, and refuses a production type that the descriptor doesn't declare.
- Types: solar B16 and wind onshore B19 from 2015-01-01, nuclear B14 from 2015-04-21, hydro
  pumped storage B10 and water reservoir B12 from 2015-07-01, run-of-river B11 from 2015-10-13,
  fossil gas B04 only from 2015-01-17 to 2015-10-08.
- A request of 365 days comes whole: 2025 gave 52,560 hours (8,760 x 6 types) in 15 s. A week
  takes as long (about 15 s): the time is the platform's, not the size.
- Revised (`qa/revisions_entsoe_ch.md`): 36 of 608,417 values changed between 2026-10-31 and
  2026-11-15, 33 of them less than 2 days old (the first values of the last hours), 2 at 2 to 7
  days, one at 93 days (2026-07-30 18:00 UTC, +105 MW). The answer carries no document status.
- No document field that changes at each answer is returned (createdDateTime, mRID): with
  `revisions: append-only`, each fetch would store every row again.

The HTTP requests go through entsoe-py's raw client (its errors for "no data"), with a timeout
and retries; the XML is parsed here. The token never appears in an error text: requests puts
the URL, token included, in its messages.
"""
from __future__ import annotations

import datetime as dt
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from entsoe import EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError, PaginationError

UTC = dt.timezone.utc
ZONES = {"CH": "10YCH-SWISSGRIDZ"}
TYPES = {  # ENTSO-E psrType --> production_type (the categories of the descriptor)
    "B04": "fossil_gas",
    "B10": "hydro_pumped_storage",
    "B11": "hydro_run_of_river",
    "B12": "hydro_reservoir",
    "B14": "nuclear",
    "B16": "solar",
    "B19": "wind_onshore",
}
MAX_SPAN = dt.timedelta(days=365)  # the API serves at most one year per request
LAG = dt.timedelta(days=2)  # a response may end this much before now without counting as cut
TIMEOUT_S = 120
ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
RESOLUTION = {"PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30), "PT60M": pd.Timedelta(hours=1)}
COLUMNS = {"bidding_zone": "object", "production_type": "object", "delivery_start": "datetime64[ns, UTC]",
           "resolution": "timedelta64[ns]", "generation": "float64"}


def _points(period: ET.Element, ns: str, curve: str) -> list[tuple[pd.Timestamp, pd.Timedelta, float]]:
    """(start, resolution, quantity) of each interval of a Period; A03 holds a value until the next point."""
    start = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}start")).tz_convert("UTC")
    end = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}end")).tz_convert("UTC")
    res_text = period.findtext(f"{ns}resolution")
    if res_text not in RESOLUTION:
        raise RuntimeError(f"resolution {res_text!r}")
    res = RESOLUTION[res_text]
    n = int((end - start) / res)
    points = sorted((int(p.findtext(f"{ns}position")), float(p.findtext(f"{ns}quantity")))
                    for p in period.iter(f"{ns}Point"))
    rows = []
    for i, (pos, q) in enumerate(points):
        last = (points[i + 1][0] if i + 1 < len(points) else n + 1) if curve == "A03" else pos + 1
        rows += [(start + (k - 1) * res, res, q) for k in range(pos, last)]
    return rows


def parse(xml: str, zone: str = "CH") -> pd.DataFrame:
    """The points of an A75 answer: production_type, delivery_start (as served), resolution, generation (MW)."""
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
        if ts.find(f"{ns}outBiddingZone_Domain.mRID") is not None:
            raise RuntimeError("a consumption series (outBiddingZone_Domain): not handled")
        area = ts.findtext(f"{ns}inBiddingZone_Domain.mRID")
        if area != ZONES[zone]:
            raise RuntimeError(f"bidding zone {area!r}, expected {ZONES[zone]} ({zone})")
        psr = ts.findtext(f"{ns}MktPSRType/{ns}psrType")
        if psr not in TYPES:
            raise RuntimeError(f"production type {psr!r}: not in the descriptor")
        for period in ts.iter(f"{ns}Period"):
            rows += [(TYPES[psr], *p) for p in _points(period, ns, curve)]
    return pd.DataFrame(rows, columns=["production_type", "delivery_start", "resolution", "generation"])


def _clean(e: Exception) -> str:
    return str(e).replace(os.environ.get("ENTSO_TOKEN") or "\0", "***")[:300]


def _request(client: EntsoeRawClient, zone: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            xml = client.query_generation(zone, start=pd.Timestamp(s), end=pd.Timestamp(e))
            break
        except NoMatchingDataError:
            return None
        except PaginationError:  # too large: _one splits the window
            raise
        except Exception as ex:  # noqa: BLE001 - its text, or the error it chains, may hold the URL with the token
            status = getattr(getattr(ex, "response", None), "status_code", None)
            transient = isinstance(ex, (requests.Timeout, requests.ConnectionError)) or status in RETRY_STATUS
            if not transient or attempt == ATTEMPTS:
                raise RuntimeError(f"{zone} A75 [{s}, {e}): {type(ex).__name__} {_clean(ex)}") from None
            time.sleep(5 * attempt)
    df = parse(xml, zone)
    return df if len(df) else None


def _one(client: EntsoeRawClient, zone: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; split in two when the answer ends well before what it should cover (a cut answer)
    or when the platform refuses it as too large."""
    try:
        df = _request(client, zone, s, e)
    except PaginationError:
        df, too_large = None, True
    else:
        too_large = False
    data_end = None if df is None else (df["delivery_start"] + df["resolution"]).max()
    cut = df is not None and data_end < min(e, dt.datetime.now(UTC)) - LAG
    if (too_large or cut) and e - s > dt.timedelta(days=1):
        mid = _floor_hour(s + (e - s) / 2)
        parts = [p for p in (_one(client, zone, s, mid), _one(client, zone, mid, e)) if p is not None]
        return pd.concat(parts, ignore_index=True).drop_duplicates(ignore_index=True) if parts else None
    if too_large:
        raise RuntimeError(f"{zone} A75 [{s}, {e}): refused as too large, even for one day")
    return df


def _floor_hour(t: dt.datetime) -> dt.datetime:
    return t.replace(minute=0, second=0, microsecond=0)


def _ceil_hour(t: dt.datetime) -> dt.datetime:
    f = _floor_hour(t)
    return f if f == t else f + dt.timedelta(hours=1)


def _chunks(start: dt.datetime, end: dt.datetime):
    """Whole hours (entsoe-py rounds a time to the nearest hour), at most MAX_SPAN each."""
    s, end = _floor_hour(start), _ceil_hour(end)
    while s < end:
        e = min(s + MAX_SPAN, end)
        yield s, e
        s = e


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    client = EntsoeRawClient(api_key=os.environ["ENTSO_TOKEN"], timeout=TIMEOUT_S)
    jobs = [(zone, cs, ce) for zone in ZONES for cs, ce in _chunks(start, end)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda j: (j[0], _one(client, *j)), jobs))
    frames = [df.assign(bidding_zone=zone) for zone, df in answers if df is not None]
    df = pd.concat(frames, ignore_index=True) if frames else _empty()
    df = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)]
    # chunks may meet inside one answer's period: keep one copy of identical rows
    return df[list(COLUMNS)].drop_duplicates(ignore_index=True).astype(COLUMNS)
