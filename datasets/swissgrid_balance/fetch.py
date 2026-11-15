# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Swissgrid's balance of the control area per quarter-hour since November 2024: the year files
`control-area-balance-<year>.csv`, revised in place.

Draft by Claude, 2026-11-15 (WP4, points 4 to 6). No raw answers (point 4): Swissgrid still serves
the files, and append-only keeps their revisions. The window chooses the files: every local
(Europe/Zurich) year that [start, end) touches, from 2024 on. With the lookback of the descriptor
(P800D), a scheduled run reads three files, and the server compares every row (G6).

Facts (SED, sources/ch_swissgrid/README.md and build.py; the Swissgrid poller's archive,
docs/work-packages/WP4-files-overwritten-or-revised.md):

- Three layouts. 2024 and 2025: `Date Time` in local wall time without a zone (the repeated
  hour of the change to winter time comes twice, the summer-time copy first), RR columns,
  the dual price (AE-Preis long and short), and in 2025 `AE-Preis per 2026`. 2026: `Date Time
  [UTC]`, no RR, the single price (AE-Preis). The 2024 file ends with an empty row.
- The stamp is the start of the quarter-hour (SED: the TSI identity holds row by row).
- Prices in EUR-cent/kWh: x10 gives EUR/MWh, rounded to 0.1 (at most two decimals in ct/kWh).
- The file of the year changes once a day, at about 23:20 UTC (sometimes 01:20 or 03:20), and
  reaches to about 2 hours before. The files of 2024 and 2025 were last modified on 2026-03-24.
- A missing file is an error, except the file of the current year in its first 7 days.
"""
from __future__ import annotations

import datetime as dt
import io
import re
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

BASE = "https://www.swissgrid.ch"
SEEDS = {  # checked by the poller on 2026-09-27
    2024: BASE + "/dam/jcr:a118814e-99d6-49e5-bafd-905eeed8c5df/control-area-balance-2024.csv",
    2025: BASE + "/dam/jcr:8637ac18-f4b6-4f46-bd7c-9a5f0e0ea02d/control-area-balance-2025.csv",
    2026: BASE + "/dam/jcr:aeff36d3-9538-4d0c-b369-fc22172b8374/control-area-balance-2026.csv",
}
PAGES = [BASE + "/en/home/customers/topics/energy-data-ch.html",
         BASE + "/en/home/customers/topics/bgm/balance-energy.html"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; adele; research data archive)"}
TIMEOUT = 60
TZ = ZoneInfo("Europe/Zurich")
FIRST_YEAR = 2024
GRACE = dt.timedelta(days=7)

COLUMNS = {
    "Abgedeckte Bedarf der aFRR+": "afrr_up", "Abgedeckte Bedarf der aFRR-": "afrr_dn",
    "Abgedeckte Bedarf der SA mFRR+": "sa_mfrr_up", "Abgedeckte Bedarf der SA mFRR-": "sa_mfrr_dn",
    "Abgedeckte Bedarf der DA mFRR+": "da_mfrr_up", "Abgedeckte Bedarf der DA mFRR-": "da_mfrr_dn",
    "Abgedeckte Bedarf der RR+": "rr_up", "Abgedeckte Bedarf der RR-": "rr_dn",
    "NRV+ (Import)": "nrv_import", "NRV- (Export)": "nrv_export",
    "FRCE+ (Import)": "frce_import", "FRCE- (Export)": "frce_export",
    "Total System Imbalance (Positiv = long / Negativ = short)": "tsi", "Total System Imbalance": "tsi",
    "AE-Preis long": "price_long", "AE-Preis short": "price_short",
    "AE-Preis per 2026": "price_single_shadow", "AE-Preis": "price_single",
}
FIELDS = ["afrr_up", "afrr_dn", "sa_mfrr_up", "sa_mfrr_dn", "da_mfrr_up", "da_mfrr_dn", "rr_up", "rr_dn",
          "nrv_import", "nrv_export", "frce_import", "frce_export", "tsi",
          "price_long", "price_short", "price_single", "price_single_shadow"]
PRICES = ["price_long", "price_short", "price_single", "price_single_shadow"]
# The columns of each known layout, by the time column. A file with a column more or less is
# refused: a missing column would store a null version of every row of the window.
_FLOWS = set(FIELDS[:12]) | {"tsi"}
LAYOUTS = {
    "Date Time": [_FLOWS | {"price_long", "price_short"},                                   # 2024
                  _FLOWS | {"price_long", "price_short", "price_single_shadow"}],           # 2025
    "Date Time [UTC]": [(_FLOWS - {"rr_up", "rr_dn"}) | {"price_single"}],                   # 2026
}


def _find(name: str) -> str | None:
    for page in PAGES:
        r = requests.get(page, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for href in re.findall(r'href="([^"]*/dam/[^"]+)"', r.text):
            url = urljoin(page, href.replace("&amp;", "&"))
            if url.split("?")[0].rsplit("/", 1)[-1] == name:
                return url
    return None


def get_year(year: int, now: dt.datetime) -> bytes | None:
    """The file of a year: at its seed URL, else found by name on the pages. None for the file
    of the current year that doesn't exist yet in the first days of the year."""
    name = f"control-area-balance-{year}.csv"
    seed = SEEDS.get(year)
    r = requests.get(seed, headers=HEADERS, timeout=TIMEOUT) if seed else None
    if r is None or r.status_code == 404:
        url = _find(name)
        if url is None:
            start_of_year = dt.datetime(year, 1, 1, tzinfo=TZ)
            if now - start_of_year < GRACE:
                print(f"{name}: not published yet")
                return None
            raise RuntimeError(f"{name}: not at its seed URL {seed}, and no page of {PAGES} links it")
        if seed:
            print(f"{name}: the seed URL is stale, the file is now at {url}: update SEEDS in fetch.py")
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.content


