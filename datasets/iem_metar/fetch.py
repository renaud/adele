# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.31", "pandas>=2.2"]
# ///
"""METAR of 8 Swiss lowland aerodromes, from the archive of the Iowa Environmental Mesonet (IEM),
https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py (no key).

One request per window of at most 400 days, for all stations, the raw text only (data=metar). The
columns are parsed here from the text up to TEMPO, BECMG, NOSIG or RMK. IEM's own columns are not
used (measured 2026-11-23): they drop CB and TCU, the bases `///` and NDV, give temperature in
Fahrenheit and visibility in miles, and precipitation as 0.00 on 1,540,813 of 1,540,876 rows,
because Swiss METARs hold none. IEM's documentation asks for at most one request per second and
for one request for all stations ("make an hourly request for all stations"); a request of more
than 1,000 station-years is refused (HTTP 422).

Measured 2026-11-23 on the whole history, 8 stations, 2015-01-01 to 2026-11-23 (248 MB of CSV,
1,540,876 rows):

- (station, time) is unique, and the stamp of IEM (`valid`) equals the ddhhmm of the text in every
  row. Times are UTC. valid_at is the time of the report, of :20 or :50; other minutes occur
  (special reports, 2,024 rows at LSME in 2015-2018, 59 at LSMD, 84 at LSMP, few elsewhere).
- Rows rebuilt by IEM from another archive, marked IEM_GHCNH in the text, are dropped: 32 rows at
  LSGG, at full hours, with a made-up AUTO, mostly without cloud groups. Before 2013 most of IEM's
  rows at LSZH and LSGG are of this kind (IEM_DS3505, from NCEI's surface database; 2003 half).
- LSMP, LSME, LSMD: about 24 rows a day (only :50) until 2018-07-22, about 46 from 2018-07-24, with
  gaps of up to 7 days (some over weekends). The others: 48 a day, except LSZH, which has almost
  no 00:20 report until 2021-04-07 (47 a day).
- AUTO: LSGG almost never in daytime until April 2024, always from May 2024; LSMP almost never in
  2017-2018 and 60-70 % of daytime rows from 2020; LSZH only outside 09-15 UTC, from 2021.
- CB or TCU: 203 of 501,882 rows at the three military stations (LSMP, LSME, LSMD), where they are
  mostly not reported; thousands of rows a year in all at the civil ones.
- Corrections: 1,218 rows begin with COR, nearly all from 2020 on (about 200 a year); before, a
  correction carries no mark, if there are any. IEM keeps one row per time, and it is not known
  which version it keeps: in 8 days compared with ogimet.com (2,804 reports, none missing at either),
  2,781 texts are equal, ogimet cuts 16 long ones, and 7 are other versions of the report
  (qa/published_figures_iem_metar.md).
- 400 rows of the last 25 hours at aviationweather.gov: the same text in IEM for every row (IEM
  has one report of LSZG that aviationweather.gov has not). Beyond 25 hours not compared; its API
  cuts an answer at 400 rows without saying so, whatever `hours` asks.
- IEM's elevation of the stations is wrong at some (LSMP 491 m for 447, LSGG 416 for 430), so
  `stations` takes elevation and position from OurAirports (https://ourairports.com/data/, public
  domain; the published values in ft, times 0.3048, 2026-11-23). It is the elevation of the
  aerodrome, the zero of the bases in METAR.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

UTC = dt.timezone.utc
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
STATIONS_CSV = Path(__file__).parent / "stations.csv"
CIVIL = ("LSGG", "LSZB", "LSZG", "LSZH", "LSZR")  # report at all hours, so a gap near an edge shows
MAX_DAYS = 400
SESSION = requests.Session()


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# --- the parser -----------------------------------------------------------------------------------

WIND = re.compile(r"^(\d{3}|VRB|///)P?(\d{2,3}|//)(?:G(?:P?)(\d{2,3}))?(KT|MPS)$")
WIND_RANGE = re.compile(r"^(\d{3})V(\d{3})$")
VISIBILITY = re.compile(r"^(\d{4}|////)(NDV|[NSEW]{1,2})?$")
RVR = re.compile(r"^R\d{2}[LCR]?/[MP]?\d{4}(V[MP]?\d{4})?[UDN]?$")
RUNWAY_STATE = re.compile(r"^R(\d{2}[LCR]?)?/([\d/]{6}|CLRD.*|SNOCLO|/+)$")  # known and not stored
CLOUD = re.compile(r"^(FEW|SCT|BKN|OVC|///)(\d{3}|///)(CB|TCU|///)?$")
VERTICAL = re.compile(r"^VV(\d{3}|///)$")
TEMPERATURE = re.compile(r"^(M?\d{2}|//)/(M?\d{2}|//)$")
QNH = re.compile(r"^Q(\d{4}|////)$")
WEATHER = re.compile(r"^(?:[-+]|VC)?(?:MI|BC|PR|DR|BL|SH|TS|FZ|DZ|RA|SN|SG|PL|GR|GS|BR|FG|FU|VA|DU|SA|HZ|SQ|FC|IC|UP|PO|DS|SS)+$")
RECENT = re.compile(r"^RE(?:[A-Z]{2})+$")
STOP = ("TEMPO", "BECMG", "NOSIG", "RMK")
NO_CLOUD = {"NSC": "nsc", "NCD": "ncd", "SKC": "skc", "CLR": "skc"}


def _temp(s: str) -> int | None:
    if s.startswith("/"):
        return None
    return -int(s[1:]) if s.startswith("M") else int(s)


def parse_metar(text: str) -> dict:
    """The columns of one METAR. What is not recognised is left to the column `metar`; the count of
    such words is in `unknown` (not stored)."""
    out: dict = {"auto": False, "corrected": False, "wind_variable": False, "unknown": 0,
                 "cloud_report": "none", "weather": None, "weather_recent": None, "rvr": None, "trend": None}
    for k in ("wind_direction", "wind_speed", "wind_gust", "wind_from", "wind_to", "visibility", "visibility_min",
              "visibility_min_direction", "vertical_visibility", "temperature", "dew_point", "qnh"):
        out[k] = None
    for i in (1, 2, 3, 4):
        out[f"cover_{i}"] = out[f"base_{i}"] = out[f"type_{i}"] = None
    words = text.rstrip("= ").split()  # some reports end with "=" (NOSIG=)
    weather, recent, rvr, layers, seen_cloud, trend = [], [], [], [], set(), None
    seen_vis = 0
    for n, w in enumerate(words):
        if w in ("TEMPO", "BECMG", "NOSIG"):
            end = words.index("RMK") if "RMK" in words else len(words)
            trend = " ".join(words[n:end]) if n < end else None
            break
        if w == "RMK":
            break
        if n == 0 and w in ("METAR", "SPECI"):
            continue
        if w == "COR":
            out["corrected"] = True
        elif w == "AUTO":
            out["auto"] = True
        elif w == "CAVOK":
            seen_cloud.add("cavok")
            out["visibility"] = 10000
        elif (m := WIND.match(w)) and out["wind_speed"] is None:
            d, sp, gust, unit = m.groups()
            k = 1 if unit == "KT" else 1.943844  # m/s to knots; Swiss METARs use KT only
            if sp != "//":
                out["wind_speed"] = round(int(sp) * k)
            if gust:
                out["wind_gust"] = round(int(gust) * k)
            out["wind_variable"] = d == "VRB"
            if d not in ("VRB", "///") and out["wind_speed"] != 0:  # 00000KT is calm: no direction
                out["wind_direction"] = int(d)
        elif m := WIND_RANGE.match(w):
            out["wind_from"], out["wind_to"] = int(m[1]), int(m[2])
        elif RVR.match(w):
            rvr.append(w)
        elif RUNWAY_STATE.match(w):
            pass
        elif m := CLOUD.match(w):
            cover, base, kind = m.groups()
            layers.append((cover, None if base == "///" else int(base) * 100, None if kind in (None, "///") else kind))
        elif m := VERTICAL.match(w):
            seen_cloud.add("vv")
            out["vertical_visibility"] = None if m[1] == "///" else int(m[1]) * 100
        elif (m := VISIBILITY.match(w)) and n > 1:
            if m[1] == "////":
                pass
            elif seen_vis == 0:
                out["visibility"] = 10000 if m[1] == "9999" else int(m[1])
            else:  # the second one is the lowest, with its direction: 3000 1200NE
                out["visibility_min"] = int(m[1])
                out["visibility_min_direction"] = m[2] if m[2] not in (None, "NDV") else None
            seen_vis += 1
        elif w in NO_CLOUD:
            seen_cloud.add(NO_CLOUD[w])
        elif m := TEMPERATURE.match(w):
            out["temperature"], out["dew_point"] = _temp(m[1]), _temp(m[2])
        elif m := QNH.match(w):
            out["qnh"] = None if m[1] == "////" else int(m[1])
        elif RECENT.match(w):
            recent.append(w[2:])
        elif w == "//" or WEATHER.match(w):  # "//": an automatic station that could not tell the weather
            weather.append(w)
        elif not (n == 0 and re.fullmatch(r"[A-Z]{4}", w)) and not re.fullmatch(r"\d{6}Z", w) \
                and not (n <= 1 and re.fullmatch(r"[A-Z]{4}", w)) and not w.startswith("WS") and w not in ("ALL", "RWY"):
            out["unknown"] += 1
    if len(layers) > 4:
        out["unknown"] += len(layers) - 4
    for i, (cover, base, kind) in enumerate(layers[:4], 1):
        out[f"cover_{i}"], out[f"base_{i}"], out[f"type_{i}"] = cover, base, kind
    ceil = [b for c, b, _ in layers if c in ("BKN", "OVC") and b is not None]
    out["ceiling"] = min(ceil) if ceil else None
    bases = [b for c, b, _ in layers if b is not None]
    out["lowest_base"] = min(bases) if bases else None
    if "cavok" in seen_cloud:
        out["cloud_report"] = "cavok"
    elif layers and any(c != "///" or t for c, _, t in layers):
        out["cloud_report"] = "layers"
    elif layers:
        out["cloud_report"] = "unknown"
    elif seen_cloud:
        out["cloud_report"] = next(k for k in ("vv", "nsc", "ncd", "skc") if k in seen_cloud)
    out["weather"] = " ".join(weather) or None
    out["weather_recent"] = " ".join(recent) or None
    out["rvr"] = " ".join(rvr) or None
    out["trend"] = trend
    return out


# --- the source ------------------------------------------------------------------------------------

# Column --> pandas type. Nullable types: an empty column keeps its type (no object column of None).
COLUMNS = {
    "station": "string", "valid_at": "datetime64[us, UTC]", "auto": "boolean", "corrected": "boolean", "cloud_report": "string",
    "ceiling": "Int64", "lowest_base": "Int64", "vertical_visibility": "Int64",
    **{f"{name}_{i}": t for i in (1, 2, 3, 4) for name, t in (("cover", "string"), ("base", "Int64"), ("type", "string"))},
    "visibility": "Int64", "visibility_min": "Int64", "visibility_min_direction": "string",
    "rvr": "string", "weather": "string", "weather_recent": "string",
    "temperature": "Int64", "dew_point": "Int64", "qnh": "Int64",
    "wind_direction": "Int64", "wind_variable": "boolean", "wind_from": "Int64", "wind_to": "Int64",
    "wind_speed": "Int64", "wind_gust": "Int64", "trend": "string", "metar": "string",
}


def stations() -> list[dict]:
    with STATIONS_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


_last_request = 0.0


def _get(start: dt.datetime, end: dt.datetime, codes: list[str]) -> str:
    """The text of one request. IEM asks for at most one request a second; 503 means busy."""
    global _last_request
    params = [("station", c) for c in codes] + [("data", "metar"), ("tz", "UTC"), ("format", "onlycomma"),
              ("missing", "empty"), ("sts", f"{start:%Y-%m-%dT%H:%M:%SZ}"), ("ets", f"{end:%Y-%m-%dT%H:%M:%SZ}")]
    for attempt in range(5):
        time.sleep(max(0.0, 1.5 - (time.time() - _last_request)))
        _last_request = time.time()
        try:
            r = SESSION.get(URL, params=params, timeout=(30, 600))
            if r.status_code in (429, 500, 502, 503, 504):
                raise IOError(f"HTTP {r.status_code}")
            if r.status_code != 200:
                raise RuntimeError(f"IEM answered HTTP {r.status_code}: {r.text[:200]}")
            if r.text.splitlines()[0] != "station,valid,metar":
                raise RuntimeError(f"IEM: unexpected answer {r.text[:200]!r}")
            return r.text
        except (requests.RequestException, IOError) as e:
            if attempt == 4:
                raise
            say(f"IEM: {type(e).__name__} ({e}), trying again")
            time.sleep(15 * (attempt + 1))
    raise AssertionError("unreachable")


def _rows(text: str, codes: list[str]) -> list[tuple[str, dt.datetime, str]]:
    """(station, valid, metar), the rows rebuilt by IEM dropped, a correction replacing its report."""
    if not text.endswith("\n"):
        raise RuntimeError("IEM: the answer does not end with a line: cut")
    out: dict = {}
    dropped = 0
    for rec in csv.reader(io.StringIO(text)):
        if rec[:2] == ["station", "valid"]:
            continue
        if len(rec) != 3 or rec[0] not in codes:
            raise RuntimeError(f"IEM: unexpected row {rec}")
        if "IEM_" in rec[2]:  # rebuilt from GHCNh or DS3505, not a METAR
            dropped += 1
            continue
        key = (rec[0], dt.datetime.strptime(rec[1], "%Y-%m-%d %H:%M").replace(tzinfo=UTC))
        metar = " ".join(rec[2].split())
        if key not in out or re.match(r"^(METAR |SPECI )?COR ", metar):
            out[key] = metar
    if dropped:
        say(f"{dropped} rows rebuilt by IEM dropped")
    return [(s, v, m) for (s, v), m in out.items()]


def _check(rows: list[tuple], start: dt.datetime, end: dt.datetime) -> None:
    """The civil stations report all day, so each must have rows near both ends of a window."""
    end = min(end, dt.datetime.now(UTC) - dt.timedelta(hours=1))
    if end - start < dt.timedelta(days=1):
        return
    day = dt.timedelta(days=1)
    for code in CIVIL:
        times = [v for s, v, _ in rows if s == code]
        if not times:
            raise RuntimeError(f"no report of {code} in [{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M})")
        if min(times) > start + day or max(times) < end - day:
            raise RuntimeError(f"{code}: reports only from {min(times):%Y-%m-%d %H:%M} to {max(times):%Y-%m-%d %H:%M} in a "
                               f"window [{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): the answer is cut")


def _parse_window(start: dt.datetime, end: dt.datetime) -> tuple[list[dict], int]:
    codes = [s["station"] for s in stations()]
    rows, lo = [], start
    while lo < end:
        hi = min(end, lo + dt.timedelta(days=MAX_DAYS))
        rows += _rows(_get(lo, hi, codes), codes)
        lo = hi
    rows = [r for r in rows if start <= r[1] < end]
    _check(rows, start, end)
    parsed, unknown = [], 0
    for station, valid, metar in rows:
        p = parse_metar(metar)
        unknown += p.pop("unknown")
        parsed.append({"station": station, "valid_at": valid, "metar": metar, **p})
    return parsed, unknown


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    parsed, unknown = _parse_window(start, end)
    reports = pd.DataFrame(parsed, columns=list(COLUMNS)).astype(COLUMNS)
    st = pd.DataFrame(stations())
    st["lat"], st["lon"] = st["lat"].astype("float64"), st["lon"].astype("float64")
    st["elevation"] = st["elevation_m"].astype("float64")
    say(f"[{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}): {len(parsed)} reports, {unknown} words not recognised "
        f"({time.time() - t0:.0f} s)")
    return {"reports": reports, "stations": st[["station", "name", "lat", "lon", "elevation"]]}
