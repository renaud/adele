# /// script
# requires-python = ">=3.12"
# dependencies = ["zarr>=3.0.8", "gcsfs>=2025.3", "numpy>=2", "pandas>=2.2"]
# ///
"""Fetch WeatherNext 3 (Google DeepMind) ensemble statistics of surface solar radiation and of
cloud cover over Switzerland, one run (init time) at a time, from Google's public Zarr stores on
GCS. Returns two tables: solar_radiation (per forecast hour) and weather (per instant).

The server runs this file with `uv run --script` (PEP 723): its dependencies are not the
server's. The fetch window [start, end) applies to init_time (adele.window); the server asks
only for the parts of a window that it doesn't hold yet (revisions: none).

Measured 2026-11-13 (docs/weathernext3.md):

- 2026 stores: one per run, `2026_to_present/<YYYYMMDD>_<HH>hr_01_preds/`, 24 runs per day,
  with a `success` marker next to `predictions.zarr` once the run is written. A run was readable
  about 7 h after its init time (one observation in the swissgrid project). Arrays
  `<variable>_<statistic>`, dims (lead_time, lat_0p1, lon_0p1). Production checkpoint (trained
  to 2026-06-30): January-June 2026 is in sample.
- 2024 and 2025 stores: one per year and kind, `<year>/6hr_inits.zarr` (00/06/12/18 UTC, leads
  1-360 h) and `<year>/interim_inits.zarr` (03/09/15/21 UTC, leads 1-48 h): 8 runs per day.
  Dims (init_time, lead_time, lat_0p1, lon_0p1); init_time is int64 "hours since <year>-01-01
  00:00" in 6hr_inits but "hours since <year>-01-01 03:00" in interim_inits (same raw values
  0, 6, 12, ...: decode with the units, never by position). Evaluation checkpoint (trained to
  2023-12-31): out of sample. No `success` marker (the stores are complete).
- One chunk per run and lead = one global field of 1801 x 3600 float32 (23.1 MB compressed),
  in every store. A box costs whole globes: bytes = fields x leads x 23 MB (13.2 GB per run here).
- lead_time holds hours 1..360 (runs at 00/06/12/18 UTC) or 1..48 (other runs). No lead 0.
- surface_solar_radiation_downwards_1hr: J/m2 accumulated over the hour that ends at
  init + lead. Stored here as the mean power of that hour, W/m2 = J/m2 / 3600, with
  delivery_start = init + lead - 1 h (the start of that hour).
- total_cloud_cover, low_cloud_cover: units "(0 - 1)", step_type "instant": the value at the
  instant init + lead, stored as is with valid_at = init + lead. Same chunks (23 MB per lead).
  12 fields per run (4 ssrd + 8 cloud) = 13.2 GB read per run.
- Reads are billed to Google (requester pays is off). Never pass a billing project. If the
  Application Default Credentials carry a quota project, GCS bills reads to it: on the Mac its
  billing account is disabled, and every chunk read fails with 403 "The billing account for the
  owning project is disabled". So the quota project is dropped here.
- Bandwidth: 120-150 MB/s from the server; 5.8 MB/s for one chunk and 10.5 MB/s for 24 chunks in
  parallel from the Mac (2026-11-13): 7 min per run.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message=".*quota project.*")

ROOT = "weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr"
FIRST_RUN = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)  # the stores start here
HOURLY_FROM = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)  # 24 runs per day from here, 8 before
VARIABLE = "surface_solar_radiation_downwards_1hr"
CLOUDS = ("total_cloud_cover", "low_cloud_cover")  # instants, fraction 0-1
STATISTICS = ("mean", "p10", "p50", "p90")  # columns ssrd_<statistic>, <cloud>_<statistic>
LEADS = (1, 48)  # first and last lead, hours
BOX = {"lat": (45.5, 48.0), "lon": (5.5, 11.0)}  # Switzerland, 26 x 56 cells at 0.1 deg (pull_wn3_box.py)
LATE_AFTER = dt.timedelta(hours=10)  # a run without `success` this long after its init is a gap, not late
UTC = dt.timezone.utc


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _filesystem():
    import gcsfs
    import google.auth

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
    if getattr(creds, "quota_project_id", None):
        creds = creds.with_quota_project(None)  # reads must not be billed to the user's project
    return gcsfs.GCSFileSystem(token=creds), creds


def _inits(start: dt.datetime, end: dt.datetime) -> list[dt.datetime]:
    """The init times of WN3's runs in [start, end): every hour from 2026, every 3 h before."""
    t = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    out = []
    while t < end:
        if t >= start and (t >= HOURLY_FROM or t.hour % 3 == 0):
            out.append(t)
        t += dt.timedelta(hours=1)
    return out


