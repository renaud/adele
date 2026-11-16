# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch hourly measurements of the SwissMetNet stations (MeteoSwiss open data, STAC collection
ch.meteoschweiz.ogd-smn): radiation, sunshine, temperature, humidity, pressure, wind,
precipitation and foehn index per station and hour (table measurements), and the automatic snow
depth read at each full hour (table snow_depth).

Files (one STAC item per station, no key): ogd-smn_<abbr>_h_historical_<decade>.csv (from the
start of the measurement to the end of the decade or to 31 December of last year, rewritten once
a year) and ogd-smn_<abbr>_h_recent.csv (1 January to yesterday, rewritten at 01 and 10 UTC).
The fetch reads a file only when the window needs it (see _plan): a scheduled run of one day reads
the 159 recent files (149 MB); a window in 2015-2019 reads the decade files 2010-2019 (1.5 GB).

Measured 2026-11-15 (WP5.7; the swissgrid project measured the rest on 2026-10-31, its
data/meteoswiss/README.md, sections 5 and 9):

- 159 STAC items (stations); 157 have h_historical_2010-2019 and 158 h_historical_2020-2029.
  Sizes over all stations: h_recent 149 MB, h_historical_2010-2019 1,487 MB, 2020-2029 1,031 MB.
- CSV: Windows-1252, ";" separated, CRLF, first columns station_abbr;reference_timestamp, stamps
  "dd.mm.yyyy HH:MM" in UTC, missing values are empty fields (no sentinel), an empty column when
  a station does not measure the parameter.
- The historical files were rewritten on 2026-02-18 (Last-Modified, and the `updated` field of
  the STAC asset): the yearly update came in February, not on 1 January. The file 2020-2029 of BER
  ends with the stamp 2025-12-31 23:00; its h_recent starts with 2026-01-01 00:00. A recent file
  rewritten on 2026-01-01 10 UTC still held all of 2025 (ogd-obs, AIG, a station that stopped).
- h_recent of BER, read 2026-11-15 11:43 UTC: last stamp 2026-11-14 23:00. The hour stamped
  2026-11-15 00:00 (the last hour of the 14th) comes with the next rewrite.
- Stamp T of an hourly value: the end of the hour from 2018-01-01 00:00 on ([T - 60 min, T));
  before, the "SYNOP schedule": [T - 20 min, T + 40 min). Proven against 10-minute data in the
  swissgrid project (100 % of the hours of 2017-H2 match the SYNOP window, 100 % of 2018-2019 the
  clock hour). Stored here as delivery_start = the start of that interval: T - 60 min from 2018,
  T - 20 min before (so the minute is 40 before 2018).
- htoauths ("Snow depth (automatic measurement); hourly current value") is a reading, not a mean,
  taken at the end of MeteoSwiss's hour. Measured on the stored data (2026-11-16): the daily value
  "read at 06 UTC" (htoautd0) equals the hourly reading stamped 06:00 on 100 % of 31,515 snow days
  from 2018, and the one stamped 05:00 on 100 % of 11,050 snow days of 2015-2017 (06:00: 61 %).
  Before 2018 the daily windows start 20 min early, so that daily reading is at 05:40, the end of
  the SYNOP hour stamped 05:00. Stored in snow_depth with valid_at = T from 2018, T + 40 min before.
