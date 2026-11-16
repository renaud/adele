# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.31", "pandas>=2.2"]
# ///
"""Fetch Saharan dust and aerosol optical depth of the CAMS forecasts from Open-Meteo's Air Quality
API at the 79 points of stations.csv. One table, `instant`: one row per point, domain and hour.

Draft by Claude, 2026-11-16 (WP5.10). Measured at Payerne on 2026-11-16 ("probe"); the docs were
read the same day (https://open-meteo.com/en/docs/air-quality-api); SGP's notes of 2026-10-31
(`code/datasets/fetch_openmeteo.py`):

- Two domains, asked one at a time with `domains=`: cams_global (CAMS global atmospheric
  composition forecasts, 0.4 degree, 3-hourly, from August 2022, updated every 12 h) and
  cams_europe (CAMS European air quality forecast, 0.1 degree, hourly, from October 2023, updated
  every 24 h). "The European and global domain are not coupled and may show different
  forecasts" (docs). Past values come from the archive of forecasts, not from a reanalysis: the
  docs list a European reanalysis from 2013, but dust of cams_europe was null on 2015-01-01 (SGP).
- dust (μg/m3, "Saharan dust particles close to surface level (10 meter above ground)") and
  aerosol_optical_depth (no unit, "at 550 nm of the entire atmosphere") are "Instant" (docs):
  values at the stamp, stored with valid_at = stamp. aerosol_optical_depth is null in
  cams_europe (probe 2023-10-01, SGP 2024-03-01): asked of cams_global only.
- "All output is normalised to hourly resolution" (pricing page): the 3-hourly values of
  cams_global are filled in between by Open-Meteo.
- First values: cams_global null on 2022-07-30 to 2022-08-02 at Payerne (probe), numeric on
  2022-08-05 (SGP); cams_europe dust numeric on 2023-10-01 (probe). Rows where every value is
  null are dropped.
- The answer runs into the future (forecasts, 2026-11-18 asked on 2026-11-16: answered): horizon
  PT0S keeps only past hours, whose values come from the latest run that covers them.
- Position: 46.80 N, 6.90 E at Payerne for both domains (probe).
- Cost: one call per point, domain and 14 days: 158 calls per fetch for the 79 points; from
  2022-08 about 15,000 calls. The client is the same as in openmeteo_previous_runs.
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

URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
UTC = dt.timezone.utc
DOMAINS = {  # domain --> (variables, first day asked)
    "cams_global": (("dust", "aerosol_optical_depth"), dt.datetime(2022, 8, 1, tzinfo=UTC)),
    "cams_europe": (("dust",), dt.datetime(2023, 10, 1, tzinfo=UTC)),
}
UNITS = {"dust": "μg/m³", "aerosol_optical_depth": ""}
VALUES = ("dust", "aerosol_optical_depth")
FIRST = min(first for _, first in DOMAINS.values())
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


def parse(answer: dict, station: str, domain: str) -> pd.DataFrame:
    variables, _ = DOMAINS[domain]
    df = pd.DataFrame({"station": station, "domain": domain, "valid_at": utc_hours(answer)})
    for v in VALUES:
        if v in variables:
            values = series(answer, v, UNITS[v], True, domain)
            if values is None:
                raise RuntimeError(f"{station}: the {domain} answer lacks {v}")
            df[v] = pd.to_numeric(pd.Series(values, dtype="object")).astype("float64")
        else:
            df[v] = float("nan")
    return df[df[list(VALUES)].notna().any(axis=1)].reset_index(drop=True)


def empty() -> pd.DataFrame:
    return pd.DataFrame({"station": pd.Series(dtype="object"), "domain": pd.Series(dtype="object"),
                         "valid_at": pd.Series(dtype="datetime64[ns, UTC]"),
                         "dust": pd.Series(dtype="float64"), "aerosol_optical_depth": pd.Series(dtype="float64")})


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    for_window(end)  # the budget: a window in the past is a backfill
    points = stations()
    out = [empty()]
    for domain, (variables, first) in DOMAINS.items():
        if end <= first:
            continue
        first_day = max(start, first).astimezone(UTC).date()
        last_day = (end.astimezone(UTC) - dt.timedelta(microseconds=1)).date()
        days = (last_day - first_day).days + 1
        per_point = weight(len(variables), days, 1)
        for chunk in chunks(points, per_point):
            answers = get(URL, {
                "latitude": ",".join(p["lat"] for p in chunk), "longitude": ",".join(p["lon"] for p in chunk),
                "hourly": ",".join(variables), "domains": domain, "timezone": "UTC",
                "start_date": first_day.isoformat(), "end_date": last_day.isoformat(),
            }, per_point * len(chunk))
            for point, answer in answers_by_point(answers, chunk):
                out.append(parse(answer, point["station"], domain))
        say(f"{domain}: {len(points)} points, {first_day} to {last_day}")
    return {"instant": pd.concat(out, ignore_index=True)}
