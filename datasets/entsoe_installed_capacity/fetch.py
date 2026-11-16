# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E installed generation capacity per production type (document A68, article
14.1.A, process type A33 "year ahead") of the Swiss bidding zone: one row per type and calendar
year.

Draft by Claude, 2026-11-15 (WP5.1). Facts measured before by the swissgrid project
(`swissgrid_project/data/entsoe/README.md`, download of 2026-10-31):

- CH serves four types only: B10 hydro pumped storage, B11 run-of-river, B12 reservoir, B14
  nuclear. No solar, no wind, no thermal. 2015 to 2026: 48 values.
- No value changed between 2026-10-31 and 2026-11-15 (`qa/revisions_entsoe_ch.md`).

Measured on 2026-11-15 (WP5.1):

- A request must not span more than one year ("must not span more than one year" for 2015 to
  2027 in one request). Each year is asked alone: [1 January 00:00, next 1 January 00:00) in
  Europe/Zurich, which is the period that the answer carries (P1Y from 23:00 or 22:00 UTC of
  the day before).
- 2014 answers "no data".
- The platform fills the years to come with the latest values: 2027 and 2028 answer the values
  of 2026 (6,702.2, 632.4, 5,798.9 and 2,983 MW) on 2026-11-15. A year that has not started yet
  is therefore not asked: its value would be a copy, not a publication. The value of a new year
  is fetched from its first day.
- Curve type A03, one point per year, unit MAW (MW).
"""
from __future__ import annotations

import datetime as dt
import os
import time
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd
import requests

API = "https://web-api.tp.entsoe.eu/api"
TZ = ZoneInfo("Europe/Zurich")
UTC = dt.timezone.utc
AREAS = {"CH": "10YCH-SWISSGRIDZ"}
FIRST_YEAR = 2015  # 2014 answers "no data"
TIMEOUT_S = 120
ATTEMPTS = 4
KEY = ["area", "psr_type", "delivery_year"]
COLUMNS = {"area": "object", "psr_type": "object", "delivery_year": "object", "capacity": "float64"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _get(session: requests.Session, token: str, label: str, params: dict, s: dt.datetime,
         e: dt.datetime) -> bytes | None:
    """The XML document of one answer, or None for "no matching data"."""
    query = {"securityToken": token, **params, "periodStart": f"{s:%Y%m%d%H%M}", "periodEnd": f"{e:%Y%m%d%H%M}"}
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = session.get(API, params=query, timeout=TIMEOUT_S)
        except requests.RequestException as exc:  # its message holds the URL, with the token: not shown
            if attempt == ATTEMPTS:
                raise RuntimeError(f"{label} [{s}, {e}): {type(exc).__name__} after {ATTEMPTS} attempts") from None
            time.sleep(2 ** attempt)
            continue
        # 429 and any 5xx: wait and ask again (HTTP 599 "Unable to access service within time limit" seen 2026-11-15)
        if (r.status_code == 429 or r.status_code >= 500) and attempt < ATTEMPTS:
            time.sleep(2 ** (attempt + 1))
            continue
        break
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise RuntimeError(f"{label} [{s}, {e}): HTTP {r.status_code}, not XML") from None
    if _local(root.tag).startswith("Acknowledgement"):
        reason = " ".join(x.text or "" for x in root.iter() if _local(x.tag) == "text")
        if "No matching data found" in reason:
            return None
        raise RuntimeError(f"{label} [{s}, {e}): HTTP {r.status_code}: {reason[:300]}")
    if r.status_code != 200:
        raise RuntimeError(f"{label} [{s}, {e}): HTTP {r.status_code}")
    return r.content


def parse(doc: bytes, year: int) -> list[tuple]:
    """The values of one A68 answer for one year: (psr_type, delivery_year, capacity)."""
    root = ET.fromstring(doc)
    rows = []
    for ts in (x for x in root.iter() if _local(x.tag) == "TimeSeries"):
        f = {_local(x.tag): (x.text or "").strip() for x in ts.iter() if len(x) == 0 and x is not ts}
        if f.get("quantity_Measure_Unit.name") != "MAW":
            raise RuntimeError(f"unit {f.get('quantity_Measure_Unit.name')!r}, expected MAW (MW)")
        psr = f.get("psrType")
        if not psr:
            raise RuntimeError("a time series without psrType")
        for period in (x for x in ts if _local(x.tag) == "Period"):
            p = {_local(x.tag): x.text for x in period.iter() if len(x) == 0}
            if p["resolution"] != "P1Y":
                raise RuntimeError(f"resolution {p['resolution']!r}, expected P1Y")
            start = pd.Timestamp(p["start"]).tz_convert(TZ)
            if (start.year, start.month, start.day, start.hour, start.minute) != (year, 1, 1, 0, 0):
                raise RuntimeError(f"{psr}: a period that starts at {p['start']}, expected 1 January {year} local")
            points = [x for x in period if _local(x.tag) == "Point"]
            if len(points) != 1:
                raise RuntimeError(f"{psr} {year}: {len(points)} points, expected 1")
            q = float(next(x.text for x in points[0] if _local(x.tag) == "quantity"))
            rows.append((psr, dt.date(year, 1, 1), q))
    return rows


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    token = os.environ["ENTSO_TOKEN"]
    session = requests.Session()
    now = dt.datetime.now(UTC)
    first = max(start.astimezone(TZ).year, FIRST_YEAR)
    last = (end - dt.timedelta(microseconds=1)).astimezone(TZ).year
    rows = []
    for year in range(first, last + 1):
        s = dt.datetime(year, 1, 1, tzinfo=TZ).astimezone(UTC)
        e = dt.datetime(year + 1, 1, 1, tzinfo=TZ).astimezone(UTC)
        if s > now:  # the platform copies the latest values into the years to come
            break
        for area, eic in AREAS.items():
            doc = _get(session, token, f"A68 {area}", {"documentType": "A68", "processType": "A33", "in_Domain": eic},
                       s, e)
            if doc is not None:
                rows += [(area, *r) for r in parse(doc, year)]
    if not rows:
        return _empty()
    df = pd.DataFrame(rows, columns=list(COLUMNS)).astype(COLUMNS)
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        raise RuntimeError(f"{int(dup.sum())} rows share their key, e.g. {df.loc[dup, KEY].iloc[0].tolist()}")
    return df.sort_values(KEY, ignore_index=True)