- MeteoSwiss checks the data during 5 days, and checks daily precipitation by hand "around the end
  of the upcoming month" (FAQ, opendatadocs.meteoswiss.ch): values change after publication. The
  h_recent of LUZ changed 18 morning radiation values by +2 to +63 W/m2 between 2026-10-28 and
  2026-10-31, up to 33 days after the hour.
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
GRANULARITY = "h"
# MeteoSwiss parameter --> column of the table measurements (all hourly means or totals)
MEASUREMENTS = {
    "gre000h0": "global_radiation", "ods000h0": "diffuse_radiation", "oli000h0": "longwave_radiation",
    "sre000h0": "sunshine", "tre200h0": "temperature", "ure200h0": "humidity",
    "prestah0": "pressure_qfe", "pp0qffh0": "pressure_qff", "fkl010h0": "wind_speed",
    "dkl010h0": "wind_direction", "fkl010h1": "gust", "rre150h0": "precipitation", "wcc006h0": "foehn",
}
SNOW = {"htoauths": "snow_depth"}  # a reading at the stamp
SWITCH = pd.Timestamp("2018-01-01 00:00", tz="UTC")  # first stamp of the clock hours
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
    """The stamps [lo, hi) of the rows whose delivery_start or valid_at falls in [start, end).

    measurements: delivery_start = T - 60 min (clock hours) or T - 20 min (SYNOP hours), so T lies
    in [start + 20 min, end + 60 min). snow_depth: valid_at = T (clock hours) or T + 40 min (SYNOP),
    so T lies in [start - 40 min, end). Stamps are full hours: lo is rounded up to the hour.
    A window that starts at 23:00 on 31 December of a decade's last year reads both decade files:
    the hourly mean of 23:00-24:00 is stamped 00:00 (the new file), the snow reading of 23:00 is
    stamped 23:00 (the old file).
    """
    lo = start - dt.timedelta(minutes=40)
    if lo >= SWITCH:  # clock hours: the earliest stamp is the snow reading at start
        lo = start
    if lo.minute or lo.second or lo.microsecond:
        lo = lo.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    return lo, end + dt.timedelta(hours=1)


def _tables(raw: pd.DataFrame | None, start: dt.datetime, end: dt.datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The rows of one station for the two tables. Run in the worker, so that the raw rows of all
    stations never sit in memory together (a window of 5 years took 3.5 GB that way)."""
    if raw is None:
        raw = pd.DataFrame({"station": pd.Series(dtype=str), "stamp": pd.Series(dtype="datetime64[ns, UTC]"),
                            **{p: pd.Series(dtype="float64") for p in [*MEASUREMENTS, *SNOW]}})
    stamp = pd.to_datetime(raw["stamp"], utc=True)
    synop = stamp < SWITCH
    m = pd.DataFrame({"station": raw["station"].astype(str),
                      "delivery_start": stamp - pd.to_timedelta(synop.map({True: 20, False: 60}).astype("int64"), unit="min")})
    for p, c in MEASUREMENTS.items():
        m[c] = raw[p].astype("float64")
    m = m[m[list(MEASUREMENTS.values())].notna().any(axis=1)]
    m = m[(m["delivery_start"] >= start) & (m["delivery_start"] < end)]
    # the reading belongs to the end of MeteoSwiss's hour: T from 2018, T + 40 min on the SYNOP schedule
    read_at = stamp + pd.to_timedelta(synop.map({True: 40, False: 0}).astype("int64"), unit="min")
    s = pd.DataFrame({"station": raw["station"].astype(str), "valid_at": read_at,
                      "snow_depth": raw["htoauths"].astype("float64")})
    s = s[s["snow_depth"].notna() & (s["valid_at"] >= start) & (s["valid_at"] < end)]
    return m, s


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    items = _items()
    params = [*MEASUREMENTS, *SNOW]
    lo, hi = _stamps(start, end)
    with ThreadPoolExecutor(WORKERS) as pool:
        parts = list(pool.map(lambda it: _tables(_read(it, lo, hi, params), start, end), items))
    m = pd.concat([p[0] for p in parts], ignore_index=True)
    s = pd.concat([p[1] for p in parts], ignore_index=True)
    del parts
    _check_cover(m, "delivery_start", start, end)
    say(f"[{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): {len(items)} stations listed, {m['station'].nunique()} with "
        f"measurements, {len(m)} + {len(s)} rows, {time.time() - t0:.0f} s")
    return {"measurements": m.reset_index(drop=True), "snow_depth": s.reset_index(drop=True)}
