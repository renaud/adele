# /// script
# requires-python = ">=3.12"
# dependencies = ["entsoe-py==0.8.1", "pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E physical flows (document A11) on the borders of CH, in both directions.

Draft by Claude, 2026-11-15 (WP5.2). Measured on raw answers of 2026-11-15 (2026-11-08 to now
for every border and direction, the year 2025 for DE and DE_LU), and taken from the swissgrid
project's download of 2026-10-31 (`swissgrid_project/data/entsoe/README.md`, QA 7b):

- One time series per border and direction, business type A66, unit MAW (MW, the mean power of
  the interval), curve type A03 (a point holds until the next position; the parser expands it).
  AT, FR, IT hourly (PT60M) from 2015-01-01; DE (the country, 10Y1001A1001A83F) from
  2015-02-01, at PT15M from 2021-08-01 22:00 UTC.
- The values are gross flows per direction: in the week of 2026-11-08, both directions of the
  DE border were above 0 in 658 of 756 quarter-hours (IT 17 of 189 hours, FR 5, AT 0). So the
  table keeps both directions on one row (`from_ch`, `to_ch`); the net flow is their difference.
- Only the country DE is asked for the German border, not the bidding zone DE_LU: the two are
  identical except in 2025, where 24,782 of 35,040 quarter-hours differ (DE_LU often 0 where DE
  is not), and DE agrees with Swissgrid's Energy Statistic in every year (median |difference|
  1.6 to 7 MW), DE_LU not in 2025 (272 MW). Asking both would count the border twice.
- A request of 365 days comes whole (DE 2025: 35,040 quarter-hours in 10 s). A week takes as long
  (5 to 11 s per request): the time is the platform's, not the size.
- Revised (`qa/revisions_entsoe_ch.md`, 2025-2026 only): 6,398 of 352,896 values changed between
  2026-10-31 and 2026-11-15: 6,215 at 1 to 12 months, 134 at 7 to 30 days, 49 under 2 days. None
  older than a year.
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
EIC = {"CH": "10YCH-SWISSGRIDZ", "DE": "10Y1001A1001A83F", "FR": "10YFR-RTE------C", "IT": "10YIT-GRTN-----B",
       "AT": "10YAT-APG------L"}
