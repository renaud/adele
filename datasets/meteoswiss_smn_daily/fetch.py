# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the daily values of the SwissMetNet stations (MeteoSwiss open data, STAC collection
ch.meteoschweiz.ogd-smn): sunshine, global radiation, temperature, humidity, wind, precipitation,
snow depth, pressure and foehn index per station and day.

Files (one STAC item per station, no key): ogd-smn_<abbr>_d_historical.csv (the whole history to
31 December of last year, rewritten once a year) and ogd-smn_<abbr>_d_recent.csv (1 January to
yesterday, rewritten at 01 and 10 UTC). The code that reads the files is the same as in
meteoswiss_smn_hourly/fetch.py, whose docstring gives the measurements of the files.

Measured 2026-11-15 (WP5.7) and 2026-10-31 (swissgrid project, data/meteoswiss/README.md,
section 5, where each window below was rebuilt from 10-minute or hourly values):

- Sizes over the 159 stations: d_recent 7 MB, d_historical 463 MB (158 stations; BER from
  1864-01-01 to 2025-12-31, 59,170 rows).
- The stamp D (dd.mm.yyyy 00:00) is the start of the day. From 2018-01-01 a value covers the UTC
  day [D 00:00, D + 1 00:00); before 2018 it covers [D - 1 23:40, D 23:40) (100 % of 33,800 to
  36,100 station-days of 2015-2017 match this window, 63 to 77 % the one 40 min later; for
  2010-2014 the shift is assumed). Stored as delivery_start = the start of that window, and the
  column reference_date = D, the date by which MeteoSwiss names the value (its "reference_timestamp").
- rre150d0 covers [D 06:00, D + 1 06:00) (100 % match from 2018), [D 05:40, D + 1 05:40) before.
  htoautd0 is the snow depth read at D 06:00. Both stay in the row of D, with names that say it.
- The daily sunshine is the sum of the 24 hourly values of the UTC day on 99.996 % of the
  station-days from 2018.
