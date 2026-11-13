# /// script
# requires-python = ">=3.12"
# dependencies = ["zarr>=3.0.8", "gcsfs>=2025.3", "numpy>=2", "pandas>=2.2"]
# ///
"""Fetch WeatherNext 3 (Google DeepMind) ensemble statistics of surface solar radiation over
Switzerland, one run (init time) at a time, from Google's public Zarr stores on GCS.

The server runs this file with `uv run --script` (PEP 723): its dependencies are not the
server's. The fetch window [start, end) applies to init_time (adele.window).

Measured 2026-11-13 (docs/weathernext3.md):

- 2026 stores: one per run, `2026_to_present/<YYYYMMDD>_<HH>hr_01_preds/`, 24 runs per day,
  with a `success` marker next to `predictions.zarr` once the run is written. A run was readable
  about 7 h after its init time (one observation in the swissgrid project).
- Arrays `<variable>_<statistic>`, dims (lead_time, lat_0p1, lon_0p1), one chunk per lead =
  one global field of 1801 x 3600 float32 (23.1 MB compressed). A box costs whole globes:
  bytes = statistics x leads x 23 MB = 4.4 GB per run here.
- lead_time holds hours 1..360 (runs at 00/06/12/18 UTC) or 1..48 (other runs). No lead 0.
- surface_solar_radiation_downwards_1hr: J/m2 accumulated over the hour that ends at
  init + lead. Stored here as the mean power of that hour, W/m2 = J/m2 / 3600, with
  delivery_start = init + lead - 1 h (the start of that hour).
- Reads are billed to Google (requester pays is off). Never pass a billing project. If the
  Application Default Credentials carry a quota project, GCS bills reads to it: on the Mac its
  billing account is disabled, and every chunk read fails with 403 "The billing account for the
  owning project is disabled". So the quota project is dropped here.
- Bandwidth: 120-150 MB/s from steacher1; 5.8 MB/s for one chunk and 10.5 MB/s for 24 chunks in
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

ROOT = "weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/2026_to_present"
VARIABLE = "surface_solar_radiation_downwards_1hr"
STATISTICS = ("mean", "p10", "p50", "p90")  # column ssrd_<statistic>
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
    t = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if t < start:
        t += dt.timedelta(hours=1)
    out = []
    while t < end:
        out.append(t)
        t += dt.timedelta(hours=1)
    return out


def _read_run(fs, creds, init: dt.datetime) -> pd.DataFrame:
    import zarr

    root = f"{ROOT}/{init:%Y%m%d_%H}hr_01_preds/predictions.zarr"
    g = zarr.open_group(store=f"gs://{root}", mode="r", storage_options={"token": creds})
    names = [f"{VARIABLE}_{s}" for s in STATISTICS]
    arrays = {n: g[n] for n in names}
    for n, a in arrays.items():
        dims = tuple(getattr(a.metadata, "dimension_names", None) or ())
        if dims != ("lead_time", "lat_0p1", "lon_0p1"):
            raise RuntimeError(f"{root}/{n}: dims {dims}, expected (lead_time, lat_0p1, lon_0p1)")
        if a.attrs.get("units") != "J m**-2":
            raise RuntimeError(f"{root}/{n}: units {a.attrs.get('units')!r}, expected 'J m**-2'")
    days = float(np.asarray(g["init_time"][...]))
    stored_init = dt.datetime.fromisoformat(g["init_time"].attrs["units"].split("since", 1)[1].strip()).replace(tzinfo=UTC)
    stored_init += dt.timedelta(days=days)
    if stored_init != init:
        raise RuntimeError(f"{root}: init_time is {stored_init}, expected {init}")
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
    sel = (li, slice(ai[0], ai[-1] + 1), slice(oi[0], oi[-1] + 1))

    def read(n):
        return n, np.asarray(arrays[n].oindex[sel], dtype=np.float64)

    t0 = time.time()
    with ThreadPoolExecutor(len(names)) as pool:
        data = dict(pool.map(read, names))
    L, A, O = data[names[0]].shape
    lead_h = np.repeat(leads[li].astype(np.int64), A * O)
    init_ts = pd.Timestamp(init)
    frame = pd.DataFrame({
        "init_time": init_ts,
        "delivery_start": init_ts + pd.to_timedelta(lead_h - 1, unit="h"),
        "lead_h": lead_h,
        "lat": np.round(np.tile(np.repeat(lat[sel[1]], O), L), 2),
        "lon": np.round(np.tile(lon[sel[2]], L * A), 2),
        **{f"ssrd_{s}": data[f"{VARIABLE}_{s}"].ravel() / 3600.0 for s in STATISTICS},
    })
    nan = float(np.mean([np.isnan(v).mean() for v in data.values()]))
    say(f"run {init:%Y-%m-%d %H}Z: {len(names) * L} chunks, {frame.shape[0]} rows, "
        f"{time.time() - t0:.0f} s{f', {nan:.1%} NaN' if nan else ''}")
    return frame


def fetch(start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    if start < dt.datetime(2026, 1, 1, tzinfo=UTC):
        raise NotImplementedError("runs before 2026 sit in other stores (2024/, 2025/: 8 runs per day); "
                                  "not read yet (docs/weathernext3.md)")
    fs, creds = _filesystem()
    now = dt.datetime.now(UTC)
    frames = []
    for init in _inits(start, end):
        store = f"{ROOT}/{init:%Y%m%d_%H}hr_01_preds"
        if not fs.exists(f"{store}/success"):
            if now - init > LATE_AFTER:
                raise RuntimeError(f"run {init:%Y-%m-%d %H}Z has no success marker {LATE_AFTER} after its init time")
            say(f"run {init:%Y-%m-%d %H}Z: not written yet, skipped")
            continue
        frames.append(_read_run(fs, creds, init))
    if not frames:
        return pd.DataFrame({"init_time": pd.Series(dtype="datetime64[ns, UTC]"),
                             "delivery_start": pd.Series(dtype="datetime64[ns, UTC]"),
                             "lead_h": pd.Series(dtype="int64"), "lat": pd.Series(dtype="float64"),
                             "lon": pd.Series(dtype="float64"),
                             **{f"ssrd_{s}": pd.Series(dtype="float64") for s in STATISTICS}})
    return pd.concat(frames, ignore_index=True)