def _decode(values, units: str) -> list[dt.datetime]:
    """CF time: '<unit> since <base>' --> UTC datetimes."""
    unit, base = units.split(" since ", 1)
    step = {"days": 86400, "hours": 3600, "minutes": 60, "seconds": 1}[unit.strip()]
    base = dt.datetime.fromisoformat(base.strip()).replace(tzinfo=UTC)
    return [base + dt.timedelta(seconds=float(v) * step) for v in np.atleast_1d(values)]


_STORES: dict[str, tuple] = {}  # path --> (group, init times), for the yearly stores


def _store(creds, init: dt.datetime):
    """(path, zarr group, index of the init on the init_time dim, or None for a 2026 store)."""
    import zarr

    if init >= HOURLY_FROM:
        path = f"{ROOT}/2026_to_present/{init:%Y%m%d_%H}hr_01_preds/predictions.zarr"
        g = zarr.open_group(store=f"gs://{path}", mode="r", storage_options={"token": creds})
        stored_init = _decode(np.asarray(g["init_time"][...]), g["init_time"].attrs["units"])[0]
        if stored_init != init:
            raise RuntimeError(f"{path}: init_time is {stored_init}, expected {init}")
        return path, g, None
    path = f"{ROOT}/{init.year}/{'6hr_inits' if init.hour % 6 == 0 else 'interim_inits'}.zarr"
    if path not in _STORES:
        g = zarr.open_group(store=f"gs://{path}", mode="r", storage_options={"token": creds})
        _STORES[path] = (g, _decode(np.asarray(g["init_time"][:]), g["init_time"].attrs["units"]))
    g, inits = _STORES[path]
    if init not in inits:
        raise RuntimeError(f"{path}: no run at {init:%Y-%m-%d %H}Z (store holds {inits[0]} .. {inits[-1]})")
    return path, g, inits.index(init)


