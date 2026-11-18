# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.31", "pandas>=2.2"]
# ///
"""The 79 points of the openmeteo_* datasets, and the grid cell that each model of those datasets
uses at each point. Two tables without a time column (D22), returned whole at every fetch:
`stations` (from stations.csv, the points that the other datasets ask for) and `cells` (one
request per model, at every point).

Draft by Claude, 2026-11-16 (WP5.10).

- stations.csv: the 43 Plateau and 36 Alpine SwissMetNet stations whose measured GHI the swissgrid
  project used (SGP `data/nwp/stations.csv`, from `data/pv_imbalance/smn_ghi_hourly.parquet`),
  with the position and height that SGP took from MeteoSwiss. The same file is in every
  openmeteo_* dataset and in ecmwf_ifs_ens; a test checks that the copies are equal.
- An answer's latitude and longitude are "the center of the weather grid-cell which was used"
  (Open-Meteo's docs, quoted by SGP), of the FIRST model of the request; so `cells` asks one
  model per request. Its `elevation` is the height of the requested point in a terrain model of
  90 m, used to adapt temperature (SGP: within 2.4 m of the station height on the Plateau, 27 m
  in the Alps on average); it is not the height of the cell.
- SGP, for ecmwf_ifs025: 54 cells for the 79 points (29 for the Plateau, 25 for the Alps), all on
  the 0.25-degree grid; 45 points share their cell with another one, and points that share a
  cell have equal series. The cells come from the default `cell_selection=land`, which "finds a
  suitable grid-cell on land with similar elevation" (docs), so a cell is not always the
  nearest one.
- Fetched on 2026-11-16: ecmwf_ifs025 uses the same cell as in SGP's answers at all 79 points
  (54 cells, 45 points share one); `elevation` equals SGP's at 77 of 79 points and is the same
  for every model at a point. era5 is also on a 0.25-degree grid but picks other cells (56).
  Distinct cells: icon_eu 78, gfs_global 75 (SGP's counts of distinct series), icon_d2,
  meteoswiss_icon_ch1 and ch2 79.
- Cost: one call per point and model, 14 models: 1,106 calls per fetch. Hence every P7D.
  The client is the same as in openmeteo_previous_runs.
"""
from __future__ import annotations

import csv
import datetime as dt
import fcntl
import math
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

UTC = dt.timezone.utc
PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"
SINGLE = "https://single-runs-api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
# model --> (API, the parameter that names it, the dataset that uses it)
MODELS = {
    "ecmwf_ifs025": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "ecmwf_aifs025_single": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "icon_eu": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "icon_d2": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "gfs_global": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "meteofrance_arpege_europe": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "gem_global": (PREVIOUS, "models", "openmeteo_previous_runs"),
    "meteoswiss_icon_ch2": (PREVIOUS, "models", "openmeteo_previous_runs, openmeteo_single_runs"),
    "ecmwf_ifs": (SINGLE, "models", "openmeteo_single_runs"),
    "meteoswiss_icon_ch1": (SINGLE, "models", "openmeteo_single_runs"),
    "era5": (ARCHIVE, "models", "openmeteo_era5"),
    "era5_land": (ARCHIVE, "models", "openmeteo_era5"),
    "cams_global": (AIR, "domains", "openmeteo_cams"),
    "cams_europe": (AIR, "domains", "openmeteo_cams"),
}
MAX_REQUEST = 200.0  # calls per request at most: points are split into chunks below it
TIMEOUT = (15, 300)  # connect, read (s)


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def stations() -> list[dict]:
    with (Path(__file__).parent / "stations.csv").open() as f:
        return [{"station": r["station"], "lat": r["lat"], "lon": r["lon"]} for r in csv.DictReader(f)]


# --- the Open-Meteo client: the same in every openmeteo_* dataset --------------------------------

_SESSION = requests.Session()
# The budget of every openmeteo_* fetch on this machine together (the free tier counts per IP:
# 600 calls per minute, 5,000 per hour, 10,000 per day, 300,000 per month). The calls are written
# down in one file (ledger()), which each fetch reads before each request.
MINUTE_CAP, HOUR_CAP, DAY_CAP = 500.0, 4000.0, 9000.0  # 9,000 x 31 days stays under the month's 300,000
BACKFILL_DAY_CAP = 7500.0  # a window in the past stops here: the scheduled fetches find 1,500 calls left
BACKFILL_BEFORE = dt.timedelta(days=14)  # a window that ends this long before now is a backfill
MAX_WAIT = 20 * 60.0  # s; a longer wait fails the fetch (BudgetSpent): it may last 30 min on the server
_day_cap = DAY_CAP