def years(start: dt.datetime, end: dt.datetime) -> list[int]:
    """The local years that [start, end) touches, from FIRST_YEAR on."""
    last = (end - dt.timedelta(microseconds=1)).astimezone(TZ).year
    return list(range(max(FIRST_YEAR, start.astimezone(TZ).year), last + 1))


def eur_mwh(ct_kwh: pd.Series, what: str) -> pd.Series:
    v = ct_kwh * 10.0
    r = v.round(1)
    lost = (v - r).abs()
    if (lost > 1e-6).any():
        raise ValueError(f"{what}: a price with more than two decimals in ct/kWh: {ct_kwh[lost > 1e-6].head(3).tolist()}")
    return r


def local_to_utc(stamps: pd.Series) -> pd.Series:
    """Naive local wall time, rows in time order --> UTC. The hour of the change to winter time
    comes twice: a stamp of that hour is summer time until the file steps back, winter time after.
    Read from the order of the rows, not from the repeats, so that a file that ends inside the
    repeated hour is right too. The result must increase strictly, or the file is refused."""
    stepped_back = (stamps.cummax().shift(1) >= stamps).fillna(False)  # an earlier row is at or after this one
    out = stamps.dt.tz_localize(TZ, ambiguous=(~stepped_back).to_numpy(), nonexistent="raise").dt.tz_convert("UTC")
    if not out.is_monotonic_increasing or not out.is_unique:
        raise ValueError("local stamps that are not in time order once converted to UTC")
    return out


def parse(body: bytes, name: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(body), sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
    tcol = df.columns[0] if len(df.columns) else None
    if tcol not in ("Date Time", "Date Time [UTC]"):
        raise ValueError(f"{name}: the first column is {tcol!r}, expected 'Date Time' or 'Date Time [UTC]'")
    unknown = [c for c in df.columns[1:] if c not in COLUMNS]
    if unknown:
        raise ValueError(f"{name}: unknown columns {unknown}")
    targets = [COLUMNS[c] for c in df.columns[1:]]
    if len(set(targets)) != len(targets) or set(targets) not in LAYOUTS[tcol]:
        raise ValueError(f"{name}: columns {list(df.columns[1:])} are not a known layout for {tcol!r}")
    df = df[df[tcol].str.strip() != ""]
    stamps = pd.to_datetime(df[tcol].str.strip(), format="%d.%m.%Y %H:%M")
    out = pd.DataFrame({"delivery_start": stamps.dt.tz_localize("UTC") if "[UTC]" in tcol else local_to_utc(stamps)})
    for c in FIELDS:
        src = next((s for s in df.columns[1:] if COLUMNS[s] == c), None)
        out[c] = (pd.to_numeric(df[src].str.strip().replace("", np.nan), errors="raise").astype("float64")
                  if src else np.nan)
    for c in PRICES:
        out[c] = eur_mwh(out[c], f"{name} {c}")
    return out


def fetch(start: dt.datetime, end: dt.datetime, now: dt.datetime | None = None) -> pd.DataFrame:
    now = now or dt.datetime.now(dt.timezone.utc)
    frames = []
    for y in years(start, end):
        body = get_year(y, now)
        if body is not None:
            frames.append(parse(body, f"control-area-balance-{y}.csv"))
    if not frames:
        return pd.DataFrame({"delivery_start": pd.Series([], dtype="datetime64[ns, UTC]"),
                             **{c: pd.Series([], dtype="float64") for c in FIELDS}})
    out = pd.concat(frames, ignore_index=True)
    off = out["delivery_start"][out["delivery_start"].dt.minute % 15 != 0]
    if len(off):
        raise ValueError(f"stamps off the quarter-hour grid: {off.head(3).tolist()}")
    if out["delivery_start"].duplicated().any():
        dup = out["delivery_start"][out["delivery_start"].duplicated()].head(3).tolist()
        raise ValueError(f"a quarter-hour in two rows (two year files?): {dup}")
    return out
