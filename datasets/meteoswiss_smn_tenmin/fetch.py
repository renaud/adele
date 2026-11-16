# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the 10-minute global radiation and sunshine duration of the SwissMetNet stations
(MeteoSwiss open data, STAC collection ch.meteoschweiz.ogd-smn).

Files (one STAC item per station, no key): ogd-smn_<abbr>_t_historical_<decade>.csv (rewritten
once a year) and ogd-smn_<abbr>_t_recent.csv (1 January to yesterday, rewritten at 01 and 10
UTC). The fetch reads a file only when the window needs it (_plan): a scheduled run of one day
reads the 159 recent files (852 MB); a window in 2020-2025 reads the decade files 2020-2029
(5.8 GB). The code that reads the files is the same as in meteoswiss_smn_hourly/fetch.py, whose
docstring gives the measurements of the files.

Measured 2026-11-15 (WP5.7) and 2026-10-31 (swissgrid project, data/meteoswiss/README.md):

- Sizes over the 159 stations: t_recent 852 MB, t_historical_2020-2029 5,844 MB (max 45 MB),
  t_historical_2010-2019 at 157 stations, t_historical_2000-2009 at 128.
- Stamp T = the end of the 10 minutes, [T - 10 min, T), also before 2018 (the hourly values of
  2017 and 2018 were rebuilt from the 10-minute values with both conventions). Stored as
  delivery_start = T - 10 min.
- The hourly global radiation is the mean of the six 10-minute values of [t, t + 1 h) on all but
  one of 3,580,115 station-hours (swissgrid project, QA test 4).
- t_recent of BER, read 2026-11-15: last stamp 2026-11-14 23:50.
- One negative 10-minute global radiation (MOA, 2024: -11 W/m2), kept as published.
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
GRANULARITY = "t"
MEASUREMENTS = {"gre000z0": "global_radiation", "sre000z0": "sunshine"}
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
    """The stamps [lo, hi) of the rows whose delivery_start = T - 10 min falls in [start, end).

    lo is rounded up to the 10 minutes, so that a window that starts at 23:50 on 31 December doesn't
    read the decade file that ends there.
    """
    lo = start + dt.timedelta(minutes=10)
    rest = dt.timedelta(minutes=lo.minute % 10, seconds=lo.second, microseconds=lo.microsecond)
    if rest:
        lo += dt.timedelta(minutes=10) - rest
    return lo, end + dt.timedelta(minutes=10)


def _table(raw: pd.DataFrame | None, start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    """The rows of one station, converted in the worker: the raw rows of all stations never sit in
    memory together."""
    if raw is None:
        raw = pd.DataFrame({"station": pd.Series(dtype=str), "stamp": pd.Series(dtype="datetime64[ns, UTC]"),
                            **{p: pd.Series(dtype="float64") for p in MEASUREMENTS}})
    m = pd.DataFrame({"station": raw["station"].astype(str),
                      "delivery_start": pd.to_datetime(raw["stamp"], utc=True) - pd.Timedelta(minutes=10)})
    for p, c in MEASUREMENTS.items():
        m[c] = raw[p].astype("float64")
    m = m[m[list(MEASUREMENTS.values())].notna().any(axis=1)]
    return m[(m["delivery_start"] >= start) & (m["delivery_start"] < end)]


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    t0 = time.time()
    items = _items()
    params = list(MEASUREMENTS)
    lo, hi = _stamps(start, end)
    with ThreadPoolExecutor(WORKERS) as pool:
        parts = list(pool.map(lambda it: _table(_read(it, lo, hi, params), start, end), items))
    m = pd.concat(parts, ignore_index=True)
    del parts
    _check_cover(m, "delivery_start", start, end)
    say(f"[{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): {len(items)} stations listed, {m['station'].nunique()} with "
        f"values, {len(m)} rows, {time.time() - t0:.0f} s")
    return m