class BudgetSpent(RuntimeError):
    """The budget has no room for a request before MAX_WAIT. The message says from when on it has
    ("budget spent until <UTC time>"); deploy/backfill_by_window.py waits until then."""


def for_window(end: dt.datetime) -> None:
    """Call first in fetch(): a window that ends before now - BACKFILL_BEFORE gets BACKFILL_DAY_CAP."""
    global _day_cap
    _day_cap = BACKFILL_DAY_CAP if end < dt.datetime.now(UTC) - BACKFILL_BEFORE else DAY_CAP


def ledger() -> Path:
    """One line per request of every openmeteo_* fetch on this machine: time (s), calls, dataset.
    In $XDG_STATE_HOME/adele (on the server: the fetch unit sets XDG_STATE_HOME), else
    ~/.local/state/adele. Lines older than 24 h are dropped."""
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "adele" / "openmeteo-calls.tsv"


def weight(series: int, days: float, locations: int) -> float:
    """Calls that a request costs: max(1, series / 10) x max(1, days / 14) per location."""
    return locations * max(1.0, series / 10) * max(1.0, days / 14)


def _room_in(spent: list[tuple[float, float]], now: float, w: float, span: float, cap: float) -> float:
    """Seconds from now until the calls of the last `span` seconds leave room for w more under cap."""
    inside = sorted((t, c) for t, c in spent if now - t < span)
    excess = sum(c for _, c in inside) + w - cap
    for t, c in inside:  # the oldest leave the span first, at t + span
        if excess <= 0:
            break
        excess -= c
        if excess <= 0:
            return t + span - now
    return 0.0 if excess <= 0 else math.inf


