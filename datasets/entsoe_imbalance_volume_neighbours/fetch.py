# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch ENTSO-E total imbalance volumes (document A86, article 17.1.H) of the control areas
around Switzerland: AT, FR, Italy (total and two macro zones), DE_LU and the four German TSO
areas. One row per area and settlement period, with the sign set from the direction served.

Draft by Claude, 2026-11-15 (WP5.1). Facts measured before by the swissgrid project
(`swissgrid_project/data/entsoe_neighbours/README.md`, download of 2026-11-01):

- Coverage: AT and FR from 2015-01-01; DE_LU from 2015-01-01 to 2022-09-02; TenneT from
  2019-12-01, TransnetBW from 2020-01-28, 50Hertz from 2021-02-10, Amprion from 2022-06-22;
  IT from 2015-01-05 to 2018-06-30 and from 2022-01-01 (43 more days missing from 2022-01-09);
  the Italian macro zones North and South from 2015-01-01 to 2022-02-23. The German control
  block (10YCB-GERMANY--8) holds nothing in any window: not asked.
- FR: PT30M until 2024-12-30 23:30 UTC, PT15M from 2024-12-31 00:00 UTC; 1,692 half-hours
  missing. The others PT15M.
- The value is served as a magnitude in MWh per settlement period (`quantity` >= 0) with a
  direction. A01 means a long control area (surplus) and A02 a short one for DE_LU, FR and the
  German TSO areas (evidence: the imbalance price is low when A01, high when A02; Spearman rho
  of the signed volume with the price -0.62 for DE_LU, -0.30 for FR, 0 of 374 months with the
  other sign). A03 comes with volume 0.
- AT used the opposite convention (A01 = short) before 2024-12-01 local, except in the
  intervals whose point also carries `secondaryQuantity` (whole months 2020-05, 2022-11,
  2023-01, 2024-07, which have the new sign): rho +0.60 before, -0.69 from December 2024. The
  data place the change within the day of 2024-12-01 (best cut 08:00 local); this file cuts at
  2024-12-01 00:00 local.
- IT has no price on the platform, so its sign is not checked (weak evidence: it correlates
  positively with the Swiss imbalance, 0.17, strongest at lag 0).
- `secondaryQuantity` (the second value of the DDD, MV - SV) is served for the German TSO
  areas, IT from 2022 and AT in some months, signed for DE and IT and as a magnitude for AT. Its
  sign convention is not checked, so it is not stored; it only selects AT's sign above.
- Outliers kept as served: TenneT 8,301.4 MWh on 2024-02-15 11:30 local (next largest 1,164.55),
  IT macro North about 5,000 MWh in three quarter-hours ending 2019-12-13 07:45 local.

Measured on 2026-11-15 (WP5.1):

- One request may span one year at most; a one-year request comes whole (TenneT 2025: one
  document, 35,040 points). An answer is a zip of documents with docStatus A01 "Intermediate"
  or A02 "Final", each covering other days; no interval was served twice. A final value would
  win over an intermediate one.
