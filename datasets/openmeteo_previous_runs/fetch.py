# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.31", "pandas>=2.2"]
# ///
"""Fetch Open-Meteo's Previous Runs API at the 79 points of stations.csv: what each weather model
forecast for an hour one day (previous_day1) and two days (previous_day2) before, and its latest
short-range value (day0). Two tables: `hourly` (values over an hour) and `instant` (values at an
instant).

Draft by Claude, 2026-11-16 (WP5.10). The points, models and series are those of the swissgrid
project (SGP, `swissgrid_project/data/nwp/README.md`, tiers t1 to t6, downloaded 2026-10-31 to
2026-11-06); its facts are quoted from there, with "SGP". Measured again on 2026-11-16 at
Payerne, with a few calls ("probe"):

- The answer's latitude and longitude are the centre of the grid cell of the FIRST model of the
  request (probe: 46.75 N, 7.00 E for ecmwf_ifs025 at Payerne); no interpolation between cells.
  The other models choose their own cells, which the answer does not report
  (`openmeteo_stations.cells` asks each model alone). SGP: 54 ecmwf_ifs025 cells serve the 79
  points, and points in one cell have identical ecmwf_ifs025 series.
- Keys of the answer: `<variable>_<lead>_<model>`, e.g. `cloud_cover_previous_day1_icon_eu`; the
  day0 series has no lead suffix. With one model in the request, the model suffix is absent
  (probe, single runs API).
- Radiation (mean of the preceding hour) and snowfall (sum of the preceding hour) are stamped at
  the END of the hour; this file stores the start (delivery_start = stamp - 1 h). SGP proved the
  convention: on clear days the forecast GHI is centred on solar noon within about 1 minute. Cloud
  cover, temperature and snow depth are values at the stamp (valid_at = stamp).
- previous_dayN at valid time t comes from the latest run started at or before t - N x 24 h (SGP,
  verified for ICON-CH2 against single runs: lead 24-29 h for previous_day1 with 6-hourly runs).
  The answer holds future hours too: on 2026-11-16 every series ran to 2026-11-19 23:00 (probe).
  A value of a future hour can still change (a later run qualifies); horizon PT0S keeps them out.
- day0 is a stitched series of each run's first hours (SGP, from the Historical Forecast API's
  docs; unverified for this API). Low, mid and high cloud cover and snow depth exist ONLY as day0:
  their previous_dayN series are null for all 17 models probed by SGP, 2024-01 to 2026-10.
- Where the archives start (SGP, Payerne): previous_dayN of icon_eu, gfs_global, arpege, gem and
  icon_d2 2024-01-19/20; ecmwf_ifs025 cloud 2024-02-05, GHI 2024-03-07; ecmwf_aifs025_single
  2025-02-18; meteoswiss_icon_ch2 2025-07-05. day0 of gfs_global from about 2021-03-23, of
  icon_eu from between 2022-10-05 and 2022-12-05. icon_d2 has previous_day1 only. A series is
  asked for from the FROM date of its model below; rows where every value is null are dropped.
- Holes in the archive: icon_eu previous_day2 misses 95 h from 2026-04-07 12:00 UTC, ecmwf_ifs025
  cloud previous_day2 129 h from 2026-04-17 15:00 UTC, at all 79 points (SGP, QA C1).
- GFS cloud cover has values -1 and 101 (about 0.05 % of its hours; SGP). Kept as served.
- Compared on 2026-11-16 with SGP's raw answers of tiers t1 to t5 (`qa/tools/compare_sgp_openmeteo.py`,
  2026-10-24 to 2026-10-30 22:00 UTC, 79 points): 917,980 values, every one equal except
  temperature_2m, of which 1.3 to 1.9 % per model and lead differ by 0.1 degC. Open-Meteo changed
  them between SGP's downloads (2026-10-31 to 11-03) and this one; a second fetch on the same day
  changed nothing. No value of SGP is missing here.
- Units of the answer: W/m2, %, degC, cm (snowfall), m (snow depth). Snow depth is stored in cm.
  An answer with another unit fails the fetch.
- Cost: the free tier allows 600 calls per minute, 5,000 per hour, 10,000 per day per IP. A request
  counts max(1, series / 10) x max(1, days / 14) calls per location; that each model x variable x
  lead counts as one series, and that each location counts, is the conservative reading of
  https://open-meteo.com/en/pricing (not stated there). All series: 7.8 calls per point and
  14 days, so 616 calls per fetch of up to 14 days for the 79 points. The openmeteo_* fetches of
  one machine write their calls in one file and keep together under 500 calls per minute, 4,000
  per hour and 9,000 per 24 h (7,500 for a window that ended more than 14 days ago, a backfill),
  see the client below. A 429 of Open-Meteo waits for the minute or the hour, and fails the fetch
  on the day or the month.
- Several points in one request (comma-separated lists) return a list of answers in the order of
  the points, each with `location_id` from the second on (probe).
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

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
UTC = dt.timezone.utc
HOURLY = ("shortwave_radiation", "diffuse_radiation", "snowfall")  # preceding hour, stamped at its end
INSTANT = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "temperature_2m", "snow_depth")
UNITS = {"shortwave_radiation": "W/m²", "diffuse_radiation": "W/m²", "snowfall": "cm", "cloud_cover": "%",
         "cloud_cover_low": "%", "cloud_cover_mid": "%", "cloud_cover_high": "%", "temperature_2m": "°C",
         "snow_depth": "m"}
LEADS = ("day0", "previous_day1", "previous_day2")

# The series of each model (SGP tiers t1 to t6). previous: variables at its previous leads, from the
# date `previous_from`; day0: variables of the latest run, from `day0_from`. The dates are a little
# before the first value that SGP found, so that no value is missed; earlier rows are null and dropped.
PREV_FULL = ["shortwave_radiation", "diffuse_radiation", "cloud_cover", "temperature_2m", "snowfall"]
DAY0_FULL = ["shortwave_radiation", "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
             "snow_depth"]
MODELS = {
    "ecmwf_ifs025": dict(previous=PREV_FULL, leads=("previous_day1", "previous_day2"), previous_from="2024-02-01",
                         day0=DAY0_FULL, day0_from="2024-02-01"),
    "icon_eu": dict(previous=PREV_FULL, leads=("previous_day1", "previous_day2"), previous_from="2024-01-18",
                    day0=DAY0_FULL, day0_from="2022-10-01"),
    "gfs_global": dict(previous=PREV_FULL, leads=("previous_day1", "previous_day2"), previous_from="2024-01-18",
                       day0=DAY0_FULL, day0_from="2021-03-22"),
    "meteofrance_arpege_europe": dict(previous=["shortwave_radiation", "cloud_cover"],
                                      leads=("previous_day1", "previous_day2"), previous_from="2024-01-18",
                                      day0=["cloud_cover_low"], day0_from="2024-01-18"),
    "gem_global": dict(previous=["shortwave_radiation", "cloud_cover"], leads=("previous_day1", "previous_day2"),
                       previous_from="2024-01-18", day0=["cloud_cover_low"], day0_from="2024-01-18"),
    "ecmwf_aifs025_single": dict(previous=["shortwave_radiation", "cloud_cover"],
                                 leads=("previous_day1", "previous_day2"), previous_from="2025-02-17",
                                 day0=["cloud_cover_low"], day0_from="2025-02-17"),
    "meteoswiss_icon_ch2": dict(previous=["shortwave_radiation", "cloud_cover"],
                                leads=("previous_day1", "previous_day2"), previous_from="2025-07-01",
                                day0=["cloud_cover_low"], day0_from="2025-07-01"),
    "icon_d2": dict(previous=PREV_FULL, leads=("previous_day1",), previous_from="2024-01-18",
                    day0=["shortwave_radiation", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
                          "snow_depth"], day0_from="2024-01-18"),
}
FIRST = dt.datetime(2021, 3, 22, tzinfo=UTC)  # the earliest series (day0 of gfs_global)
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

def requests_for(start: dt.datetime, end: dt.datetime) -> list[tuple[list[str], list[str]]]:
    """(models, hourly parameters) of each request for [start, end): the series whose model has
    values before `end`, models with the same parameters in one request (it asks for every
    parameter of every model)."""
    groups: dict[tuple, list[str]] = {}
    for model, m in MODELS.items():
        params = []
        if end > _date(m["previous_from"]):
            params += [f"{v}_{lead}" for lead in m["leads"] for v in m["previous"]]
        if end > _date(m["day0_from"]):
            params += list(m["day0"])
        if params:
            groups.setdefault(tuple(params), []).append(model)
    return [(models, list(params)) for params, models in groups.items()]


def _date(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


def parse(answer: dict, station: str, models: list[str], params: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One answer --> rows of `hourly` and of `instant` (long in model and lead, wide in variables)."""
    t = utc_hours(answer)
    hourly, instant = [], []
    for model in models:
        for lead in LEADS:
            suffix = "" if lead == "day0" else f"_{lead}"
            cols = {}
            for var in HOURLY + INSTANT:
                p = var + suffix
                if p not in params:
                    continue
                values = series(answer, p, UNITS[var], len(models) == 1, model)
                if values is None:
                    raise RuntimeError(f"{station}: the answer lacks {p} of {model}")
                cols[var] = pd.to_numeric(pd.Series(values, dtype="object"), errors="raise").astype("float64")
            for names, out, time_col, shift in ((HOURLY, hourly, "delivery_start", dt.timedelta(hours=1)),
                                                (INSTANT, instant, "valid_at", dt.timedelta(0))):
                have = [v for v in names if v in cols]
                if not have:
                    continue
                df = pd.DataFrame({v: cols[v] for v in have})
                keep = df.notna().any(axis=1)
                if not keep.any():
                    continue
                df = df[keep].reindex(columns=list(names)).reset_index(drop=True)
                df.insert(0, time_col, (t - shift)[keep].reset_index(drop=True))
                df.insert(0, "lead", lead)
                df.insert(0, "model", model)
                df.insert(0, "station", station)
                out.append(df)
    h = pd.concat(hourly, ignore_index=True) if hourly else empty("hourly")
    i = pd.concat(instant, ignore_index=True) if instant else empty("instant")
    i["snow_depth"] = i["snow_depth"] * 100  # m --> cm
    return h, i


