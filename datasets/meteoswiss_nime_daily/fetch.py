# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the manual precipitation and snow network of MeteoSwiss (open data, STAC collection
ch.meteoschweiz.ogd-nime): fresh snow, snow depth and precipitation per station and day (table
measurements), and the list of its stations (table stations, no time column: each fetch returns
it whole and the server replaces it).

Files (one STAC item per station, no key): ogd-nime_<abbr>_d_historical.csv (rewritten once a
year) and ogd-nime_<abbr>_d_recent.csv (1 January to yesterday); the station list
ogd-nime_meta_stations.csv. The code that reads the station files is the same as in
meteoswiss_smn_hourly/fetch.py, whose docstring gives the measurements of the files.

Measured 2026-11-15 (WP5.7) and 2026-11-01 (swissgrid project, data/meteoswiss/README.md,
section 3, QA test 12):

- 274 STAC items, 273 with data files (JUN has none). ogd-nime_meta_stations.csv lists 270
  stations; KLO, VAD, PAY and ULR have files but no row there. KLO's recent file, rewritten on
  2026-01-01, holds 2025: KLO, PAY and VAD stop on 2025-12-31.
- hns000d0 and rre150d0: "daily total 6 UTC - 6 UTC following day"; hto000d0: "morning
  measurement at 6 UTC" (ogd-nime_meta_parameters.csv). The stamp D (dd.mm.yyyy 00:00) names the
  day that starts at D 06:00 UTC: rre150d0 equals SwissMetNet's rre150d0 of the same station and
  D within 0.05 mm on 100.0 % of 191,138 station-days (2018 on, 60 stations in both networks),
  41 % when shifted by one day; fresh snow of D correlates 0.749 with the change of snow depth
  from D to D + 1, 0.186 with the change from D - 1 to D. Stored as delivery_start = D 06:00 UTC,
  with the column reference_date = D.
- Missing values are empty fields; no sentinel and no negative value. Fresh snow and snow depth
  are empty on 19 % of the rows (stations that measure only precipitation).
"""
from __future__ import annotations

import datetime as dt
import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

COLLECTION = "ch.meteoschweiz.ogd-nime"
STAC = "https://data.geo.admin.ch/api/stac/v1/collections"
GRANULARITY = "d"
MEASUREMENTS = {"hns000d0": "fresh_snow", "hto000d0": "snow_depth", "rre150d0": "precipitation"}
DAY_START = dt.timedelta(hours=6)  # the day D runs [D 06:00, D + 1 06:00) UTC
STATIONS = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-nime/ogd-nime_meta_stations.csv"
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


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.strip(), errors="raise").astype("float64")


def stations() -> pd.DataFrame:
    """The station list, the same columns as meteoswiss_smn_stations.stations."""
    content = _get(STATIONS)
    if content is None:
        raise RuntimeError(f"{STATIONS}: not found")
    s = pd.read_csv(io.BytesIO(content), sep=";", encoding="cp1252", dtype=str)
    need = ["station_abbr", "station_name", "station_canton", "station_wigos_id", "station_type_en",
            "station_dataowner", "station_data_since", "station_height_masl", "station_height_barometer_masl",
            "station_coordinates_lv95_east", "station_coordinates_lv95_north", "station_coordinates_wgs84_lat",
            "station_coordinates_wgs84_lon", "station_exposition_en", "station_url_en"]
    missing = [c for c in need if c not in s.columns]
    if missing or s.empty:
        raise RuntimeError(f"{STATIONS}: columns {missing} missing, or no rows")
    return pd.DataFrame({
        "station": s["station_abbr"].str.strip(),
        "name": s["station_name"],
        "canton": s["station_canton"],
        "wigos_id": s["station_wigos_id"],
        "station_type": s["station_type_en"],
        "data_owner": s["station_dataowner"],
        "data_since": pd.to_datetime(s["station_data_since"].str.strip(), format="%d.%m.%Y").dt.date,
        "height": _num(s["station_height_masl"]),
        "barometer_height": _num(s["station_height_barometer_masl"]),
        "lv95_east": _num(s["station_coordinates_lv95_east"]),
        "lv95_north": _num(s["station_coordinates_lv95_north"]),
        "lat": _num(s["station_coordinates_wgs84_lat"]),
        "lon": _num(s["station_coordinates_wgs84_lon"]),
        "exposition": s["station_exposition_en"],
        "url": s["station_url_en"],
    })


def _stamps(start: dt.datetime, end: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """The stamps [lo, hi) of the rows whose delivery_start = D + 6 h falls in [start, end)."""
    lo = start - DAY_START
    day = lo.replace(hour=0, minute=0, second=0, microsecond=0)
    return (day if day == lo else day + dt.timedelta(days=1)), end - DAY_START


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    items = _items()
    params = list(MEASUREMENTS)
    lo, hi = _stamps(start, end)
    with ThreadPoolExecutor(WORKERS) as pool:
        parts = [p for p in pool.map(lambda it: _read(it, lo, hi, params), items) if p is not None]
    raw = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["station", "stamp", *params])
    stamp = pd.to_datetime(raw["stamp"], utc=True)
    m = pd.DataFrame({"station": raw["station"].astype(str), "delivery_start": stamp + DAY_START,
                      "reference_date": stamp.dt.date})
    for p, c in MEASUREMENTS.items():
        m[c] = raw[p].astype("float64")
    m = m[m[list(MEASUREMENTS.values())].notna().any(axis=1)]
    m = m[(m["delivery_start"] >= start) & (m["delivery_start"] < end)].reset_index(drop=True)
    _check_cover(m, "delivery_start", start, end)
    st = stations()
    say(f"[{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): {len(items)} stations listed, {m['station'].nunique()} with "
        f"values, {len(m)} rows; {len(st)} stations in the list; {time.time() - t0:.0f} s")
    return {"measurements": m, "stations": st}
