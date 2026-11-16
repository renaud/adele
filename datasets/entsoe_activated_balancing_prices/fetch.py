# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E prices of activated balancing energy (document A84, article 17.1.F, process
type A16) of the Swiss control area: one row per reserve, resource type, direction and
quarter-hour.

Draft by Claude, 2026-11-15 (WP5.1). Facts measured before by the swissgrid project
(`swissgrid_project/data/entsoe/README.md`, download of 2026-10-31, its QA 3):

- Series as served: aFRR (business type A96) from 2015-04-30, mFRR (A97) from 2021-01-01 to
  2022-08-24, RR (A98) from 2015-04-30 to 2025-12-17 (TERRE ended in December 2025). Resource
  type A04 (generation) for all, and A03 (mixed) for RR from 2020-10-08.
- aFRR equals the secondary-control price of Swissgrid's Energy Statistic in 96.6 to 100 % of
  the quarter-hours of 2015-2024 and 2026, but in 13 % of 2025: in 2025 the A84 prices are whole
  numbers of EUR/MWh (cents lost, 99.96 % within 0.5 EUR/MWh).
- RR holds repeated round values that look like limits: -13,999 (48 quarter-hours), -14,899,
  +-9,999.
- No value changed between 2026-10-31 and 2026-11-15 (`qa/revisions_entsoe_ch.md`).

Measured on 2026-11-15 (WP5.1):

- The answer is one XML document (no zip, no docStatus); one year per request at most. Curve
  type A03 (a point holds until the next position): the parser expands it.
- The market product is served as `original_MarketProduct.marketProductType` (A04 for aFRR
  from 2025) or `standard_MarketProduct.marketProductType` (A01 for RR); before 2025 aFRR and
  RR of resource type A04 carry none. The column `product` takes the one served.
- The price category (`imbalance_Price.category` of each point) is A06 "Average bid price",
  and A08 for RR from 2025-07-30 18:00 local (A08 is not in code list v36r0).
- The key (reserve, resource, direction, quarter-hour) is unique in the swissgrid project's
  download: products and categories follow each other in time, never side by side.
- The latest price on 2026-11-15 21:22 UTC was for 20:45 UTC.
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
RESERVE = {"A95": "FCR", "A96": "aFRR", "A97": "mFRR", "A98": "RR"}
RESOURCE = {"A03": "mixed", "A04": "generation", "A05": "load"}
DIRECTION = {"A01": "up", "A02": "down"}
MAX_SPAN = dt.timedelta(days=365)
LAG = dt.timedelta(days=2)  # an answer may end this much before now without counting as cut
TIMEOUT_S = 120
ATTEMPTS = 4
RESOLUTION = {"PT1M": pd.Timedelta(minutes=1), "PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30),
              "PT60M": pd.Timedelta(hours=1)}
KEY = ["area", "reserve", "resource", "direction", "delivery_start"]
COLUMNS = {"area": "object", "reserve": "object", "resource": "object", "direction": "object",
           "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]", "product": "object",
           "category": "object", "price": "float64"}


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


def _code(table: dict, value: str | None, what: str) -> str:
    if value not in table:
        raise RuntimeError(f"{what} {value!r}, expected one of {sorted(table)}")
    return table[value]


def parse(doc: bytes) -> list[tuple]:
    """The points of one A84 document: (reserve, resource, direction, delivery_start, resolution,
    product, category, price)."""
    root = ET.fromstring(doc)
    rows = []
    for ts in (x for x in root.iter() if _local(x.tag) == "TimeSeries"):
        f = {_local(x.tag): (x.text or "").strip() for x in ts if len(x) == 0}
        if (f.get("currency_Unit.name"), f.get("price_Measure_Unit.name")) != ("EUR", "MWH"):
            raise RuntimeError(f"currency and unit {f.get('currency_Unit.name')}/{f.get('price_Measure_Unit.name')}, "
                               "expected EUR/MWH")
        curve = f.get("curveType", "A01")
        if curve not in ("A01", "A03"):
            raise RuntimeError(f"curve type {curve!r}, expected A01 or A03")
        reserve = _code(RESERVE, f.get("businessType"), "business type")
        resource = _code(RESOURCE, f.get("mktPSRType.psrType"), "resource type")
        direction = _code(DIRECTION, f.get("flowDirection.direction"), "direction")
        product = f.get("standard_MarketProduct.marketProductType") or f.get("original_MarketProduct.marketProductType")
        for period in (x for x in ts if _local(x.tag) == "Period"):
            p = {_local(x.tag): x.text for x in period.iter() if len(x) == 0}
            start = pd.Timestamp(p["start"]).tz_convert("UTC")
            end = pd.Timestamp(p["end"]).tz_convert("UTC")
            if p["resolution"] not in RESOLUTION:
                raise RuntimeError(f"resolution {p['resolution']!r}")
            res = RESOLUTION[p["resolution"]]
            n = int((end - start) / res)
            pts = sorted((int(v["position"]), float(v["activation_Price.amount"]), v.get("imbalance_Price.category"))
                         for v in ({_local(x.tag): x.text for x in pt}
                                   for pt in period if _local(pt.tag) == "Point"))
            for i, (pos, price, cat) in enumerate(pts):  # A03: a point holds until the next point
                last = (pts[i + 1][0] if i + 1 < len(pts) else n + 1) if curve == "A03" else pos + 1
                rows += [(reserve, resource, direction, start + (k - 1) * res, res, product, cat, price)
                         for k in range(pos, last)]
    return rows


def _frame(docs: list[bytes]) -> pd.DataFrame | None:
    rows = [r for d in docs for r in parse(d)]
    if not rows:
        return None
    return pd.DataFrame(rows, columns=[c for c in COLUMNS if c != "area"])


def _one(session, token, area: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; its two halves when the API refuses it as too large or when the answer ends
    well before what it should cover (a cut answer)."""
    params = {"documentType": "A84", "processType": "A16", "controlArea_Domain": AREAS[area]}
    try:
        docs = _get(session, token, f"A84 {area}", params, s, e)
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
    # chunks and halves overlap at their borders (whole days): keep one copy of identical rows
    df = df.astype(COLUMNS).drop_duplicates(ignore_index=True)
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        raise RuntimeError(f"{int(dup.sum())} rows share their key with another row, e.g. "
                           f"{df.loc[dup, KEY].iloc[0].tolist()}")
    return df.sort_values(KEY, ignore_index=True)