def empty(table: str) -> pd.DataFrame:
    time_col, names = ("delivery_start", HOURLY) if table == "hourly" else ("valid_at", INSTANT)
    df = pd.DataFrame({"station": pd.Series(dtype="object"), "model": pd.Series(dtype="object"),
                       "lead": pd.Series(dtype="object"), time_col: pd.Series(dtype="datetime64[ns, UTC]")})
    for v in names:
        df[v] = pd.Series(dtype="float64")
    return df


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    for_window(end)  # the budget: a window in the past is a backfill
    if end <= FIRST:
        return {"hourly": empty("hourly"), "instant": empty("instant")}
    start = max(start, FIRST)
    first_day = start.astimezone(UTC).date()
    # the hour that ends at `end` is stamped at `end` (radiation): ask for that date too
    last_day = (end.astimezone(UTC) - dt.timedelta(microseconds=1) + dt.timedelta(hours=1)).date()
    days = (last_day - first_day).days + 1
    points = stations()
    hourly, instant = [], []
    for models, params in requests_for(start, end):
        per_point = weight(len(models) * len(params), days, 1)
        for chunk in chunks(points, per_point):
            answers = get(URL, {
                "latitude": ",".join(p["lat"] for p in chunk), "longitude": ",".join(p["lon"] for p in chunk),
                "hourly": ",".join(params), "models": ",".join(models), "timezone": "UTC",
                "start_date": first_day.isoformat(), "end_date": last_day.isoformat(),
            }, per_point * len(chunk))
            for point, answer in answers_by_point(answers, chunk):
                h, i = parse(answer, point["station"], models, params)
                hourly.append(h)
                instant.append(i)
            say(f"{','.join(models)}: {len(chunk)} points, {first_day} to {last_day}")
    return {"hourly": pd.concat(hourly, ignore_index=True) if hourly else empty("hourly"),
            "instant": pd.concat(instant, ignore_index=True) if instant else empty("instant")}
