# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch Swissgrid's imbalance prices per quarter-hour from the monthly price files (final prices).

Source: https://www.swissgrid.ch/en/home/customers/topics/bgm/balance-energy.html links one XML
(and an XLSX twin) per month of the current year, and one zip per past year
(`balance-energy-<year>.zip`, an XML and an XLSX per month). The links carry an id that changes
when Swissgrid replaces a file (`/dam/jcr:<id>/<name>`), so each fetch reads them from the page.

Measured on 2026-11-15 (all files of the page, scratch measurements; parser after SED,
`sources/ch_swissgrid/build.py`):

- 45 monthly XML files, 2023-01 to 2026-09: 131,420 quarter-hours from 2023-01-01 00:00 local to
  2026-09-30 23:45 local, every quarter-hour, no gap, no duplicate. Each file covers the local
  days [first, last) of its name (e.g. 260101-260201) and its stamps run from 00:00 to 23:45
  local: a stamp marks the start of the quarter-hour. Stamps carry their offset
  (2023-03-26T03:00:00+02:00), so the clock changes need no guess: March has 2,972 quarter-hours,
  October 2,980.
- Series: BG-long and BG-short (2023-2025, the dual price), BG-AEP (from 2025-07: next to the
  dual price until 2025-12, alone from 2026-01, the single price). Swissgrid's control-area file
  names the 2025 column "AE-Preis per 2026": the price by the rules of 2026, published for
  information. Unit ct/kWh with at most 2 decimals; x 10 = EUR/MWh (exact, through Decimal).
  BG-long <= BG-short in all 105,216 quarter-hours of 2023-2025.
- Against ENTSO-E's CH imbalance price (A85, swissgrid_project's download): BG-long equals A04
  and BG-short equals A05 in 99.6 % of the quarter-hours at shift 0, 4.4 % at -15 or +15 min.
- Identical, value for value, to SED's `imbalance_price_15min` (2023-01 to 2026-09).
- Publication: a month's file is printed on the 12th to the 24th of the next month (printedAt).
  The January and February 2026 files were uploaded again on 2026-03-24 (Last-Modified), with
  their printedAt of February and March. The disclaimer: Swissgrid may correct errors "in the
  next billing period". In the zips the files are named swissgrid-prices-for-balance-energy-
  (2024-01 and 2024-02 with an underscore: ..._240101-240201.xml).
- The October 2026 file was not on the page yet on 2026-11-15.

A month whose file is still missing 45 days after its end is an error: the status turns to
failing, and someone looks at the page.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
import requests

PAGE = "https://www.swissgrid.ch/en/home/customers/topics/bgm/balance-energy.html"
TZ = ZoneInfo("Europe/Zurich")
UTC = dt.timezone.utc
FIRST_MONTH = dt.date(2023, 1, 1)  # the first month on the page (and in any local copy)
LATE = dt.timedelta(days=45)  # a month without a file this long after its end is an error
TIMEOUT_S = 60
ATTEMPTS = 3
UNIT = "ct/kWh"
SERIES = ("BG-long", "BG-short", "BG-AEP")
QUARTER = pd.Timedelta(minutes=15)
# swissgrid-prices-for-imbalance-energy-260101-260201.xml (page), ...-for-balance-energy-250101-250201.xml
# and ...-for-balance-energy_240101-240201.xml (zips): the first day of the month, then the first day after it
MONTH_FILE = re.compile(r"swissgrid-prices-for-(?:im)?balance-energy[-_](\d{2})(\d{2})01-(\d{2})(\d{2})01\.xml$")
COLUMNS = ["delivery_start", "price_regime", "price_long", "price_short", "price_single"]


