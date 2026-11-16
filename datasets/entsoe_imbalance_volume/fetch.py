# /// script
# requires-python = ">=3.12"
# dependencies = ["entsoe-py==0.8.1", "pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the ENTSO-E total imbalance volume (document A86, article 17.1.H) of the Swiss control area.

Draft by Claude, 2026-11-15 (WP5.2). Measured on raw answers of 2026-11-15 (2026-11-01 to now,
the years 2015 and 2025), and taken from the swissgrid project's download of 2026-10-31 and its
comparison with Swissgrid's TSI (`swissgrid_project/data/entsoe/README.md`, "The main result"):

- The answer is a zip of documents, one per document status: 2015 holds one document without a
  status (20 points: 2015-03-25, 2015-03-31, and in the project's download 2022-05-31 22:00-23:45
  UTC) and one "intermediate" (docStatus A01); 2025 one intermediate (to 2025-03-30) and one
  "final" (A02, from 2025-03-31). Every value before April 2025 is still marked intermediate.
- Per document, one time series per direction (flowDirection A01, A02, and A03 with volume 0
  only), business type A19, unit MWH (the energy of the quarter-hour), curve type A03 (a point
  holds until the next position; the parser expands it). PT15M from 2015-03-25 23:00 UTC.
- Each point holds `quantity` (the volume, >= 0) and, from 2024-07-31 22:00 UTC, a
  `secondaryQuantity`: the difference between measured and scheduled flows over all
  interconnectors, MV - SV, signed, export > 0 (ENTSO-E's Detailed Data Descriptions v3r4,
  pp. 89-91).
- Sign: A01 is a surplus (the control area is long), A02 a deficit. The code list names them
  "UP" and "DOWN", which doesn't tell the sign; the comparison with Swissgrid's TSI does: TSI > 0
  in 90.5 % of the A01 quarter-hours and in 6.3 % of the A02 ones (69,592 quarter-hours,
  2024-11-01 to 2026-10-27). This file writes `imbalance` = +volume for A01, -volume for A02, 0
  for A03 (a volume other than 0 there is refused).
- A request of 365 days comes whole (2025: 34,945 quarter-hours in 15 s; 95 of 2025-10-24 are
  missing at the source). A week takes as long: the time is the platform's, not the size.
- Revised (`qa/revisions_entsoe_ch.md`): between 2026-10-31 and 2026-11-15, 6 values of
  2025-09-11 changed (25.1 --> 82.1 MWh at 11:00 UTC), 14 were removed and 32 added (one
  quarter-hour of 2025-09-22 added): corrected more than a year after delivery.
- No document field that changes at each answer is returned (createdDateTime, mRID): with
  `revisions: append-only`, each fetch would store every row again. The document status is
  returned: a value that becomes final is a new version.

The HTTP requests go through entsoe-py's raw client (its errors for "no data"), with a timeout
and retries; the XML is parsed here. The token never appears in an error text: requests puts
the URL, token included, in its messages.
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
from entsoe import EntsoeRawClient
from entsoe.exceptions import NoMatchingDataError, PaginationError

UTC = dt.timezone.utc
AREAS = {"CH": "10YCH-SWISSGRIDZ"}
SIGN = {"A01": 1.0, "A02": -1.0, "A03": 0.0}  # flowDirection --> sign of the imbalance (surplus > 0)
STATUS = {"A01": "intermediate", "A02": "final", None: None}  # docStatus
MAX_SPAN = dt.timedelta(days=365)  # the API serves at most one year per request
LAG = dt.timedelta(days=2)  # a response may end this much before now without counting as cut
TIMEOUT_S = 120
ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}
RESOLUTION = {"PT15M": pd.Timedelta(minutes=15), "PT30M": pd.Timedelta(minutes=30), "PT60M": pd.Timedelta(hours=1)}
COLUMNS = {"control_area": "object", "delivery_start": "datetime64[ns, UTC]", "resolution": "timedelta64[ns]",
           "imbalance": "float64", "mv_minus_sv": "float64", "status": "object"}