BORDERS = ["DE", "FR", "IT", "AT"]
DIRECTIONS = {"from_ch": lambda nb: ("CH", nb), "to_ch": lambda nb: (nb, "CH")}  # column --> (from, to)
MAX_SPAN = dt.timedelta(days=365)  # the API serves at most one year per request
LAG = dt.timedelta(days=2)  # a response may end this much before now without counting as cut
TIMEOUT_S = 120
ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
RESOLUTION = {"PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30), "PT60M": pd.Timedelta(hours=1)}
COLUMNS = {"border": "object", "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]",
           "from_ch": "float64", "to_ch": "float64"}


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


def parse(xml: str, frm: str, to: str) -> pd.DataFrame:
    """The points of an A11 answer for the flow frm --> to: delivery_start, resolution, flow (MW)."""
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
        got = (ts.findtext(f"{ns}out_Domain.mRID"), ts.findtext(f"{ns}in_Domain.mRID"))
        if got != (EIC[frm], EIC[to]):
            raise RuntimeError(f"domains out {got[0]!r}, in {got[1]!r}; expected {frm} --> {to}")
        for period in ts.iter(f"{ns}Period"):
            rows += _points(period, ns, curve)
    return pd.DataFrame(rows, columns=["delivery_start", "resolution", "flow"])


def _clean(e: Exception) -> str:
    return str(e).replace(os.environ.get("ENTSO_TOKEN") or "\0", "***")[:300]


def _request(client: EntsoeRawClient, frm: str, to: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            xml = client.query_crossborder_flows(frm, to, start=pd.Timestamp(s), end=pd.Timestamp(e))
            break
        except NoMatchingDataError:
            return None
        except PaginationError:  # too large: _one splits the window
            raise
        except Exception as ex:  # noqa: BLE001 - its text, or the error it chains, may hold the URL with the token
            status = getattr(getattr(ex, "response", None), "status_code", None)
            transient = isinstance(ex, (requests.Timeout, requests.ConnectionError)) or status in RETRY_STATUS
            if not transient or attempt == ATTEMPTS:
                raise RuntimeError(f"A11 {frm} --> {to} [{s}, {e}): {type(ex).__name__} {_clean(ex)}") from None
            time.sleep(5 * attempt)
    df = parse(xml, frm, to)
    return df if len(df) else None


def _one(client: EntsoeRawClient, frm: str, to: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; split in two when the answer ends well before what it should cover (a cut answer)
    or when the platform refuses it as too large."""
    try:
        df = _request(client, frm, to, s, e)
    except PaginationError:
        df, too_large = None, True
    else:
        too_large = False
    data_end = None if df is None else (df["delivery_start"] + df["resolution"]).max()
    cut = df is not None and data_end < min(e, dt.datetime.now(UTC)) - LAG
    if (too_large or cut) and e - s > dt.timedelta(days=1):
        mid = _floor_hour(s + (e - s) / 2)
        parts = [p for p in (_one(client, frm, to, s, mid), _one(client, frm, to, mid, e)) if p is not None]
        return pd.concat(parts, ignore_index=True).drop_duplicates(ignore_index=True) if parts else None
    if too_large:
        raise RuntimeError(f"A11 {frm} --> {to} [{s}, {e}): refused as too large, even for one day")
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


def common_grid(sides: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Bring the two directions to the same intervals. Where, in one hour, a direction is served at
    a finer resolution than the other (not seen for A11 up to 2026-11-15; seen for A09), the
    coarser value (a mean power) is repeated in each finer interval: the energy and the hourly
    mean stay exact."""
    starts = pd.concat([s[["delivery_start", "resolution"]] for s in sides], ignore_index=True)
    finest = starts.groupby(starts["delivery_start"].dt.floor("h"))["resolution"].min()
    out = []
    for s in sides:
        s = s.reset_index(drop=True)
        if s.empty:
            out.append(s)
            continue
        step = pd.Series(finest.reindex(s["delivery_start"].dt.floor("h")).to_numpy(), index=s.index)
        coarse = s["resolution"] > step
        if coarse.any():
            c, c_step = s[coarse], step[coarse]
            n = (c["resolution"] / c_step).astype(int)
            rep = c.loc[c.index.repeat(n)].copy()
            k = rep.groupby(level=0).cumcount().to_numpy()
            rep_step = pd.to_timedelta(c_step.loc[rep.index].to_numpy())
            rep["delivery_start"] = pd.DatetimeIndex(rep["delivery_start"]) + k * rep_step
            rep["resolution"] = rep_step
            s = pd.concat([s[~coarse], rep], ignore_index=True).sort_values("delivery_start", ignore_index=True)
        out.append(s)
    return out


def wide(parts: dict[str, list[pd.DataFrame]], border: str) -> pd.DataFrame:
    """The two directions of one border on one row per interval, on a common grid (common_grid).
    Refuses an interval served twice (the key is border and delivery_start)."""
    sides = []
    for col in DIRECTIONS:
        frames = [f for f in parts.get(col, []) if f is not None]
        df = (pd.concat(frames, ignore_index=True).drop_duplicates(ignore_index=True) if frames
              else pd.DataFrame({"delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                                 "resolution": pd.Series(dtype="timedelta64[ns]"), "flow": pd.Series(dtype="float64")}))
        sides.append(df.rename(columns={"flow": col}))
    sides = common_grid(sides)
    df = sides[0].merge(sides[1], on=["delivery_start", "resolution"], how="outer")
    dup = df["delivery_start"].duplicated(keep=False)
    if dup.any():
        t = df.loc[dup, "delivery_start"].min()
        raise RuntimeError(f"border {border}: {int(dup.sum())} rows share a delivery_start with another "
                           f"resolution or value, the first at {t}")
    return df.assign(border=border)


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    client = EntsoeRawClient(api_key=os.environ["ENTSO_TOKEN"], timeout=TIMEOUT_S)
    jobs = [(nb, col, *DIRECTIONS[col](nb), cs, ce) for nb in BORDERS for col in DIRECTIONS
            for cs, ce in _chunks(start, end)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda j: (j[0], j[1], _one(client, *j[2:])), jobs))
    frames = []
    for nb in BORDERS:
        parts: dict[str, list[pd.DataFrame]] = {}
        for border, col, df in answers:
            if border == nb:
                parts.setdefault(col, []).append(df)
        frames.append(wide(parts, nb))
    df = pd.concat(frames, ignore_index=True) if frames else _empty()
    df = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)]
    return df[list(COLUMNS)].astype(COLUMNS).sort_values(["border", "delivery_start"], ignore_index=True)