def _get(session: requests.Session, url: str) -> bytes:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = session.get(url, timeout=TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == ATTEMPTS:
                raise
        else:
            if r.status_code < 500:
                r.raise_for_status()
                return r.content
            if attempt == ATTEMPTS:
                r.raise_for_status()
        time.sleep(5 * attempt)
    raise AssertionError("unreachable")


def page_links(html: str) -> dict[str, str]:
    """File name --> absolute URL, for every /dam/ link of the page."""
    links = {}
    for href in re.findall(r'href="([^"]*/dam/[^"]+)"', html):
        url = urljoin(PAGE, href.replace("&amp;", "&"))
        links.setdefault(url.split("?")[0].rsplit("/", 1)[-1], url)
    return links


def month_of(name: str) -> dt.date | None:
    """The month that a price file covers, from its name; None for any other file."""
    m = MONTH_FILE.search(name)
    if not m:
        return None
    first = dt.date(2000 + int(m[1]), int(m[2]), 1)
    after = dt.date(2000 + int(m[3]), int(m[4]), 1)
    if after != _next_month(first):
        raise RuntimeError(f"{name}: covers more or less than one month")
    return first


def _next_month(d: dt.date) -> dt.date:
    return dt.date(d.year + d.month // 12, d.month % 12 + 1, 1)


def _month_start_utc(d: dt.date) -> dt.datetime:
    return dt.datetime(d.year, d.month, 1, tzinfo=TZ).astimezone(UTC)


def months(start: dt.datetime, end: dt.datetime, now: dt.datetime) -> list[dt.date]:
    """The local months (Europe/Zurich) that overlap [start, end), from FIRST_MONTH to the current month."""
    last = min(end - dt.timedelta(microseconds=1), now).astimezone(TZ).date().replace(day=1)
    m = max(start.astimezone(TZ).date().replace(day=1), FIRST_MONTH)
    out = []
    while m <= last:
        out.append(m)
        m = _next_month(m)
    return out


def parse_xml(data: bytes, name: str, month: dt.date) -> pd.DataFrame:
    """One monthly file --> rows (delivery_start, series, price in EUR/MWh)."""
    root = ET.fromstring(data)
    lo, hi = _month_start_utc(month), _month_start_utc(_next_month(month))
    rows = []
    for ts in root.iter("timeSeries"):
        title, unit = ts.findtext("Report_TS_Titel_en"), ts.findtext("unit")
        if title not in SERIES:
            raise RuntimeError(f"{name}: unknown series {title!r} (known: {', '.join(SERIES)}); decide how to store it")
        if unit != UNIT:
            raise RuntimeError(f"{name}: {title}: unit {unit!r}, expected {UNIT}")
        for dv in ts.findall("timeSeriesData/DATAVALUE"):
            t = dt.datetime.fromisoformat(dv.findtext("TIME"))
            if t.tzinfo is None:
                raise RuntimeError(f"{name}: {title}: a time without its offset: {dv.findtext('TIME')}")
            t = t.astimezone(UTC)
            if not lo <= t < hi:
                raise RuntimeError(f"{name}: {title}: {t} is outside the month {month:%Y-%m}")
            rows.append((t, title, float(Decimal(dv.findtext("VALUE").strip()) * 10)))  # ct/kWh --> EUR/MWh
    df = pd.DataFrame(rows, columns=["delivery_start", "series", "price"])
    if df.empty:
        raise RuntimeError(f"{name}: no value")
    if df.duplicated(["delivery_start", "series"]).any():
        raise RuntimeError(f"{name}: a series has two values for one quarter-hour")
    expected = pd.date_range(lo, hi, freq=QUARTER, inclusive="left")
    for title, g in df.groupby("series"):
        if len(g) != len(expected):
            raise RuntimeError(f"{name}: {title} has {len(g)} quarter-hours, the month has {len(expected)}")
    return df


def to_table(long: pd.DataFrame) -> pd.DataFrame:
    """Rows (delivery_start, series, price) --> one row per quarter-hour.

    Dual price (BG-long and BG-short): price_long and price_short as published; price_single is
    BG-AEP where the file has it (2025-07 to 2025-12: the price by the rules of 2026). Single
    price (BG-AEP alone): price_long = price_short = price_single = BG-AEP.
    """
    if long.empty:
        return pd.DataFrame({"delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                             "price_regime": pd.Series(dtype="object"),
                             **{c: pd.Series(dtype="float64") for c in COLUMNS[2:]}})
    w = long.pivot(index="delivery_start", columns="series", values="price").reindex(columns=list(SERIES))
    has_long, has_short, has_aep = w["BG-long"].notna(), w["BG-short"].notna(), w["BG-AEP"].notna()
    if (has_long != has_short).any():
        raise RuntimeError(f"BG-long without BG-short (or the reverse) at {w.index[has_long != has_short][0]}")
    if (~has_long & ~has_aep).any():
        raise RuntimeError(f"no price at {w.index[~has_long & ~has_aep][0]}")
    dual = has_long
    out = pd.DataFrame({
        "delivery_start": w.index,
        "price_regime": dual.map({True: "dual", False: "single"}).values,
        "price_long": w["BG-long"].where(dual, w["BG-AEP"]).values,
        "price_short": w["BG-short"].where(dual, w["BG-AEP"]).values,
        "price_single": w["BG-AEP"].values,
    })
    return out.sort_values("delivery_start", ignore_index=True)


def fetch(start: dt.datetime, end: dt.datetime, now: dt.datetime | None = None) -> pd.DataFrame:
    now = now or dt.datetime.now(UTC)
    todo = months(start, end, now)
    if not todo:
        return to_table(pd.DataFrame())
    session = requests.Session()
    links = page_links(_get(session, PAGE).decode("utf-8", "replace"))
    monthly = {}  # month --> URL of its XML on the page
    for name, url in links.items():
        m = month_of(name)
        if m:
            monthly[m] = url
    zips = {}  # year --> {month: XML bytes}
    frames = []
    for m in todo:
        if m in monthly:
            name = monthly[m].rsplit("/", 1)[-1]
            frames.append(parse_xml(_get(session, monthly[m]), name, m))
            continue
        zip_name = f"balance-energy-{m.year}.zip"
        if zip_name in links and m.year not in zips:
            z = zipfile.ZipFile(io.BytesIO(_get(session, links[zip_name])))
            zips[m.year] = {month_of(n): (n, z.read(n)) for n in z.namelist() if month_of(n)}
        if m in zips.get(m.year, {}):
            n, data = zips[m.year][m]
            frames.append(parse_xml(data, f"{zip_name}/{n}", m))
            continue
        if _month_start_utc(_next_month(m)) + LATE < now:
            raise RuntimeError(f"no price file for {m:%Y-%m} on {PAGE}, {LATE.days} days after the month")
    return to_table(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