"""
from __future__ import annotations

import datetime as dt
import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

COLLECTION = "ch.meteoschweiz.ogd-smn"
STAC = "https://data.geo.admin.ch/api/stac/v1/collections"
GRANULARITY = "d"
MEASUREMENTS = {
    "sre000d0": "sunshine", "gre000d0": "global_radiation", "tre200d0": "temperature",
    "tre200dn": "temperature_min", "tre200dx": "temperature_max", "ure200d0": "humidity",
    "fkl010d0": "wind_speed", "fkl010d1": "gust", "rka150d0": "precipitation",
    "rre150d0": "precipitation_06utc", "htoautd0": "snow_depth_06utc", "prestad0": "pressure_qfe",
    "pp0qffd0": "pressure_qff", "wcc006d0": "foehn",
}
SWITCH = pd.Timestamp("2018-01-01 00:00", tz="UTC")  # first day on the UTC day
WORKERS = 8
UTC = dt.timezone.utc
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "adele-fetch/1 (open data)"


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _get(url: str) -> bytes | None:
    """The body of url, None when the file does not exist (403 or 404). Retries a failed request."""
    for attempt in range(4):
        try:
            r = SESSION.get(url, timeout=(30, 600))
            if r.status_code in (403, 404):
                return None
            r.raise_for_status()
            size = r.headers.get("Content-Length")
            if size is not None and int(size) != len(r.content):
                raise IOError(f"{url}: got {len(r.content)} bytes, Content-Length {size}")
            return r.content
        except (requests.RequestException, IOError):
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def _items() -> list[dict]:
    """Every STAC item (station) of the collection, following the rel=next links."""
    url, out = f"{STAC}/{COLLECTION}/items?limit=100", []
    while url:
        r = SESSION.get(url, timeout=(30, 120))
        r.raise_for_status()
        js = r.json()
        out += js.get("features", [])
        url = next((ln["href"] for ln in js.get("links", []) if ln.get("rel") == "next"), None)
    if not out:
        raise RuntimeError(f"{COLLECTION}: the STAC API lists no station")
    return out


def _ts(text: str) -> dt.datetime:
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def _plan(item: dict, lo: dt.datetime, hi: dt.datetime) -> tuple[str | None, list[tuple]]:
    """Which files of one station hold the stamps [lo, hi): (recent href or None, [(href, first, end)]).

    A historical file holds the stamps from its decade's start up to the end of its decade or to
    1 January of the year in which it was last rewritten (its `updated` field), whichever comes
    first: the yearly rewrite adds the year before. The recent file is read when the window reaches
    past every historical file; then _read() lets its first stamp cut the historical part.
    """
    recent, hist = None, []
    for name, a in item.get("assets", {}).items():
        kind = name.rsplit(".", 1)[0].split("_", 2)[-1]  # h_recent, h_historical_2010-2019, ...
        if kind == f"{GRANULARITY}_recent":
            recent = a["href"]
        elif kind.startswith(f"{GRANULARITY}_historical"):
            years = kind.rsplit("_", 1)[-1]
            first = dt.datetime(int(years[:4]), 1, 1, tzinfo=UTC) if years[:1].isdigit() else dt.datetime.min.replace(tzinfo=UTC)
            last = dt.datetime(int(years[5:]) + 1, 1, 1, tzinfo=UTC) if "-" in years else dt.datetime.max.replace(tzinfo=UTC)
            if a.get("updated"):
                last = min(last, dt.datetime(_ts(a["updated"]).year, 1, 1, tzinfo=UTC))
            hist.append((a["href"], first, last))
    reach = max((h[2] for h in hist), default=dt.datetime.min.replace(tzinfo=UTC))
    return (recent if hi > reach else None), [h for h in hist if h[1] < hi and h[2] > lo]


def _parse(content: bytes, params: list[str], abbr: str, url: str) -> pd.DataFrame:
    head = content[:4000].split(b"\n", 1)[0].decode("cp1252").strip().split(";")
    if head[:2] != ["station_abbr", "reference_timestamp"]:
        raise RuntimeError(f"{url}: unexpected header {head[:3]}")
    keep = [p for p in params if p in head]
    # values as float64: an empty field is NaN, any other text (also "NA" or "n/a") fails the parse
    df = pd.read_csv(io.BytesIO(content), sep=";", encoding="cp1252", usecols=["station_abbr", "reference_timestamp", *keep],
                     dtype={"station_abbr": str, "reference_timestamp": str, **{p: "float64" for p in keep}},
                     keep_default_na=False, na_values=[""])  # only an empty field is missing: "NA" fails
    if (df["station_abbr"] != abbr).any():
        raise RuntimeError(f"{url}: rows of another station: {sorted(set(df['station_abbr']) - {abbr})[:5]}")
    out = pd.DataFrame({"stamp": pd.to_datetime(df["reference_timestamp"], format="%d.%m.%Y %H:%M", utc=True)})
    for p in params:
        out[p] = df[p] if p in keep else float("nan")
    return out


def _read(item: dict, lo: dt.datetime, hi: dt.datetime, params: list[str]) -> pd.DataFrame | None:
    """The rows of one station with a stamp in [lo, hi), from the files that _plan picks."""
    abbr = item["id"].upper()
    recent, hist = _plan(item, lo, hi)
    parts, cut = [], hi
    if recent:
        content = _get(recent)
        if content is not None:
            r = _parse(content, params, abbr, recent)
            if len(r):
                cut = min(cut, r["stamp"].min().to_pydatetime())
            parts.append(r)
    for href, first, last in hist:
        if first >= cut or last <= lo:
            continue
        content = _get(href)
        if content is not None:
            parts.append(_parse(content, params, abbr, href))
    if not parts:
        return None
    d = pd.concat(parts, ignore_index=True)
    d = d[(d["stamp"] >= lo) & (d["stamp"] < hi)]
    d = d.drop_duplicates("stamp", keep="first")  # the recent file comes first: it wins
    d.insert(0, "station", abbr)
    return d


def _check_cover(rows: pd.DataFrame, col: str, start: dt.datetime, end: dt.datetime) -> None:
    """Fail when the source returned nothing near the start or the end of the window.

    Files are read whole, so a source can't cut an answer; but a file can be missing, stale or
    shorter than its period. Every station stops some day, so the check is over all stations.
    """
    today = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    last_expected = min(end, today - dt.timedelta(days=2)) - dt.timedelta(days=2)
    if start < last_expected and not (rows[col] >= last_expected).any():
        raise RuntimeError(f"no row from {last_expected:%Y-%m-%d %H:%M} on, in a window that ends {end:%Y-%m-%d %H:%M}: "
                           "a file is missing or was not rewritten")
    if end - start > dt.timedelta(days=4) and start < last_expected and not (rows[col] < start + dt.timedelta(days=2)).any():
        raise RuntimeError(f"no row in the first two days of the window starting {start:%Y-%m-%d %H:%M}")


def _stamps(start: dt.datetime, end: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """The stamps [lo, hi) of the rows whose delivery_start (D, or D - 20 min before 2018) falls in
    [start, end): D in [start, end + 20 min), and D is a midnight, so lo is rounded up to a day."""
    lo = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if lo < start:
        lo += dt.timedelta(days=1)
    return lo, end + dt.timedelta(minutes=20)


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    t0 = time.time()
    items = _items()
    params = list(MEASUREMENTS)
    lo, hi = _stamps(start, end)
    with ThreadPoolExecutor(WORKERS) as pool:
        parts = [p for p in pool.map(lambda it: _read(it, lo, hi, params), items) if p is not None]
    raw = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["station", "stamp", *params])
    stamp = pd.to_datetime(raw["stamp"], utc=True)
    shift = (stamp < SWITCH).map({True: 20, False: 0}).astype("int64")
    m = pd.DataFrame({"station": raw["station"].astype(str),
                      "delivery_start": stamp - pd.to_timedelta(shift, unit="min"),
                      "reference_date": stamp.dt.date})
    for p, c in MEASUREMENTS.items():
        m[c] = raw[p].astype("float64")
    m = m[m[list(MEASUREMENTS.values())].notna().any(axis=1)]
    m = m[(m["delivery_start"] >= start) & (m["delivery_start"] < end)].reset_index(drop=True)
    _check_cover(m, "delivery_start", start, end)
    say(f"[{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): {len(items)} stations listed, {m['station'].nunique()} with "
        f"values, {len(m)} rows, {time.time() - t0:.0f} s")
    return m
