# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.31", "pandas>=2.2"]
# ///
"""Fetch whole model runs from Open-Meteo's Single Runs API at the 79 points of stations.csv: the
00 UTC run of ECMWF IFS (9 km), MeteoSwiss ICON-CH1 and ICON-CH2, every hour of its first 72 h.
Two tables: `hourly` (values over an hour) and `instant` (values at an instant). The fetch window
[start, end) applies to init_time (adele.window): one run per day.

Draft by Claude, 2026-11-16 (WP5.10). Measured at Payerne with a few calls on 2026-11-16
("probe"), and before by the swissgrid project (SGP, `data/nwp/README.md` and
`semester_project/sem project/03_WN3/ECMWF_BASELINE.md`, 2026-10-26 and 2026-10-31):

- One request asks one run (`run=YYYY-MM-DDTHH:MM`) and `forecast_days=3`: 72 hours from the init
  time. Several models in one request: keys `<variable>_<model>`; one model: no suffix (probe).
- Archived runs: ECMWF IFS HRES 9 km from 2024-03-14, every other model from 2026-04-02 (docs,
  read 2026-11-16). A request that names a model without that run fails as a whole: HTTP 400 "The
  requested model run is not available. Model: meteoswiss_icon_ch2, run: 2026-03-01T00:00Z"
  (probe). IFS runs at 00, 06, 12, 18 UTC (12 UTC of 2024-06-01 and 06 UTC of 2026-11-14 answered);
  this dataset keeps the 00 UTC run, the one that is out before the Swiss day-ahead auction.
- Radiation is the mean of the preceding hour, stamped at its END: null at the init time, 71
  values for IFS and ICON-CH2 from init + 1 h to init + 71 h (probe). Stored with delivery_start =
  stamp - 1 h and lead_h = stamp - init (1 to 71). ICON-CH1 runs to 33 h: 33 radiation values,
  34 cloud values (lead 0 to 33), the rest null (probe). Cloud cover and temperature are values
  at the stamp (valid_at, lead 0 to 71).
- Low, mid and high cloud cover exist at every lead here, unlike the Previous Runs API (SGP).
- The answer's position is the centre of the cell of the FIRST model (probe at Payerne: IFS
  46.784 N, 6.979 E; ICON-CH2 alone 46.819 N, 6.930 E; ICON-CH1 alone 46.809 N, 6.946 E).
  `openmeteo_stations.cells` asks each model alone.
- A run appears 4 to 6 h after its init time for global models and 1 to 3 h for regional ones
  (docs). With revisions: none, a stored run is never fetched again, so a run is returned only
  whole: every model that should have it, every point. A run whose model is missing or whose
  radiation has fewer values than expected (`EXPECTED`) is skipped while it is younger than
  `COMPLETE_AFTER`; after that the models that have it are kept and the others are reported on
  stderr (a hole that stays).
- Cost: 7 variables x up to 3 models = 2.1 calls per point and run (the conservative reading of
  the pricing, see openmeteo_previous_runs/fetch.py): 166 calls per run for the 79 points, 79
  before 2026-04-02. The client is the same as in openmeteo_previous_runs.
- Compared on 2026-11-16 with SGP's ECMWF IFS 00 UTC runs at 10 stations
  (`qa/tools/compare_sgp_openmeteo.py`, runs of 2026-10-20 to 2026-10-25): 30,120 values, all equal
  (temperature to 1e-6, SGP's float32), none missing on either side.
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

URL = "https://single-runs-api.open-meteo.com/v1/forecast"
UTC = dt.timezone.utc
HOURLY = ("shortwave_radiation", "diffuse_radiation")  # preceding hour mean, stamped at its end
INSTANT = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "temperature_2m")
UNITS = {"shortwave_radiation": "W/m²", "diffuse_radiation": "W/m²", "cloud_cover": "%", "cloud_cover_low": "%",
         "cloud_cover_mid": "%", "cloud_cover_high": "%", "temperature_2m": "°C"}
MODELS = {  # model --> first archived run (docs)
    "ecmwf_ifs": dt.datetime(2024, 3, 14, tzinfo=UTC),
    "meteoswiss_icon_ch1": dt.datetime(2026, 4, 2, tzinfo=UTC),
    "meteoswiss_icon_ch2": dt.datetime(2026, 4, 2, tzinfo=UTC),
}
EXPECTED = {"ecmwf_ifs": 71, "meteoswiss_icon_ch1": 33, "meteoswiss_icon_ch2": 71}  # radiation values per run
RUN_HOUR = 0  # the 00 UTC run of each day
FORECAST_DAYS = 3
COMPLETE_AFTER = dt.timedelta(hours=18)  # a younger run that is not whole is left for a later fetch
FIRST = min(MODELS.values())
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
MAX_WAIT = 20 * 60.0  # s; a longer wait fails the fetch (BudgetSpent): it may last 30 min on steacher1
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
    In $XDG_STATE_HOME/adele (steacher1: the fetch unit sets XDG_STATE_HOME), else
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


def runs(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    """The init times of the kept runs in [start, end)."""
    day = max(start, FIRST).astimezone(UTC).replace(hour=RUN_HOUR, minute=0, second=0, microsecond=0)
    out = []
    while day < end:
        if day >= start and day >= FIRST:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def parse(answer: dict, station: str, models: list[str], init: dt.datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    t = utc_hours(answer)
    lead = ((t - pd.Timestamp(init)) / pd.Timedelta(hours=1)).round().astype("int64")
    hourly, instant = [], []
    for model in models:
        cols = {}
        for var in HOURLY + INSTANT:
            values = series(answer, var, UNITS[var], len(models) == 1, model)
            if values is None:
                raise RuntimeError(f"{station}: the answer lacks {var} of {model}")
            cols[var] = pd.to_numeric(pd.Series(values, dtype="object")).astype("float64")
        for names, out, time_col, shift in ((HOURLY, hourly, "delivery_start", dt.timedelta(hours=1)),
                                            (INSTANT, instant, "valid_at", dt.timedelta(0))):
            df = pd.DataFrame({v: cols[v] for v in names})
            keep = df.notna().any(axis=1)
            df = df[keep].reset_index(drop=True)
            df.insert(0, "lead_h", lead[keep].reset_index(drop=True))
            df.insert(0, time_col, (t - shift)[keep].reset_index(drop=True))
            df.insert(0, "model", model)
            df.insert(0, "station", station)
            df.insert(0, "init_time", pd.Timestamp(init))
            out.append(df)
    return pd.concat(hourly, ignore_index=True), pd.concat(instant, ignore_index=True)


def empty(table: str) -> pd.DataFrame:
    time_col, names = ("delivery_start", HOURLY) if table == "hourly" else ("valid_at", INSTANT)
    df = pd.DataFrame({"init_time": pd.Series(dtype="datetime64[ns, UTC]"), "station": pd.Series(dtype="object"),
                       "model": pd.Series(dtype="object"), time_col: pd.Series(dtype="datetime64[ns, UTC]"),
                       "lead_h": pd.Series(dtype="int64")})
    for v in names:
        df[v] = pd.Series(dtype="float64")
    return df


def _ask(init: dt.datetime, models: list[str], chunk: list[dict]) -> list[dict]:
    return get(URL, {
        "latitude": ",".join(p["lat"] for p in chunk), "longitude": ",".join(p["lon"] for p in chunk),
        "hourly": ",".join(HOURLY + INSTANT), "models": ",".join(models), "timezone": "UTC",
        "run": f"{init:%Y-%m-%dT%H:%M}", "forecast_days": FORECAST_DAYS,
    }, weight(len(models) * len(HOURLY + INSTANT), FORECAST_DAYS, len(chunk)))


def _available(init: dt.datetime, models: list[str], probe: dict) -> list[str]:
    """The models that have the run, asked one by one at one point, and that look whole."""
    out = []
    for m in models:
        try:
            a = _ask(init, [m], [probe])[0]
        except SourceError as e:
            say(f"run {init:%Y-%m-%d %H}Z, {m}: {e}")
            continue
        n = sum(v is not None for v in a["hourly"]["shortwave_radiation"])
        if n < EXPECTED[m]:
            say(f"run {init:%Y-%m-%d %H}Z, {m}: {n} radiation values, expected {EXPECTED[m]}")
            continue
        out.append(m)
    return out


def fetch_run(init: dt.datetime, points: list[dict], now: dt.datetime) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Every point of one run, or None when the run is not whole yet."""
    models = [m for m, first in MODELS.items() if init >= first]
    have = _available(init, models, points[0])
    if have != models:
        if now - init < COMPLETE_AFTER:
            say(f"run {init:%Y-%m-%d %H}Z: not whole yet ({','.join(have) or 'no model'} of {','.join(models)}), "
                "skipped")
            return None
        if not have:
            raise RuntimeError(f"run {init:%Y-%m-%d %H}Z: no model has it, {now - init} after its init time")
        say(f"run {init:%Y-%m-%d %H}Z: kept without {','.join(sorted(set(models) - set(have)))} "
            f"({now - init} after its init time): a hole")
    per_point = weight(len(have) * len(HOURLY + INSTANT), FORECAST_DAYS, 1)
    hourly, instant = [], []
    for chunk in chunks(points, per_point):
        for point, answer in answers_by_point(_ask(init, have, chunk), chunk):
            h, i = parse(answer, point["station"], have, init)
            hourly.append(h)
            instant.append(i)
    say(f"run {init:%Y-%m-%d %H}Z: {','.join(have)}, {len(points)} points")
    return pd.concat(hourly, ignore_index=True), pd.concat(instant, ignore_index=True)


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    for_window(end)  # the budget: a window in the past is a backfill
    points, now = stations(), dt.datetime.now(UTC)
    hourly, instant = [empty("hourly")], [empty("instant")]
    for init in runs(start, end):
        got = fetch_run(init, points, now)
        if got is not None:
            hourly.append(got[0])
            instant.append(got[1])
    return {"hourly": pd.concat(hourly, ignore_index=True), "instant": pd.concat(instant, ignore_index=True)}
