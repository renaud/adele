# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the ENTSO-E current balancing state of the Swiss control area (document A86, business
type B33 "Area Control error (ACE)", EB GL article 12.3.a): one value per minute, with the sign
set from the direction served.

Draft by Claude, 2026-11-15 (WP5.1). Facts measured before by the swissgrid project
(`swissgrid_project/data/entsoe/README.md`, download of 2026-10-31):

- The series runs from 2019-09-30 22:00 to 2025-06-18 08:44 UTC; none before October 2019 and
  from July 2025. 10,371 minutes are missing in between.
- It is the closed-loop control error, not the imbalance: its 15-minute mean follows -FRCE of
  Swissgrid's control-area file (correlation 0.94 at lag 0, -0.15 and -0.21 at -1 and +1
  quarter-hour, Nov 2024 to Jun 2025, 21,956 quarter-hours, slope 0.95) and not the total
  imbalance (A86) or Swissgrid's TSI (correlation -0.01 and 0.09).
- Its direction codes run opposite to those of A86: A01 goes with FRCE import (the control area
  short). This file sets control_error = -value for A01, +value for A02, 0 for A03 (every A03
  value is 0), so that > 0 means long, like TSI.
- 211 minutes above 1,000 MW on six days, e.g. 1,500 to 2,700 MW on 2023-11-28 08:00-10:30 UTC
  and up to 4,000 MW on 2024-07-13 19:00-21:15 UTC, while aFRR and mFRR energy stayed below
  350 MW: kept as served. Against ENTSO-E's LFC reports (2026-11-16,
  `qa/published_figures_entsoe_balancing_state.md`): the spike of 2023-11-28 is not in
  Swissgrid's FRCE (an error of this publication), the one of 2024-07-13 is.

Measured on 2026-11-15 (WP5.1):

- One request may span one year at most ("larger than maximum allowed period 'P1Y'"). A
  one-year answer comes whole but is large (2024: 193 MB of XML, 54 s, 257,864 time series):
  this file asks for 31 days at a time.
- The series still ends on 2025-06-18 08:45 UTC; 2026-06-01 to 2026-11-15 answers "no data".
- Each run of minutes with one direction is its own time series (curve type A03: a point holds
  until the next position, or the end of the period); unit MAW (MW).