def documents(content: bytes) -> list[bytes]:
    """The XML documents of an answer: the members of a zip, or the answer itself."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return [z.read(n) for n in sorted(z.namelist())]
    return [content]


def _num(text: str | None) -> float | None:
    return None if text is None else float(text)


def parse(content: bytes, area: str = "CH") -> pd.DataFrame:
    """The points of an A86 answer: delivery_start, resolution, imbalance (MWh, signed), mv_minus_sv
    (MWh), status."""
    rows = []
    for doc in documents(content):
        root = ET.fromstring(doc)
        ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        if root.tag.endswith("Acknowledgement_MarketDocument"):
            raise RuntimeError(f"acknowledgement: {root.findtext(f'.//{ns}Reason/{ns}text')!r}")
        got = root.findtext(f"{ns}controlArea_Domain.mRID")
        if got != AREAS[area]:
            raise RuntimeError(f"control area {got!r}, expected {AREAS[area]} ({area})")
        code = root.findtext(f"{ns}docStatus/{ns}value")
        if code not in STATUS:
            raise RuntimeError(f"document status {code!r}, expected A01, A02 or none")
        for ts in root.iter(f"{ns}TimeSeries"):
            unit = ts.findtext(f"{ns}quantity_Measure_Unit.name")
            if unit != "MWH":
                raise RuntimeError(f"unit {unit!r}, expected MWH")
            curve = ts.findtext(f"{ns}curveType") or "A01"
            if curve not in ("A01", "A03"):
                raise RuntimeError(f"curve type {curve!r}, expected A01 or A03")
            business = ts.findtext(f"{ns}businessType")
            if business != "A19":
                raise RuntimeError(f"business type {business!r}, expected A19")
            direction = ts.findtext(f"{ns}flowDirection.direction")
            if direction not in SIGN:
                raise RuntimeError(f"direction {direction!r}, expected A01, A02 or A03")
            for period in ts.iter(f"{ns}Period"):
                start = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}start")).tz_convert("UTC")
                end = pd.Timestamp(period.findtext(f"{ns}timeInterval/{ns}end")).tz_convert("UTC")
                res_text = period.findtext(f"{ns}resolution")
                if res_text not in RESOLUTION:
                    raise RuntimeError(f"resolution {res_text!r}")
                res = RESOLUTION[res_text]
                n = int((end - start) / res)
                points = sorted((int(p.findtext(f"{ns}position")), float(p.findtext(f"{ns}quantity")),
                                 _num(p.findtext(f"{ns}secondaryQuantity"))) for p in period.iter(f"{ns}Point"))
                for i, (pos, q, sec) in enumerate(points):
                    if direction == "A03" and q != 0:
                        raise RuntimeError(f"direction A03 (balanced) with volume {q} at {start + (pos - 1) * res}")
                    last = (points[i + 1][0] if i + 1 < len(points) else n + 1) if curve == "A03" else pos + 1
                    rows += [(start + (k - 1) * res, res, SIGN[direction] * q + 0.0, sec, STATUS[code])
                             for k in range(pos, last)]
    return pd.DataFrame(rows, columns=["delivery_start", "resolution", "imbalance", "mv_minus_sv", "status"])


def _clean(e: Exception) -> str:
    return str(e).replace(os.environ.get("ENTSO_TOKEN") or "\0", "***")[:300]


def _request(client: EntsoeRawClient, area: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            content = client.query_imbalance_volumes(area, start=pd.Timestamp(s), end=pd.Timestamp(e))
            break
        except NoMatchingDataError:
            return None
        except PaginationError:  # too large: _one splits the window
            raise
        except Exception as ex:  # noqa: BLE001 - its text, or the error it chains, may hold the URL with the token
            status = getattr(getattr(ex, "response", None), "status_code", None)
            transient = isinstance(ex, (requests.Timeout, requests.ConnectionError)) or status in RETRY_STATUS
            if not transient or attempt == ATTEMPTS:
                raise RuntimeError(f"{area} A86 [{s}, {e}): {type(ex).__name__} {_clean(ex)}") from None
            time.sleep(5 * attempt)
    df = parse(content, area)
    return df if len(df) else None


def _one(client: EntsoeRawClient, area: str, s: dt.datetime, e: dt.datetime) -> pd.DataFrame | None:
    """One request; split in two when the answer ends well before what it should cover (a cut answer)
    or when the platform refuses it as too large."""
    try:
        df = _request(client, area, s, e)
    except PaginationError:
        df, too_large = None, True
    else:
        too_large = False
    data_end = None if df is None else (df["delivery_start"] + df["resolution"]).max()
    cut = df is not None and data_end < min(e, dt.datetime.now(UTC)) - LAG
    if (too_large or cut) and e - s > dt.timedelta(days=1):
        mid = _floor_hour(s + (e - s) / 2)
        parts = [p for p in (_one(client, area, s, mid), _one(client, area, mid, e)) if p is not None]
        return pd.concat(parts, ignore_index=True).drop_duplicates(ignore_index=True) if parts else None
    if too_large:
        raise RuntimeError(f"{area} A86 [{s}, {e}): refused as too large, even for one day")
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
    jobs = [(area, cs, ce) for area in AREAS for cs, ce in _chunks(start, end)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda j: (j[0], _one(client, *j)), jobs))
    frames = [df.assign(control_area=area) for area, df in answers if df is not None]
    df = pd.concat(frames, ignore_index=True) if frames else _empty()
    df = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)]
    # chunks may meet inside one answer's period: keep one copy of identical rows
    df = df[list(COLUMNS)].drop_duplicates(ignore_index=True).astype(COLUMNS)
    df["status"] = df["status"].where(df["status"].notna(), None)  # pandas 3 gives NaN for a missing string
    dup = df.duplicated(["control_area", "delivery_start"], keep=False)
    if dup.any():  # served twice (two directions, or two documents) with different values
        raise RuntimeError(f"{int(dup.sum())} rows share a quarter-hour, the first at "
                           f"{df.loc[dup, 'delivery_start'].min()}")
    return df
