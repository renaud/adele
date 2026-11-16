# /// script
# requires-python = ">=3.12"
# dependencies = ["icechunk>=1.1", "xarray>=2025.1", "zarr>=3.0.8", "numpy>=2", "pandas>=2.2"]
# ///
"""Fetch the ECMWF IFS ensemble (51 members) at the grid points nearest to the 79 stations of
stations.csv, from dynamical.org's Icechunk store of ECMWF Open Data: the 00 UTC run of each day,
leads 0 to 48 h, all 19 variables of the store. Three tables: `three_hourly` (values over the
3 hours before a lead: mean or maximum), `instant` (values at an instant) and `stations` (the grid
point of each station, no time column). The fetch window [start, end) applies to init_time
(adele.window).

Draft by Claude, 2026-11-16 (WP5.10). Measured on 2026-11-16 on the store (snapshot
6GVA4RVMRYWPTQEPDFN0), and before by the swissgrid project (SGP,
`semester_project/sem project/03_WN3/ECMWF_BASELINE.md` and `pull_ecmwf_ens_point.py`, 2026-10-25).
"Catalog" is dynamical.org's page of the dataset, "validation" its validation report (both read
2026-11-16, https://dynamical.org/catalog/ecmwf-ifs-ens-forecast-15-day-0-25-degree/ and
.../validation/, report of 2026-08-19):

- Store: https://dynamical-ecmwf-ifs-ens.s3.us-west-2.amazonaws.com/ecmwf-ifs-ens-forecast-15-day-0-25-degree/v0.1.0.icechunk
  (from https://stac.dynamical.org/catalog.json), anonymous HTTPS, no key. Dataset version
  0.1.0, "ECMWF IFS ENS forecast data processed by dynamical.org from ECMWF Open Data", CC-BY-4.0.
- 960 runs on 2026-11-16: every day at 00 UTC from 2024-04-01 to 2026-11-16, no gap ("This
  dataset contains the 00 UTC initialization times only", catalog). Leads 0 to 144 h every 3 h,
  then every 6 h to 360 h; members 0 (control) to 50; a 0.25-degree global grid (latitude 90 to
  -90, longitude -180 to 179.75).
- The coordinate `ingested_forecast_length` is empty (NaT) for all 960 runs, so it can't tell how
  far a run is written. A run is used only when temperature has a value at every kept lead,
  member and grid point, and radiation at least one value at each lead after 0 (`whole`): the
  catalog says that radiation and precipitation "are NaN at isolated points where the source's
  running total decreases" (validation), so a test on every radiation value would refuse such
  a run for good. The run of 2026-11-16 was whole at 09:00 UTC.
- One chunk = one run x 85 leads x 51 members x 32 x 32 cells (8 x 8 degrees): Switzerland is in
  one chunk per variable, about 8 MB. All 19 variables of one run at Payerne: 235 s from the Mac
  (run 2026-11-15), 455 s (run 2024-04-01); a fetch of one run at the 79 stations: 2 to 4
  minutes, 133,036 rows, about 1.3 MB stored.
- The 19 variables (probe of the runs 2024-04-01 and 2026-11-15 at Payerne; step types and
  descriptions from the store's attributes and the catalog):
  - step type avg, "Average ... since the previous forecast step": downward short-wave and
    long-wave radiation (W m-2), precipitation rate (kg m-2 s-1, "Units equivalent to mm/s").
    The value at lead L covers [init + L - 3 h, init + L); null at lead 0. Stored with
    delivery_start = init + L - 3 h; precipitation as mm over the 3 hours (rate x 10,800 s).
  - step type max: wind_gust_10m, "Maximum 10 metre wind gust since previous post-processing"
    (m s-1): over the same 3 hours (null at lead 0, like the means).
  - step type instant: temperature and dew point at 2 m, total cloud cover (percent), wind
    components u and v at 10 and 100 m, surface pressure and pressure reduced to sea level (Pa,
    stored in hPa), precipitation type (a code), temperature at 925 and 850 hPa, geopotential
    height at 925, 850 and 500 hPa (m). valid_at = init + lead.
  - Empty before a date at every point ("filled with NaNs", catalog): precipitation type and wind
    gust before 2024-11-13, total cloud cover before 2025-11-21. Confirmed at Payerne (probe and
    the backfill of 2025-11: cloud cover null up to the run of 2025-11-20, complete from 2025-11-21).
  - Precipitation type codes (catalog): 0 none, 1 rain, 2 thunderstorm, 3 freezing rain, 4 mixed
    or ice, 5 snow, 6 wet snow, 7 rain and snow, 8 ice pellets, 9 graupel, 10 hail, 11 drizzle,
    12 freezing drizzle, 13 and 14 hail (under or from 5 mm), 255 missing.
- The nearest grid point: at Payerne (46.81 N, 6.94 E) 46.75 N, 7.00 E (SGP and probe), the same
  as the ecmwf_ifs025 cell of Open-Meteo there.
- A run is committed around 08:15 UTC (SGP, 21 days measured in another project).
- Compared on 2026-11-16 with SGP's extracts at Payerne (`pull_ecmwf_ens_point.py`, runs of
  2026-09-03 and 2026-10-20): 867 rows per run (17 leads x 51 members), radiation, cloud cover
  and temperature all equal.
"""
from __future__ import annotations