def _read_run(fs, creds, init: dt.datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    root, g, k = _store(creds, init)
    units = {f"{VARIABLE}_{s}": "J m**-2" for s in STATISTICS}
    units |= {f"{c}_{s}": "(0 - 1)" for c in CLOUDS for s in STATISTICS}
    names = list(units)
    arrays = {n: g[n] for n in names}
    want = ("lead_time", "lat_0p1", "lon_0p1") if k is None else ("init_time", "lead_time", "lat_0p1", "lon_0p1")
    for n, a in arrays.items():
        dims = tuple(getattr(a.metadata, "dimension_names", None) or ())
        if dims != want:
            raise RuntimeError(f"{root}/{n}: dims {dims}, expected {want}")
        if a.attrs.get("units") != units[n]:
            raise RuntimeError(f"{root}/{n}: units {a.attrs.get('units')!r}, expected {units[n]!r}")
    if g["lead_time"].attrs.get("units") != "hours":
        raise RuntimeError(f"{root}: lead_time units {g['lead_time'].attrs.get('units')!r}, expected hours")
    leads = np.asarray(g["lead_time"][:])
    lat = np.asarray(g["lat_0p1"][:], dtype=float)
    lon = np.asarray(g["lon_0p1"][:], dtype=float)
    li = np.where((leads >= LEADS[0]) & (leads <= LEADS[1]))[0]
    ai = np.where((lat >= BOX["lat"][0] - 1e-6) & (lat <= BOX["lat"][1] + 1e-6))[0]
    oi = np.where((lon >= BOX["lon"][0] - 1e-6) & (lon <= BOX["lon"][1] + 1e-6))[0]
    if len(li) != LEADS[1] - LEADS[0] + 1:
        raise RuntimeError(f"{root}: leads {leads.min()}..{leads.max()}, expected at least {LEADS[0]}..{LEADS[1]}")
    box = (li, slice(ai[0], ai[-1] + 1), slice(oi[0], oi[-1] + 1))
    sel = box if k is None else (k, *box)

    def read(n):
        return n, np.asarray(arrays[n].oindex[sel], dtype=np.float64)

    t0 = time.time()
    with ThreadPoolExecutor(len(names)) as pool:
        data = dict(pool.map(read, names))
    L, A, O = data[names[0]].shape
    lead_h = np.repeat(leads[li].astype(np.int64), A * O)
    init_ts = pd.Timestamp(init)
    common = {
        "lat": np.round(np.tile(np.repeat(lat[box[1]], O), L), 2),
        "lon": np.round(np.tile(lon[box[2]], L * A), 2),
        "checkpoint": "production" if k is None else "evaluation",
    }
    solar = pd.DataFrame({
        "init_time": init_ts,
        "delivery_start": init_ts + pd.to_timedelta(lead_h - 1, unit="h"),
        "lead_h": lead_h, **common,
        **{f"ssrd_{s}": data[f"{VARIABLE}_{s}"].ravel() / 3600.0 for s in STATISTICS},
    })
    weather = pd.DataFrame({
        "init_time": init_ts,
        "valid_at": init_ts + pd.to_timedelta(lead_h, unit="h"),
        "lead_h": lead_h, **common,
        **{f"{c}_{s}": data[f"{c}_{s}"].ravel() for c in CLOUDS for s in STATISTICS},
    })
    nan = float(np.mean([np.isnan(v).mean() for v in data.values()]))
    say(f"run {init:%Y-%m-%d %H}Z: {len(names) * L} chunks, {solar.shape[0]} + {weather.shape[0]} rows, "
        f"{time.time() - t0:.0f} s{f', {nan:.1%} NaN' if nan else ''}")
    return solar, weather


def _empty() -> dict[str, pd.DataFrame]:
    t = "datetime64[ns, UTC]"
    common = {"lead_h": pd.Series(dtype="int64"), "lat": pd.Series(dtype="float64"),
              "lon": pd.Series(dtype="float64"), "checkpoint": pd.Series(dtype="string")}
    return {
        "solar_radiation": pd.DataFrame({"init_time": pd.Series(dtype=t), "delivery_start": pd.Series(dtype=t), **common,
                                         **{f"ssrd_{s}": pd.Series(dtype="float64") for s in STATISTICS}}),
        "weather": pd.DataFrame({"init_time": pd.Series(dtype=t), "valid_at": pd.Series(dtype=t), **common,
                                 **{f"{c}_{s}": pd.Series(dtype="float64") for c in CLOUDS for s in STATISTICS}}),
    }


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    if start < FIRST_RUN:
        raise ValueError(f"WN3 has no runs before {FIRST_RUN:%Y-%m-%d} (window starts {start})")
    inits = _inits(start, end)
    if not inits:  # e.g. the gap between two stored hourly runs
        return _empty()
    fs, creds = _filesystem()
    now = dt.datetime.now(UTC)
    solar, weather = [], []
    for init in inits:
        if init >= HOURLY_FROM:
            marker = f"{ROOT}/2026_to_present/{init:%Y%m%d_%H}hr_01_preds/success"
            if not fs.exists(marker):
                if now - init > LATE_AFTER:
                    raise RuntimeError(f"run {init:%Y-%m-%d %H}Z has no success marker {LATE_AFTER} after its init time")
                say(f"run {init:%Y-%m-%d %H}Z: not written yet, skipped")
                continue
        s, w = _read_run(fs, creds, init)
        solar.append(s)
        weather.append(w)
    if not solar:
        return _empty()
    return {"solar_radiation": pd.concat(solar, ignore_index=True), "weather": pd.concat(weather, ignore_index=True)}
