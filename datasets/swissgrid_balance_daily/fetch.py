# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Swissgrid's balance of the control area for the last 24 hours: the file
`control-area-balance-daily.csv`, one row per quarter-hour, a new quarter-hour every 15 minutes,
the oldest dropped (adele.raw: keep).

Draft by Claude, 2026-11-15 (WP4). Facts from the Swissgrid poller's archive (2026-09-27 to
2026-10-17, 1,795 kept answers; docs/work-packages/WP4-files-overwritten-or-revised.md):

- 95 to 98 rows, `;` as separator, `.` as decimal point, the header `Date Time [UTC];...` with
  the stamps as `dd.mm.yyyy HH:MM` in UTC, the start of the quarter-hour (SED,
  sources/ch_swissgrid/README.md: the TSI identity holds row by row at that stamp). The last
  row is 31 to 45 minutes old when the file changes.
- The same 13 columns as the 2026 file of the year (`control-area-balance-2026.csv`).
- Rows are revised while they are in the file: 34 of 2,029 quarter-hours changed once, a median
  of 57 minutes after their start, at most 24 h 35 min. 13 of them were first published with
  every component blank and only a TSI value (placeholders), then filled.
- TSI = -(the sum of the ten components) on every row with all components, within 1.1e-07 MW.
- AE-Preis is the provisional single imbalance price in EUR-cent/kWh (SED: the monthly XML files
  of the final prices carry `<unit>ct/kWh</unit>`, and the values match them). x10 gives
  EUR/MWh; the source has at most two decimals, so the result is rounded to 0.1 EUR/MWh (as SED
  did, to drop float artefacts), and a value that would lose more than 1e-6 is refused.

The URL as in swissgrid_tsi: a seed of 2026-09-27, looked up again on Swissgrid's pages on a 404.
"""
from __future__ import annotations

import io
import re
from urllib.parse import urljoin

import numpy as np
import pandas as pd
import requests

NAME = "control-area-balance-daily.csv"
BASE = "https://www.swissgrid.ch"
SEED = BASE + "/dam/jcr:0bbafc76-e5bc-4126-bd99-41c939fe10e0/control-area-balance-daily.csv"
PAGES = [BASE + "/en/home/customers/topics/energy-data-ch.html",
         BASE + "/en/home/customers/topics/bgm/balance-energy.html"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; adele; research data archive)"}
TIMEOUT = 30

TIME = "Date Time [UTC]"
COLUMNS = {
    "Abgedeckte Bedarf der aFRR+": "afrr_up", "Abgedeckte Bedarf der aFRR-": "afrr_dn",
    "Abgedeckte Bedarf der SA mFRR+": "sa_mfrr_up", "Abgedeckte Bedarf der SA mFRR-": "sa_mfrr_dn",
    "Abgedeckte Bedarf der DA mFRR+": "da_mfrr_up", "Abgedeckte Bedarf der DA mFRR-": "da_mfrr_dn",
    "NRV+ (Import)": "nrv_import", "NRV- (Export)": "nrv_export",
    "FRCE+ (Import)": "frce_import", "FRCE- (Export)": "frce_export",
    "Total System Imbalance": "tsi", "AE-Preis": "price_single",
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


def get_file(name: str, seed: str) -> dict:
    url = seed
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        url = _find(name)
        if url is None:
            raise RuntimeError(f"{name}: 404 at {seed}, and no page of {PAGES} links it")
        print(f"{name}: the seed URL is stale, the file is now at {url}: update SEED in fetch.py")
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return {"name": name, "url": url, "body": r.content}


def download(start, end):
    """The file holds the last 24 hours: the window can't choose anything."""
    yield get_file(NAME, SEED)


def eur_mwh(ct_kwh: pd.Series, what: str) -> pd.Series:
    """EUR-cent/kWh --> EUR/MWh, rounded to 0.1; refused if the rounding would move a value by more than 1e-6."""
    v = ct_kwh * 10.0
    r = v.round(1)
    lost = (v - r).abs()
    if (lost > 1e-6).any():
        raise ValueError(f"{what}: a price with more than two decimals in ct/kWh: {ct_kwh[lost > 1e-6].head(3).tolist()}")
    return r


def parse(answers: list[dict]) -> pd.DataFrame:
    frames = []
    for a in answers:
        if a["name"] != NAME:
            raise ValueError(f"unexpected answer {a['name']!r}")
        df = pd.read_csv(io.BytesIO(a["body"]), sep=";", dtype=str, keep_default_na=False, encoding="utf-8")
        if not len(df.columns) or df.columns[0] != TIME:
            raise ValueError(f"{NAME}: the first column is {df.columns[:1].tolist()}, expected {TIME!r}")
        got = list(df.columns[1:])
        if got != list(COLUMNS):
            raise ValueError(f"{NAME}: columns {got}, expected {list(COLUMNS)}")
        df = df[df[TIME].str.strip() != ""]
        out = pd.DataFrame({"delivery_start": pd.to_datetime(df[TIME].str.strip(), format="%d.%m.%Y %H:%M", utc=True)})
        for src, dst in COLUMNS.items():
            out[dst] = pd.to_numeric(df[src].str.strip().replace("", np.nan), errors="raise").astype("float64")
        out["price_single"] = eur_mwh(out["price_single"], f"{NAME} AE-Preis")
        frames.append(out)
    if not frames:
        raise ValueError("no answer to parse")
    out = pd.concat(frames, ignore_index=True).drop_duplicates()
    off = out["delivery_start"][(out["delivery_start"].dt.minute % 15 != 0)]
    if len(off):
        raise ValueError(f"{NAME}: stamps off the quarter-hour grid: {off.head(3).tolist()}")
    if out["delivery_start"].duplicated().any():
        raise ValueError(f"{NAME}: one quarter-hour with two rows in answers received at the same time")
    return out.reset_index(drop=True)
