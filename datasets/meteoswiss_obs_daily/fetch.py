# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the daily visual observations of MeteoSwiss (open data, STAC collection
ch.meteoschweiz.ogd-obs): cloud cover, and days with fog, rain, snowfall, hail and snow cover, per
station and calendar day.

Files (one STAC item per station, no key): ogd-obs_<abbr>_d_historical.csv and
ogd-obs_<abbr>_d_recent.csv. The code that reads the files is the same as in
meteoswiss_smn_hourly/fetch.py, whose docstring gives the measurements of the files.

Measured 2026-11-15 (WP5.7) and 2026-11-01 (swissgrid project, data/meteoswiss/README.md,
sections 3, 9 and 11):

- 20 STAC items; 18 have a recent file (SIO and PAY have none). Only 8 stations are in
  ogd-obs_meta_stations.csv (ALT, BAS, CHU, GSB, JUN, SAE, SIO, SMA); 11 of the 12 others are
  SwissMetNet stations, TAV is in no MeteoSwiss list. AIG's recent file, rewritten on
  2026-01-01 10 UTC, holds 2025-01-01 to 2025-12-31 and was not rewritten since: 12 stations stop
  on 2025-12-31 or earlier.
- Daily aggregates only (the single observations are not published). The y/n flags hold only 0
  and 1 (datatype Integer, unit y/n in ogd-obs_meta_parameters.csv); stored as booleans, and a
  fetch fails on any other value. An empty field is a day without a value, not a 0: in the AIG
  file of December 2025 the fog flag is empty while serene and dark day hold 0 or 1.
- The stamp D (dd.mm.yyyy 00:00): the parameter list does not say which hours make the day. The
  daily cloud cover correlates with SwissMetNet's daily sunshine (UTC day) at -0.775 on the same
  date, -0.39 and -0.40 one day before and after: D is the calendar day of the observations
  (observers read 3 to 8 times a day, MeteoSwiss Technical Report 266). Stored as delivery_date
  = D, in the zone Europe/Zurich: assumed, the source states none.
- nto000d0 (cloud cover, daily mean, %) comes in steps of 100/24 %. One value of 133 % (SIO,
  2011-12-18, with dark day = 1): kept as published.
"""
from __future__ import annotations

import datetime as dt
import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import pandas as pd
import requests

COLLECTION = "ch.meteoschweiz.ogd-obs"
STAC = "https://data.geo.admin.ch/api/stac/v1/collections"
GRANULARITY = "d"
CLOUD = {"nto000d0": "cloud_cover"}
FLAGS = {
    "w5p002d0": "fog_day", "nto002d0": "serene_day", "nto008d0": "dark_day", "est000d0": "snow_cover_day",
    "w1p012d0": "rain_day", "w2p002d0": "snowfall_day", "w2p001d0": "rain_and_snow_day", "w3p002d0": "hail_day",
}
ZONE = ZoneInfo("Europe/Zurich")  # the zone of the table (assumed, see above)
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


def _days(start: dt.datetime, end: dt.datetime) -> tuple[dt.date, dt.date]:
    """The first and last local day that overlap [start, end), in the zone of the table."""
    return start.astimezone(ZONE).date(), (end - dt.timedelta(microseconds=1)).astimezone(ZONE).date()


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    t0 = time.time()
    items = _items()
    params = [*CLOUD, *FLAGS]
    first, last = _days(start, end)
    lo = dt.datetime.combine(first, dt.time(), UTC)  # the stamp of day D is D 00:00
    hi = dt.datetime.combine(last + dt.timedelta(days=1), dt.time(), UTC)
    with ThreadPoolExecutor(WORKERS) as pool:
        parts = [p for p in pool.map(lambda it: _read(it, lo, hi, params), items) if p is not None]
    raw = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["station", "stamp", *params])
    stamp = pd.to_datetime(raw["stamp"], utc=True)
    if len(stamp) and (stamp.dt.hour.any() or stamp.dt.minute.any()):
        raise RuntimeError("a daily stamp is not at 00:00")
    m = pd.DataFrame({"station": raw["station"].astype(str), "delivery_date": stamp.dt.date,
                      "cloud_cover": raw["nto000d0"].astype("float64")})
    for p, c in FLAGS.items():
        v = raw[p].astype("float64")
        bad = v.notna() & ~v.isin([0.0, 1.0])
        if bad.any():
            raise RuntimeError(f"{p}: values other than 0 and 1: {sorted(v[bad].unique())[:5]}")
        m[c] = v.map({0.0: False, 1.0: True}).astype("boolean")
    m = m[m[["cloud_cover", *FLAGS.values()]].notna().any(axis=1)].reset_index(drop=True)
    # the visual network shrank at the end of 2025: check the end over the stations that report now
    when = pd.to_datetime(m["delivery_date"]).dt.tz_localize(UTC)
    _check_cover(pd.DataFrame({"t": when}), "t", start, end)
    say(f"[{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): {len(items)} stations listed, {m['station'].nunique()} with "
        f"values, {len(m)} rows, days {first} .. {last}, {time.time() - t0:.0f} s")
    return m
