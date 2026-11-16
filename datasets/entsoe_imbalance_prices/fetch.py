# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E imbalance prices (document A85, article 17.1.G) of the control areas CH, AT,
DE_LU and FR: one row per area and settlement period, with the price for a long position (A04)
and for a short one (A05) side by side.

Draft by Claude, 2026-11-15 (WP5.1). Facts measured before by the swissgrid project
(`swissgrid_project/data/entsoe/README.md` for CH, download of 2026-10-31;
`swissgrid_project/data/entsoe_neighbours/README.md` for AT, DE_LU, FR, download of 2026-11-01):

- A04 "Excess balance" is the price for a long position, A05 "Insufficient balance" the price for
  a short one (code list v36r0, StandardPriceCategoryTypeList, p. 36). CH A85 equals Swissgrid's
  own monthly price files in 100 % of the quarter-hours of 2023 and 2024, 98.9 % of 2025 and
  99.8 % of 2026 (its QA 3).
- CH from 2016-03-31 (2015 answers "no data"), holes: Jul-Sep 2016 (8,736 quarter-hours),
  2022-12-31 (96), 7 single quarter-hours at 23:00 local in May-Jun 2026. From 2026 A04 = A05.
- AT from 2015-01-01, single price (A04 = A05 in every interval). DE_LU from 2015-01-01 to
  2022-06-21, single price, nothing after (the German price is published by the four TSOs, not
  on this platform). FR dual price (A04 <= A05 in every interval), PT30M until 2024-12-30 23:30
  UTC, PT15M from 2024-12-31 00:00 UTC; holes of 1,739 half-hours.
- The four German TSO areas, the German control block and Italy have no A85 in any window: they
  are not asked.
- No CH A85 value changed between 2026-10-31 and 2026-11-15 (`qa/revisions_entsoe_ch.md`). The
  neighbours are revised (2026-11-01 against 2026-11-15): AT replaced its prices of the last
  week before the old download, FR changed 4 quarter-hours of 2026-05-13 and some of October
  2026 (`docs/work-packages/WP5.1-entsoe.md`). Hence `revisions: append-only`.

Measured on 2026-11-15 (WP5.1, raw answers in the session scratchpad, not kept):

- One request may span one year at most; a one-year request comes whole for CH and the
  neighbours (FR 2025: 2 time series, 33,919 points; AT 2025: 2 documents).
- An answer is a zip of one or two documents: one with docStatus A01 "Intermediate" and one with
  A02 "Final" (FR serves no status). Each price category is its own time series, curve type A03
  (a point holds until the next position): the parser expands it per series.
- The latest CH price on 2026-11-15 21:22 UTC was for 19:45 UTC (about 1.5 hours after delivery).

The HTTP requests are made here with `requests` (no client library): a timeout and retries on
each, and an error message never holds the URL, which carries the token.
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
AREAS = {"CH": "10YCH-SWISSGRIDZ", "AT": "10YAT-APG------L", "DE_LU": "10Y1001A1001A82H", "FR": "10YFR-RTE------C"}
MAX_SPAN = dt.timedelta(days=365)  # "larger than maximum allowed period 'P1Y'" beyond
LAG = dt.timedelta(days=2)  # an answer may end this much before now without counting as cut
TIMEOUT_S = 120
ATTEMPTS = 4
RESOLUTION = {"PT1M": pd.Timedelta(minutes=1), "PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30),
              "PT60M": pd.Timedelta(hours=1)}
CATEGORY = {"A04": "price_long", "A05": "price_short"}
STATUS_RANK = {"A02": 2, "A01": 1, None: 0}  # a final value wins over an intermediate one
COLUMNS = {"area": "object", "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]",
           "price_long": "float64", "price_short": "float64"}


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
    """The points of one A85 document: (status, delivery_start, resolution, category, price)."""
    root = ET.fromstring(doc)
    status = next((c.text for x in root if _local(x.tag) == "docStatus" for c in x), None)
    rows = []
    for ts in (x for x in root.iter() if _local(x.tag) == "TimeSeries"):
        f = {_local(x.tag): (x.text or "").strip() for x in ts if len(x) == 0}
        if (f.get("currency_Unit.name"), f.get("price_Measure_Unit.name")) != ("EUR", "MWH"):
            raise RuntimeError(f"currency and unit {f.get('currency_Unit.name')}/{f.get('price_Measure_Unit.name')}, "
                               "expected EUR/MWH")
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
            groups: dict[str, list[tuple[int, float]]] = {}
            for pt in (x for x in period if _local(x.tag) == "Point"):
                v = {_local(x.tag): x.text for x in pt}
                groups.setdefault(v["imbalance_Price.category"], []).append(
                    (int(v["position"]), float(v["imbalance_Price.amount"])))
            for cat, pts in groups.items():  # A03: a point holds until the next point of its category
                pts.sort()
                for i, (pos, price) in enumerate(pts):
                    last = (pts[i + 1][0] if i + 1 < len(pts) else n + 1) if curve == "A03" else pos + 1
                    rows += [(status, start + (k - 1) * res, res, cat, price) for k in range(pos, last)]
    return rows


def _frame(docs: list[bytes]) -> pd.DataFrame | None:
    rows = [r for d in docs for r in parse(d)]
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["status", "delivery_start", "resolution", "category", "price"])


def _one(session, token, area: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; its two halves when the API refuses it as too large or when the answer ends
    well before what it should cover (a cut answer)."""
    params = {"documentType": "A85", "controlArea_Domain": AREAS[area]}
    try:
        docs = _get(session, token, f"A85 {area}", params, s, e)
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


def wide(df: pd.DataFrame) -> pd.DataFrame:
    """One row per area and interval, the two categories side by side. An interval served by two
    documents keeps the value of the final one; two different values of the same status are an error."""
    df = df.drop_duplicates()
    # not .map(STATUS_RANK): a dict lookup through map() misses None, and a NaN rank drops the row
    df = df.assign(rank=[STATUS_RANK.get(s, 0) for s in df["status"]])
    key = ["area", "delivery_start", "category"]
    top = df[df["rank"] == df.groupby(key)["rank"].transform("max")]
    clash = top.groupby(key)["price"].nunique()
    if (clash > 1).any():
        k = clash[clash > 1].index[0]
        raise RuntimeError(f"two prices of the same status for {k}")
    top = top.drop_duplicates(key)
    res = top.groupby(["area", "delivery_start"])["resolution"].nunique()
    if (res > 1).any():
        raise RuntimeError(f"two resolutions for {res[res > 1].index[0]}")
    out = top.pivot_table(index=["area", "delivery_start", "resolution"], columns="category", values="price",
                          aggfunc="first").reset_index()
    unknown = set(out.columns) - {"area", "delivery_start", "resolution"} - set(CATEGORY)
    if unknown:
        raise RuntimeError(f"price categories {sorted(unknown)}, expected A04 and A05")
    out = out.rename(columns=CATEGORY)
    for c in CATEGORY.values():
        if c not in out:
            out[c] = float("nan")
    return out[list(COLUMNS)]


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
    df = pd.concat(parts, ignore_index=True)
    df = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)]
    if df.empty:
        return _empty()
    return wide(df).astype(COLUMNS).sort_values(["area", "delivery_start"], ignore_index=True)