"""
from __future__ import annotations

import datetime as dt
import io
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

API = "https://web-api.tp.entsoe.eu/api"
UTC = dt.timezone.utc
AREAS = {"CH": "10YCH-SWISSGRIDZ"}
SIGN = {"A01": -1.0, "A02": 1.0, "A03": 0.0}  # direction --> sign of control_error (> 0 = long)
MAX_SPAN = dt.timedelta(days=31)
LAG = dt.timedelta(days=2)  # an answer may end this much before now without counting as cut
TIMEOUT_S = 180
ATTEMPTS = 4
RESOLUTION = {"PT1M": pd.Timedelta(minutes=1), "PT15M": pd.Timedelta(minutes=15)}
KEY = ["area", "delivery_start"]
COLUMNS = {"area": "object", "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]",
           "direction": "object", "control_error": "float64"}


class TooLarge(Exception):
    """The API refused the window as too long or too large: ask its two halves."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _get(session: requests.Session, token: str, label: str, params: dict, s: dt.datetime,
         e: dt.datetime) -> list[bytes] | None:
    """The XML documents of one answer, or None for "no matching data"."""
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
    body = r.content
    if body[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            return [z.read(n) for n in sorted(z.namelist())]
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise RuntimeError(f"{label} [{s}, {e}): HTTP {r.status_code}, not XML") from None
    if _local(root.tag).startswith("Acknowledgement"):
        reason = " ".join(x.text or "" for x in root.iter() if _local(x.tag) == "text")
        if "No matching data found" in reason:
            return None
        if "exceed" in reason or "maximum allowed period" in reason or "must not span" in reason:
            raise TooLarge(reason)
        raise RuntimeError(f"{label} [{s}, {e}): HTTP {r.status_code}: {reason[:300]}")
    if r.status_code != 200:
        raise RuntimeError(f"{label} [{s}, {e}): HTTP {r.status_code}")
    return [body]


def parse(doc: bytes) -> list[tuple]:
    """The points of one A86 B33 document: (delivery_start, resolution, direction, control_error)."""
    root = ET.fromstring(doc)
    rows = []
    for ts in (x for x in root.iter() if _local(x.tag) == "TimeSeries"):
        f = {_local(x.tag): (x.text or "").strip() for x in ts if len(x) == 0}
        if f.get("businessType") != "B33":
            raise RuntimeError(f"business type {f.get('businessType')!r}, expected B33")
        if f.get("quantity_Measure_Unit.name") != "MAW":
            raise RuntimeError(f"unit {f.get('quantity_Measure_Unit.name')!r}, expected MAW (MW)")
        direction = f.get("flowDirection.direction")
        if direction not in SIGN:
            raise RuntimeError(f"direction {direction!r}, expected A01, A02 or A03")
        curve = f.get("curveType", "A01")
        if curve not in ("A01", "A03"):
            raise RuntimeError(f"curve type {curve!r}, expected A01 or A03")
        for period in (x for x in ts if _local(x.tag) == "Period"):
            p = {_local(x.tag): x.text for x in period.iter() if len(x) == 0}
            start = pd.Timestamp(p["start"]).tz_convert("UTC")
            end = pd.Timestamp(p["end"]).tz_convert("UTC")
            if p["resolution"] not in RESOLUTION:
                raise RuntimeError(f"resolution {p['resolution']!r}")
            res = RESOLUTION[p["resolution"]]
            n = int((end - start) / res)
            pts = sorted((int(v["position"]), float(v["quantity"]))
                         for v in ({_local(x.tag): x.text for x in pt} for pt in period if _local(pt.tag) == "Point"))
            for i, (pos, q) in enumerate(pts):  # A03: a point holds until the next point
                if q < 0:
                    raise RuntimeError(f"negative quantity {q} at {start + (pos - 1) * res}: the sign comes from the direction")
                last = (pts[i + 1][0] if i + 1 < len(pts) else n + 1) if curve == "A03" else pos + 1
                rows += [(start + (k - 1) * res, res, direction, SIGN[direction] * q) for k in range(pos, last)]
    return rows


def _frame(docs: list[bytes]) -> pd.DataFrame | None:
    rows = [r for d in docs for r in parse(d)]
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["delivery_start", "resolution", "direction", "control_error"])


def _one(session, token, area: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; its two halves when the API refuses it as too large or when the answer ends
    well before what it should cover (a cut answer)."""
    params = {"documentType": "A86", "businessType": "B33", "area_Domain": AREAS[area]}
    try:
        docs = _get(session, token, f"A86 B33 {area}", params, s, e)
    except TooLarge:
        if e - s <= dt.timedelta(days=1):
            raise
        docs = []  # split below
    df = None if docs is None else _frame(docs)
    cut = docs == [] or (df is not None and
                         (df["delivery_start"] + df["resolution"]).max() < min(e, dt.datetime.now(UTC)) - LAG)
    if cut and e - s > dt.timedelta(days=1):
        mid = s + (e - s) / 2
        parts = [p for p in (_one(session, token, area, s, mid), _one(session, token, area, mid, e)) if p is not None]
        return pd.concat(parts, ignore_index=True) if parts else None
    return df.assign(area=area) if df is not None else None


def _chunks(start: dt.datetime, end: dt.datetime):
    s = start
    while s < end:
        e = min(s + MAX_SPAN, end)
        yield s, e
        s = e


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in COLUMNS.items()})


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    token = os.environ["ENTSO_TOKEN"]
    session = requests.Session()
    jobs = [(area, cs, ce) for area in AREAS for cs, ce in _chunks(start, end)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        parts = [p for p in pool.map(lambda j: _one(session, token, *j), jobs) if p is not None]
    if not parts:
        return _empty()
    df = pd.concat(parts, ignore_index=True)[list(COLUMNS)]
    df = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)]
    df = df.astype(COLUMNS).drop_duplicates(ignore_index=True)
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        raise RuntimeError(f"{int(dup.sum())} rows share their key with another row, e.g. "
                           f"{df.loc[dup, KEY].iloc[0].tolist()}")
    return df.sort_values(KEY, ignore_index=True)