import csv
import datetime as dt
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HREF = ("https://dynamical-ecmwf-ifs-ens.s3.us-west-2.amazonaws.com/"
        "ecmwf-ifs-ens-forecast-15-day-0-25-degree/v0.1.0.icechunk")
UTC = dt.timezone.utc
FIRST = dt.datetime(2024, 4, 1, tzinfo=UTC)
LAST_LEAD = 48  # hours
STEP_S = 3 * 3600  # the leads kept are 3 h apart
GHI, T2M = "downward_short_wave_radiation_flux_surface", "temperature_2m"
# source variable: (column, unit in the store, factor to the stored unit)
THREE_HOURLY = {
    GHI: ("shortwave_radiation", "W m-2", 1.0),
    "downward_long_wave_radiation_flux_surface": ("longwave_radiation", "W m-2", 1.0),
    "precipitation_surface": ("precipitation", "kg m-2 s-1", STEP_S),  # mean rate --> mm over the 3 h
    "wind_gust_10m": ("wind_gust_10m", "m s-1", 1.0),
}
INSTANT = {
    T2M: ("temperature_2m", "degree_Celsius", 1.0),
    "dew_point_temperature_2m": ("dew_point_2m", "degree_Celsius", 1.0),
    "total_cloud_cover_atmosphere": ("cloud_cover", "percent", 1.0),
    "wind_u_10m": ("wind_u_10m", "m s-1", 1.0),
    "wind_v_10m": ("wind_v_10m", "m s-1", 1.0),
    "wind_u_100m": ("wind_u_100m", "m s-1", 1.0),
    "wind_v_100m": ("wind_v_100m", "m s-1", 1.0),
    "pressure_surface": ("pressure_surface", "Pa", 0.01),  # hPa
    "pressure_reduced_to_mean_sea_level": ("pressure_msl", "Pa", 0.01),
    "categorical_precipitation_type_surface": ("precipitation_type", "1", 1.0),
    "temperature_925hpa": ("temperature_925hpa", "degree_Celsius", 1.0),
    "temperature_850hpa": ("temperature_850hpa", "degree_Celsius", 1.0),
    "geopotential_height_925hpa": ("geopotential_height_925hpa", "m", 1.0),
    "geopotential_height_850hpa": ("geopotential_height_850hpa", "m", 1.0),
    "geopotential_height_500hpa": ("geopotential_height_500hpa", "m", 1.0),
}
VARS = THREE_HOURLY | INSTANT
KEY = ["init_time", "station", "member"]
LATE_AFTER = dt.timedelta(hours=36)  # a run not whole (to 48 h) this long after its init is a gap, not late


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def stations() -> pd.DataFrame:
    with (Path(__file__).parent / "stations.csv").open() as f:
        df = pd.DataFrame(list(csv.DictReader(f)))
    return df.astype({"lat": "float64", "lon": "float64"})[["station", "lat", "lon"]]


def km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def grid_points(ds, points: pd.DataFrame) -> pd.DataFrame:
    """The nearest grid point of each station: its indices and its centre."""
    lats, lons = ds.latitude.values, ds.longitude.values
    out = points.copy()
    out["i"] = [int(np.abs(lats - la).argmin()) for la in out["lat"]]
    out["j"] = [int(np.abs(lons - lo).argmin()) for lo in out["lon"]]
    out["cell_lat"] = lats[out["i"]].astype("float64")
    out["cell_lon"] = lons[out["j"]].astype("float64")
    out["cell_distance_km"] = [round(km(a, b, c, d), 2) for a, b, c, d in
                               zip(out["lat"], out["lon"], out["cell_lat"], out["cell_lon"])]
    return out


def open_store():
    import icechunk
    import xarray as xr

    repo = icechunk.Repository.open(icechunk.http_storage(HREF))
    return xr.open_zarr(repo.readonly_session("main").store, chunks=None)