def _pace(w: float) -> None:
    """Wait until the last minute, hour and 24 h leave room for w calls, then write them down.
    Raises BudgetSpent when the room comes later than MAX_WAIT from the first try."""
    path = ledger()
    path.parent.mkdir(parents=True, exist_ok=True)
    first = time.time()
    while True:
        with path.open("a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)  # released when the file closes
            now = time.time()
            f.seek(0)
            lines = f.read().splitlines()
            spent = [(float(t), float(c)) for t, c, *_ in (ln.split("\t") for ln in lines if ln)]
            spent = [(t, c) for t, c in spent if now - t < 86400]
            day = sum(c for _, c in spent)
            wait = max(_room_in(spent, now, w, 60, MINUTE_CAP), _room_in(spent, now, w, 3600, HOUR_CAP),
                       _room_in(spent, now, w, 86400, _day_cap))
            if wait == 0:
                if len(lines) > len(spent) + 1000:  # drop the lines older than 24 h
                    f.truncate(0)
                    f.write("".join(f"{t:.0f}\t{c:g}\n" for t, c in spent))
                f.write(f"{now:.0f}\t{w:g}\t{Path(__file__).parent.name}\n")
                return
        if wait == math.inf:
            raise RuntimeError(f"a request of {w:g} calls exceeds a cap of the budget")
        if now + wait - first > MAX_WAIT:
            until = dt.datetime.fromtimestamp(now + wait, UTC)
            raise BudgetSpent(f"Open-Meteo budget spent until {until:%Y-%m-%dT%H:%MZ}: {day:,.0f} calls in the "
                              f"last 24 h on this machine (cap {_day_cap:,.0f}), {w:g} more needed")
        time.sleep(min(wait, 60.0))


def get(url: str, params: dict, w: float) -> list[dict]:
    """The answers of one request (one per location, in their order). Raises SourceError on HTTP 400
    (the source refuses the request: an unknown run, model or variable)."""
    for attempt in range(8):
        _pace(w)
        try:
            r = _SESSION.get(url, params=params, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as e:
            say(f"{type(e).__name__}, try again in {30 * (attempt + 1)} s")
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 429:
            reason = _reason(r)
            if "inute" not in reason and "ourly" not in reason:  # daily or monthly: no point in waiting
                raise RuntimeError(f"Open-Meteo refused the request (429): {reason}")
            wait = 65 if "inute" in reason else 600
            say(f"429 {reason!r}: wait {wait} s")
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            say(f"HTTP {r.status_code}, try again in {30 * (attempt + 1)} s")
            time.sleep(30 * (attempt + 1))
            continue
        if r.status_code == 400:
            raise SourceError(_reason(r))
        r.raise_for_status()
        answer = r.json()
        return answer if isinstance(answer, list) else [answer]
    raise RuntimeError(f"no answer from {url} after 8 tries")


class SourceError(Exception):
    pass


def _reason(r: requests.Response) -> str:
    try:
        return str(r.json().get("reason", r.text[:200]))
    except ValueError:
        return r.text[:200]


def chunks(points: list[dict], per_point: float) -> list[list[dict]]:
    n = max(1, int(MAX_REQUEST // per_point))
    return [points[i:i + n] for i in range(0, len(points), n)]


def answers_by_point(answers: list[dict], chunk: list[dict]) -> list[tuple[dict, dict]]:
    """Pair each answer with its point: `location_id` (absent on the first) gives the position."""
    if len(answers) != len(chunk):
        raise RuntimeError(f"{len(answers)} answers for {len(chunk)} points")
    out = []
    for i, a in enumerate(answers):
        pos = a.get("location_id", 0)
        if pos != i:
            raise RuntimeError(f"answer {i} has location_id {pos}")
        if a.get("utc_offset_seconds") != 0:
            raise RuntimeError(f"answer for {chunk[i]['station']} is not in UTC: {a.get('timezone')}")
        out.append((chunk[i], a))
    return out


def series(answer: dict, name: str, unit: str, single_model: bool, model: str) -> list | None:
    """The values of one series: the key with the model suffix, or without it when the request named
    one model. None when the answer lacks it. A unit other than `unit` is an error."""
    h, units = answer["hourly"], answer.get("hourly_units", {})
    for key in ([name] if single_model else []) + [f"{name}_{model}"]:
        if key in h:
            if units.get(key) != unit:
                raise RuntimeError(f"{key}: unit {units.get(key)!r}, expected {unit!r}")
            return h[key]
    return None


def utc_hours(answer: dict) -> pd.DatetimeIndex:
    return pd.to_datetime(pd.Series(answer["hourly"]["time"]), format="%Y-%m-%dT%H:%M").dt.tz_localize(UTC)


# --- this dataset --------------------------------------------------------------------------------


def params(model: str, now: dt.datetime) -> dict:
    """A small request: one variable, one day (or one run) that the model has."""
    url, key, _ = MODELS[model]
    p = {key: model, "timezone": "UTC"}
    if url == SINGLE:
        run = (now - dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return p | {"hourly": "cloud_cover", "run": f"{run:%Y-%m-%dT%H:%M}", "forecast_days": 1}
    day = (now - dt.timedelta(days=10 if url == ARCHIVE else 1)).date().isoformat()  # ERA5 lags 5-6 days
    return p | {"hourly": "dust" if url == AIR else "cloud_cover", "start_date": day, "end_date": day}


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance on the sphere (radius 6,371 km)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    for_window(end)  # the budget: a window in the past is a backfill
    with (Path(__file__).parent / "stations.csv").open() as f:
        listed = pd.DataFrame(list(csv.DictReader(f)))
    listed = listed.astype({"lat": "float64", "lon": "float64", "height": "float64"})
    points, now, rows = stations(), dt.datetime.now(UTC), []
    for model, (url, _, used_by) in MODELS.items():
        for chunk in chunks(points, 1.0):
            answers = get(url, params(model, now) | {"latitude": ",".join(p["lat"] for p in chunk),
                                                     "longitude": ",".join(p["lon"] for p in chunk)}, len(chunk))
            for point, a in answers_by_point(answers, chunk):
                rows.append({"station": point["station"], "model": model, "used_by": used_by,
                             "cell_lat": float(a["latitude"]), "cell_lon": float(a["longitude"]),
                             "elevation": float(a["elevation"]),
                             "cell_distance_km": round(km(float(point["lat"]), float(point["lon"]),
                                                          float(a["latitude"]), float(a["longitude"])), 2)})
        say(f"{model}: {len(points)} points")
    cells = pd.DataFrame(rows)
    key = [cells["model"], cells["cell_lat"].round(5), cells["cell_lon"].round(5)]
    cells["stations_in_cell"] = cells.groupby(key)["station"].transform("size").astype("int64")
    return {"stations": listed[["station", "region", "lat", "lon", "height"]], "cells": cells}
