# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.31", "pandas>=2.2"]
# ///
"""Fetch the ERA5 and ERA5-Land reanalyses from Open-Meteo's Historical Weather API at the 79
points of stations.csv, from 2015. Two tables: `hourly` (radiation, mean over an hour) and
`instant` (cloud layers, boundary layer height, temperature, snow depth).

Draft by Claude, 2026-11-16 (WP5.10). Measured at Payerne on 2026-11-16 ("probe"), and before by
the swissgrid project (SGP, `code/datasets/fetch_openmeteo.py`, 2026-10-31; its download never ran:
it waits for ever because one request of 555 calls exceeds its cap of 550 per minute):

- `models=era5` (0.25 degree) has cloud cover (total, low, mid, high), boundary layer height,
  radiation and temperature, and no snow depth; `models=era5_land` (0.1 degree) has temperature
  and snow depth, and no cloud, boundary layer or radiation (probe, all null; SGP the same on
  2015-01-01). So two requests: 8 variables of era5, 2 of era5_land. One model per request: the
  keys have no model suffix.
- The last value lags about 5.5 days: on 2026-11-16 at 09:40 UTC both models ended at 2026-11-10
  23:00 (probe); the later hours are null and dropped.
- Radiation is the mean of the preceding hour, stamped at its end (Open-Meteo's docs; the same
  convention as the forecast APIs, proven for those by SGP): delivery_start = stamp - 1 h. The
  other variables are values at the stamp.
- Units: %, m (boundary layer height, snow depth), W/m2, degC. Snow depth is stored in cm.
- Position: era5 answers 46.75 N, 7.00 E at Payerne, the centre of its 0.25-degree cell (probe).
- Cost: two requests per point, each 1 call per 14 days: 158 calls per fetch of up to 14 days
  for the 79 points; 2015-01-01 to 2026-11 is about 49,000 calls (5 days of the free tier).
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

URL = "https://archive-api.open-meteo.com/v1/archive"
UTC = dt.timezone.utc
FIRST = dt.datetime(2015, 1, 1, tzinfo=UTC)
# model --> {variable of the answer: column of adele}
REQUESTS = {
    "era5": {"shortwave_radiation": "shortwave_radiation", "diffuse_radiation": "diffuse_radiation",
             "cloud_cover": "cloud_cover", "cloud_cover_low": "cloud_cover_low", "cloud_cover_mid": "cloud_cover_mid",
             "cloud_cover_high": "cloud_cover_high", "boundary_layer_height": "boundary_layer_height",
             "temperature_2m": "temperature_2m"},
    "era5_land": {"temperature_2m": "temperature_2m_land", "snow_depth": "snow_depth"},
}
UNITS = {"shortwave_radiation": "W/m²", "diffuse_radiation": "W/m²", "cloud_cover": "%", "cloud_cover_low": "%",
         "cloud_cover_mid": "%", "cloud_cover_high": "%", "boundary_layer_height": "m", "temperature_2m": "°C",
         "snow_depth": "m"}
HOURLY = ("shortwave_radiation", "diffuse_radiation")  # preceding hour mean, stamped at its end
INSTANT = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "boundary_layer_height",
           "temperature_2m", "temperature_2m_land", "snow_depth")
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


def parse(answer: dict, station: str, model: str) -> pd.DataFrame:
    """One answer --> one column per variable, indexed by the stamp (the end of the hour for radiation)."""
    cols = {}
    for var, col in REQUESTS[model].items():
        values = series(answer, var, UNITS[var], True, model)
        if values is None:
            raise RuntimeError(f"{station}: the {model} answer lacks {var}")
        cols[col] = pd.to_numeric(pd.Series(values, dtype="object")).astype("float64")
    df = pd.DataFrame(cols)
    df.insert(0, "stamp", utc_hours(answer))
    df.insert(0, "station", station)
    return df


def tables(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """The answers of era5 and era5_land, joined on station and stamp --> hourly and instant."""
    both = frames["era5"].merge(frames["era5_land"], on=["station", "stamp"], how="outer")
    hourly = both[["station", "stamp", *HOURLY]].rename(columns={"stamp": "delivery_start"})
    hourly["delivery_start"] = hourly["delivery_start"] - pd.Timedelta(hours=1)
    instant = both[["station", "stamp", *INSTANT]].rename(columns={"stamp": "valid_at"})
    instant["snow_depth"] = instant["snow_depth"] * 100  # m --> cm
    return {"hourly": hourly[hourly[list(HOURLY)].notna().any(axis=1)].reset_index(drop=True),
            "instant": instant[instant[list(INSTANT)].notna().any(axis=1)].reset_index(drop=True)}


def empty() -> dict[str, pd.DataFrame]:
    out = {}
    for table, time_col, names in (("hourly", "delivery_start", HOURLY), ("instant", "valid_at", INSTANT)):
        df = pd.DataFrame({"station": pd.Series(dtype="object"), time_col: pd.Series(dtype="datetime64[ns, UTC]")})
        for v in names:
            df[v] = pd.Series(dtype="float64")
        out[table] = df
    return out


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    for_window(end)  # the budget: a window in the past is a backfill
    if end <= FIRST:
        return empty()
    start = max(start, FIRST)
    first_day = start.astimezone(UTC).date()
    last_day = (end.astimezone(UTC) - dt.timedelta(microseconds=1) + dt.timedelta(hours=1)).date()
    if last_day > dt.datetime.now(UTC).date():  # the archive refuses dates in the future
        last_day = dt.datetime.now(UTC).date()
    days = (last_day - first_day).days + 1
    points = stations()
    frames: dict[str, list[pd.DataFrame]] = {m: [] for m in REQUESTS}
    for model, variables in REQUESTS.items():
        per_point = weight(len(variables), days, 1)
        for chunk in chunks(points, per_point):
            answers = get(URL, {
                "latitude": ",".join(p["lat"] for p in chunk), "longitude": ",".join(p["lon"] for p in chunk),
                "hourly": ",".join(variables), "models": model, "timezone": "UTC",
                "start_date": first_day.isoformat(), "end_date": last_day.isoformat(),
            }, per_point * len(chunk))
            for point, answer in answers_by_point(answers, chunk):
                frames[model].append(parse(answer, point["station"], model))
        say(f"{model}: {len(points)} points, {first_day} to {last_day}")
    return tables({m: pd.concat(f, ignore_index=True) for m, f in frames.items()})