def runs(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    day = max(start, FIRST).astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while day < end:
        if day >= start:
            out.append(day)
        day += dt.timedelta(days=1)
    return out


def check_units(ds) -> None:
    for v, (_, unit, _) in VARS.items():
        if str(ds[v].attrs.get("units")) != unit:
            raise RuntimeError(f"{v}: unit {ds[v].attrs.get('units')!r}, expected {unit!r}")


def read_run(ds, init: dt.datetime, pts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """One run at the grid points of the stations, leads 0 to 48 h; None when it is not whole."""
    import xarray as xr

    check_units(ds)
    lead_h = (ds.lead_time.values / np.timedelta64(1, "h")).astype(int)
    leads = np.where(lead_h <= LAST_LEAD)[0]
    cells = pts[["i", "j"]].drop_duplicates().reset_index(drop=True)
    k = int(np.where(ds.init_time.values == np.datetime64(init.replace(tzinfo=None), "ns"))[0][0])
    sub = (ds[list(VARS)].isel(init_time=k, lead_time=leads,
                               latitude=xr.DataArray(cells["i"].to_numpy(), dims="cell"),
                               longitude=xr.DataArray(cells["j"].to_numpy(), dims="cell"))
           .load())
    arrays = {v: sub[v].transpose("lead_time", "ensemble_member", "cell").values.astype("float64") for v in VARS}
    return tables(arrays, lead_h[leads], sub.ensemble_member.values.astype("int64"), cells, pts, init)


def tables(arrays: dict[str, np.ndarray], lh: np.ndarray, members: np.ndarray, cells: pd.DataFrame,
           pts: pd.DataFrame, init: dt.datetime) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """The rows of both tables from one array (lead, member, cell) per variable; None when the run
    is not whole. `cells`: the distinct (i, j) in the order of the arrays' cell axis."""
    if not whole(arrays, lh):
        return None
    cells = cells.copy()
    # long frame: (lead, member, cell) in C order
    grid = pd.MultiIndex.from_product([lh, members, range(len(cells))], names=["lead_h", "member", "cell"])
    vals = {col: arrays[v].ravel() * f if f != 0.01 else np.round(arrays[v].ravel() * f, 2)  # Pa --> hPa
            for v, (col, _, f) in VARS.items()}
    frame = pd.DataFrame(vals, index=grid).reset_index()
    frame["precipitation_type"] = frame["precipitation_type"].round().astype("Int64")
    cells["cell"] = range(len(cells))
    frame = frame.merge(cells, on="cell").merge(pts[["station", "i", "j"]], on=["i", "j"])
    t0 = pd.Timestamp(init)
    frame["init_time"] = t0
    cols3 = [c for c, _, _ in THREE_HOURLY.values()]
    colsi = [c for c, _, _ in INSTANT.values()]
    three = frame[frame[cols3].notna().any(axis=1)].copy()
    three["delivery_start"] = t0 + pd.to_timedelta(three["lead_h"] - 3, unit="h")
    three = three[KEY + ["delivery_start", "lead_h"] + cols3]
    inst = frame[frame[colsi].notna().any(axis=1)].copy()
    inst["valid_at"] = t0 + pd.to_timedelta(inst["lead_h"], unit="h")
    inst = inst[KEY + ["valid_at", "lead_h"] + colsi]
    return three.reset_index(drop=True), inst.reset_index(drop=True)


def whole(arrays: dict[str, np.ndarray], lh: np.ndarray) -> bool:
    """Temperature has a value at every lead, member and point; radiation at least one value at each
    lead after 0 (isolated nulls of radiation are in the source for good)."""
    ghi = arrays[GHI][lh > 0]
    has_ghi = np.isfinite(ghi).reshape(len(ghi), -1).any(axis=1).all()
    return bool(has_ghi and np.isfinite(arrays[T2M]).all())


def empty() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = {"init_time": pd.Series(dtype="datetime64[ns, UTC]"), "station": pd.Series(dtype="object"),
            "member": pd.Series(dtype="int64")}
    three = pd.DataFrame(base | {"delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                                 "lead_h": pd.Series(dtype="int64")}
                         | {c: pd.Series(dtype="float64") for c, _, _ in THREE_HOURLY.values()})
    inst = pd.DataFrame(base | {"valid_at": pd.Series(dtype="datetime64[ns, UTC]"), "lead_h": pd.Series(dtype="int64")}
                        | {c: pd.Series(dtype="Int64" if c == "precipitation_type" else "float64")
                           for c, _, _ in INSTANT.values()})
    return three, inst


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    ds = open_store()
    pts = grid_points(ds, stations())
    table = pts[["station", "cell_lat", "cell_lon", "cell_distance_km"]]
    t3, ti = empty()
    three, inst = [t3], [ti]
    now = dt.datetime.now(UTC)
    stored = set(pd.DatetimeIndex(ds.init_time.values).tz_localize(UTC))
    for init in runs(start, end):
        got = read_run(ds, init, pts) if pd.Timestamp(init) in stored else None
        if got is None:
            if now - init > LATE_AFTER:
                raise RuntimeError(f"run {init:%Y-%m-%d %H}Z is not in the store or not whole to {LAST_LEAD} h, "
                                   f"{now - init} after its init time")
            say(f"run {init:%Y-%m-%d %H}Z: not written to {LAST_LEAD} h yet, skipped")
            continue
        a, b = got
        three.append(a)
        inst.append(b)
        say(f"run {init:%Y-%m-%d %H}Z: {len(a):,} + {len(b):,} rows")
    return {"three_hourly": pd.concat(three, ignore_index=True), "instant": pd.concat(inst, ignore_index=True),
            "stations": table}
