# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Swissgrid's 5-minute Total System Imbalance: the file `total-system-imbalance.csv`, which holds
one quarter-hour as three 5-minute values and is replaced every 15 minutes (adele.raw: keep).

Draft by Claude, 2026-11-15 (WP4). Facts from the Swissgrid poller's archive (2026-09-27 to
2026-10-17, 2,158 kept answers; docs/work-packages/WP4-files-overwritten-or-revised.md):

- An answer is about 120 bytes: a header `timestamp_utc,total_system_imbalance`, then three
  rows, e.g. `2026-10-09T23:45:00Z,-16.00`, `...23:50:00Z,6.97`, `...23:55:00Z,101.68`. Two
  decimals. The file of the quarter-hour that starts at Q appears at about Q + 15 min.
- The stamps are the starts of 5-minute intervals: the mean of the three values of a quarter-hour
  is the quarter-hour TSI of the control-area balance within 0.55 MW (median 0.07 MW, 1,849
  quarter-hours), and far from it with end stamps (median 17 MW).
- No 5-minute value changed between two answers in those 20 days.
- 80 of 1,932 quarter-hours are in no kept answer: network errors (46) and minutes in which
  Swissgrid kept serving the previous file (33). Swissgrid sometimes serves the previous file
  again for a minute (306 of the 2,158 answers repeat an older one).

The URL holds an id (`/dam/jcr:<id>/`) that changes when Swissgrid uploads the file anew. SEED
is the URL of 2026-09-27; on a 404 the file is looked up by name on Swissgrid's pages, as the
poller does, and the run says that SEED is stale.
"""
from __future__ import annotations

import io
import re
from urllib.parse import urljoin

import pandas as pd
import requests

NAME = "total-system-imbalance.csv"
BASE = "https://www.swissgrid.ch"
SEED = BASE + "/dam/jcr:f0f9140c-2aa5-42f1-9594-2da51cf93547/total-system-imbalance.csv"
PAGES = [BASE + "/en/home/customers/topics/energy-data-ch.html",
         BASE + "/en/home/customers/topics/bgm/balance-energy.html"]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; adele; research data archive)"}
TIMEOUT = 20
COLUMNS = ["timestamp_utc", "total_system_imbalance"]


def _find(name: str) -> str | None:
    """The URL of a file named `name` among the /dam/ links of Swissgrid's pages."""
    for page in PAGES:
        r = requests.get(page, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        for href in re.findall(r'href="([^"]*/dam/[^"]+)"', r.text):
            url = urljoin(page, href.replace("&amp;", "&"))
            if url.split("?")[0].rsplit("/", 1)[-1] == name:
                return url
    return None


def get_file(name: str, seed: str) -> dict:
    """One answer: the file at its seed URL, or found again on the pages after a 404."""
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
    """The file holds only the latest quarter-hour: the window can't choose anything."""
    yield get_file(NAME, SEED)


def parse(answers: list[dict]) -> pd.DataFrame:
    frames = []
    for a in answers:
        if a["name"] != NAME:
            raise ValueError(f"unexpected answer {a['name']!r}")
        df = pd.read_csv(io.BytesIO(a["body"]), dtype=str, keep_default_na=False)
        if list(df.columns) != COLUMNS:
            raise ValueError(f"{NAME}: columns {list(df.columns)}, expected {COLUMNS}")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    out = pd.DataFrame({
        "delivery_start": pd.to_datetime(df["timestamp_utc"], format="%Y-%m-%dT%H:%M:%SZ", utc=True),
        "tsi": pd.to_numeric(df["total_system_imbalance"], errors="raise").astype("float64"),
    })
    off = out["delivery_start"][(out["delivery_start"].dt.minute % 5 != 0) | (out["delivery_start"].dt.second != 0)]
    if len(off):
        raise ValueError(f"{NAME}: stamps off the 5-minute grid: {off.head(3).tolist()}")
    # answers received at the same time (an import) may repeat a row; a stamp with two values can't be told apart
    out = out.drop_duplicates()
    if out["delivery_start"].duplicated().any():
        raise ValueError(f"{NAME}: one stamp with two values in answers received at the same time")
    return out