- Revised after publication (2026-11-01 against 2026-11-15, `qa/tools/revisions_entsoe_ch.py
  --neighbours`): 3,075 values changed, 2,958 of them 1 to 12 months after delivery (TenneT, all
  of August 2026), 258 added, 61 removed. Hence `revisions: append-only` and a long lookback.
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
AREAS = {
    "AT": "10YAT-APG------L", "FR": "10YFR-RTE------C", "IT": "10YIT-GRTN-----B",
    "IT_MACRO_NORTH": "10Y1001A1001A84D", "IT_MACRO_SOUTH": "10Y1001A1001A85B", "DE_LU": "10Y1001A1001A82H",
    "DE_50HZ": "10YDE-VE-------2", "DE_AMPRION": "10YDE-RWENET---I", "DE_TENNET": "10YDE-EON------1",
    "DE_TRANSNETBW": "10YDE-ENBW-----N",
}
SIGN = {"A01": 1.0, "A02": -1.0, "A03": 0.0}  # direction --> sign of imbalance (> 0 = long, surplus)
AT_NEW_SIGN_FROM = dt.datetime(2024, 11, 30, 23, tzinfo=UTC)  # 2024-12-01 00:00 Europe/Zurich
MAX_SPAN = dt.timedelta(days=365)
LAG = dt.timedelta(days=2)  # an answer may end this much before now without counting as cut
TIMEOUT_S = 120
ATTEMPTS = 4
RESOLUTION = {"PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30), "PT60M": pd.Timedelta(hours=1)}
STATUS_RANK = {"A02": 2, "A01": 1, None: 0}  # a final value wins over an intermediate one
KEY = ["area", "delivery_start"]
COLUMNS = {"area": "object", "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]",
           "direction": "object", "volume": "float64", "imbalance": "float64"}


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
    """The points of one A86 document: (status, delivery_start, resolution, direction, volume,
    has_secondary)."""
    root = ET.fromstring(doc)
    status = next((c.text for x in root if _local(x.tag) == "docStatus" for c in x), None)
    rows = []
    for ts in (x for x in root.iter() if _local(x.tag) == "TimeSeries"):
        f = {_local(x.tag): (x.text or "").strip() for x in ts if len(x) == 0}
        if f.get("businessType") != "A19":
            raise RuntimeError(f"business type {f.get('businessType')!r}, expected A19")
        if f.get("quantity_Measure_Unit.name") != "MWH":
            raise RuntimeError(f"unit {f.get('quantity_Measure_Unit.name')!r}, expected MWH")
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
            pts = sorted((int(v["position"]), float(v["quantity"]), "secondaryQuantity" in v)
                         for v in ({_local(x.tag): x.text for x in pt} for pt in period if _local(pt.tag) == "Point"))
            for i, (pos, q, sec) in enumerate(pts):  # A03: a point holds until the next point
                if q < 0:
                    raise RuntimeError(f"negative quantity {q}: the sign comes from the direction")
                last = (pts[i + 1][0] if i + 1 < len(pts) else n + 1) if curve == "A03" else pos + 1
                rows += [(status, start + (k - 1) * res, res, direction, q, sec) for k in range(pos, last)]
    return rows


def signed(df: pd.DataFrame) -> pd.Series:
    """The imbalance in MWh, > 0 = long: the sign of the direction, flipped for AT before
    2024-12-01 local where the point carries no secondaryQuantity."""
    sign = df["direction"].map(SIGN)
    flip = (df["area"] == "AT") & (df["delivery_start"] < AT_NEW_SIGN_FROM) & ~df["has_secondary"]
    return (sign.where(~flip, -sign) * df["volume"]).astype("float64")


def _frame(docs: list[bytes]) -> pd.DataFrame | None:
    rows = [r for d in docs for r in parse(d)]
    if not rows:
        return None
    return pd.DataFrame(rows, columns=["status", "delivery_start", "resolution", "direction", "volume",
                                       "has_secondary"])


def _one(session, token, area: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; its two halves when the API refuses it as too large or when the answer ends
    well before what it should cover (a cut answer)."""
    params = {"documentType": "A86", "controlArea_Domain": AREAS[area]}
    try:
        docs = _get(session, token, f"A86 {area}", params, s, e)
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


def one_per_key(df: pd.DataFrame) -> pd.DataFrame:
    """One row per area and interval: identical copies dropped, a final value preferred to an
    intermediate one; two different values of the same status are an error."""
    df = df.drop_duplicates()
    # not .map(STATUS_RANK): a dict lookup through map() misses None, and a NaN rank drops the row
    rank = pd.Series([STATUS_RANK.get(s, 0) for s in df["status"]], index=df.index)
    df = df[rank == rank.groupby([df["area"], df["delivery_start"]]).transform("max")]
    dup = df.duplicated(KEY, keep=False)
    if dup.any():
        raise RuntimeError(f"{int(dup.sum())} rows of the same status share their key, e.g. "
                           f"{df.loc[dup, KEY].iloc[0].tolist()}")
    return df


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
    df = one_per_key(df)
    df = df.assign(imbalance=signed(df))
    return df[list(COLUMNS)].astype(COLUMNS).sort_values(KEY, ignore_index=True)
