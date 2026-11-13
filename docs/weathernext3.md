# WeatherNext 3 as adele's second dataset: design notes

Status: draft by Claude, 2026-11-13, for discussion. Sources: the swissgrid project
(`semester_project/sem project/03_WN3/README.md` and `WN3.md`, `pull_wn3_box.py`, the extract
`wn3_stats_ch_20260903_00.parquet`), and the sample dataset `datasets/weathernext3/` built the same
day. Renaud's answers (2026-11-13): CH only, all 24 runs per day, a few days for now, more on
steacher1 (the adele Linux server). Nothing else is decided.

## Sample dataset (2026-11-13)

`datasets/weathernext3/`, table `weathernext3.solar_radiation`, fetched on the Mac through the
server (`adele-server backfill`). It holds 6 runs (init 2026-11-12 00-05 UTC), leads 1-48, 4
statistics: 419,328 rows (69,888 per run = 48 leads x 1,456 cells), 5.8 MB of Parquet (14 bytes
per row). It took 31 min from the Mac (about 5 min per run, 4.4 GB read per run). Not all 24 runs
of a day: from the Mac, a day takes about 2 h, so the few-days backfill waits for steacher1.

What the sample shows: the key is unique, p10 <= p50 <= p90 in every row, no value is missing.
Daylight is 07-15 UTC; the box mean peaks at 335 W/m2 at 11 UTC on 13 Nov. At night the box mean
is 0.1-0.2 W/m2, not 0. The forecast of 13 Nov 11-12 UTC moved by 7 W/m2 across the 6 runs (334.6
at lead 36, 327.5 at lead 33).

Defaults chosen by Claude, to confirm (Renaud answered none of these):

- Dataset `weathernext3`, table `solar_radiation`: later tables hold other variable groups
  (instant variables in their own table if 14b, below).
- Only ssrd (surface solar radiation downwards, accumulated over the hour: it fits the interval
  convention). Statistics mean, p10, p50, p90 as columns `ssrd_<statistic>`, in W/m2 (the
  source's J/m2 per hour / 3600). delivery_start = valid time - 1 h; resolution PT1H for the
  whole dataset (`adele.resolution`).
- Columns init_time, delivery_start, lead_h, lat, lon. `lead_h` is the source's lead (hours from
  init to the END of the forecast hour, 1 for the first hour); it is redundant with
  delivery_start - init_time + 1 h, and is there against that off-by-one. Key (init_time,
  delivery_start, lat, lon). lat and lon rounded to 0.01 (the store's float32 gives 47.29999924).
- The Swiss box of `pull_wn3_box.py` (lat 45.5-48.0, lon 5.5-11.0: 26 x 56 = 1,456 cells).
  Leads 1-48 for every run, also for the 00/06/12/18 UTC runs that go to 360 h.
- `adele.window: init_time` (question 7 below): the fetch window, the [start, end) filter and the
  month partitions use init_time, so a run is read once and stored whole in one file.
- Refresh every PT1H with lookback PT12H. fetch.py skips a run whose `success` marker isn't
  there yet, and fails if a run has no marker 10 h after its init time (a gap, not a late run).
  Cost: each refresh reads the published runs of the last 12 h again (about 5 runs, 22 GB, 3 min
  on steacher1). A refresh that fetches only the runs not yet stored would read each run once:
  that needs the server to tell fetch() what it holds (not done).
- Runs before 2026 (stores `2024/`, `2025/`, 8 runs per day, another layout) are not read:
  fetch() refuses a window that starts before 2026-01-01.
- Definitions (title, descriptions, licenses, warnings) are TODO(Renaud) in the descriptor.

For a few days on steacher1 (one run = 4.4 GB, about 37 s at 120 MB/s; a window of 6 h keeps
each fetch call far below the time limit of 30 min):

```bash
cd <checkout>/server
uv run adele-server --config <config> backfill weathernext3 --start 2026-11-09 --end 2026-11-13 --step-hours 6
```

Four days are 96 runs: about 420 GB read (about 1 h at 120 MB/s), 6.7 million rows, about 94 MB of
Parquet. A year at 24 runs per day: 612 million rows, about 8.6 GB of Parquet, 38 TB read. One
month partition then holds 52 million rows (730 MB), and every hourly refresh rewrites that file
(the merge rewrites the whole month): this dataset may need partitions by day (not done).

Measured 2026-11-13 (from the Mac):

- `2026_to_present/` holds 7,597 entries, one store per run (`<YYYYMMDD>_<HH>hr_01_preds/`, with
  `predictions.zarr`, `success`, `BQ_picked_grid_0p1deg`, `BQ_picked_grid_0p05deg`). 135 entries
  in a store: 21 variables x 6 statistics, plus coordinates (`lat_0p1`, `lon_0p1`, `lat_0p05`,
  `lon_0p05`, `lead_time`, `init_time`, `datetime`).
- Arrays: dims (lead_time, lat_0p1, lon_0p1), chunks (1, 1801, 3600), no shards, 23.1 MB per
  chunk; units `J m**-2`, `step_type: accumulated`. lat -90..90 ascending, lon 0..359.9.
  lead_time in hours: 1..360 for the run of 00 UTC, 1..48 for the run of 01 UTC. init_time is a
  scalar, "days since <init>".
- At 17:45 UTC on 2026-11-13, the runs of 00-11 UTC that day had their `success` marker: a
  latency of at most 6 h 45 min.
- Bandwidth from the Mac: 5.8 MB/s for one chunk, 9.5 MB/s with 8 and 10.5 MB/s with 24 chunks in
  parallel (not the 0.34 MB/s of an earlier measurement). About 7 min per run of 4 statistics x
  48 leads.
- The Application Default Credentials on the Mac carry a quota project (`gcloud config` project)
  whose billing account is disabled. GCS then refuses every object read with 403 "The billing
  account for the owning project is disabled", while listing works. fetch.py drops the quota
  project from the credentials (reads stay billed to Google, as `pull_wn3_box.py` intends).

## What WN3 is, in adele's terms

- Google DeepMind's ensemble weather forecast. Public: the statistics of its 64 members (mean,
  p10, p25, p50, p75, p90), not the members. 0.1° global grid, 21 surface variables, hourly
  leads 1-360 h (00/06/12/18 UTC inits) or 1-48 h (other inits).
- GCS Zarr, `gs://weathernext3_statistics_spatial/weathernext_3_0_0_statistics/zarr/`. 2024 and
  2025: consolidated stores, 8 inits per day. 2026: one store per init, 24 inits per day.
  Reading needs Google credentials; requester pays is off (never pass a billing project).
- A chunk is one global field for one lead (23 MB). A box or a point costs whole globes:
  bytes = fields x leads x 23 MB. Measured: 120-150 MB/s from steacher1, 0.34 MB/s from the Mac.
- Licence: values that relate to a time 1 h ago or more are CC BY 4.0. Newer values (every
  forecast of the future) fall under Google's experimental terms: internal use allowed,
  required notices, "experimental modelling only".
- Training: 2024-2025 come from the evaluation checkpoint (trained to 2023-12-31, out of
  sample); 2026 from the production checkpoint (trained to 2026-06-30): Jan-Jun 2026 in sample.
- Latency: one run observed, written about 7 h after its init time.

## What doesn't fit the current spec

1. **The fetch window.** SPEC.md: `fetch(start, end)` returns rows whose delivery time falls in
   [start, end). A forecast run covers init + 1 h to init + 48 h (or 360 h), and one run costs
   GBs to read. With a window on delivery time, two consecutive windows read the same run
   twice. Proposal: a dataset declares the column of its window (`adele.window: init_time`).
   Implemented 2026-11-13 for the sample, to confirm: the column also sets the [start, end)
   filter and the month partitions; default delivery_start.
2. **Instant values.** `ssrd` is accumulated over the hour that ends at `valid_time`: it fits
   the convention (delivery_start = valid_time - 1 h, resolution PT1H, stored as W/m² = J/m² /
   3600, so the trap of the unit is removed at ingestion). Cloud cover, wind and temperature
   are values at an instant. The convention "a timestamp marks the start of its interval"
   doesn't cover them.
3. **Two time axes in the key.** Grain: one row per (init_time, delivery_start, lat, lon). The
   knowledge time is the init time plus the latency, not adele's fetch time (a backfill fetches
   two years of runs on one day). Backtests need "the latest run available at time T".
4. **Partitions.** Partition by delivery month (as now) or by init month? Queries ask for "the
   day-ahead run for day D" (by init) and "all forecasts for hour H" (by delivery).
5. **Size.** The Swiss box (1,456 cells), 4 runs per day, leads 1-48: about 280,000 rows per day,
   100 million per year. Reading: 4 variables x 4 statistics x 48 leads x 23 MB = 18 GB per run.
   The prices dataset is 2 MB per year. The "few GB" of TODOs.md no longer holds.
6. **Dependencies.** Reading needs zarr and gcsfs (with google-auth, aiohttp). Since fetches run
   in a child process, each `fetch.py` could declare its own dependencies (PEP 723 inline
   metadata, run by `uv run`), so the server doesn't carry every source's libraries.
   Agreed 2026-11-13 and implemented: a fetch.py with a `# /// script` block runs through
   `uv run --script`; both datasets use it, and the server no longer depends on entsoe-py.

## Traps to write down (for the analyst)

- Jan-Jun 2026 is in sample. Candidate normalization: a column `checkpoint` (evaluation,
  production).
- p10 ... p90 are quantiles per cell and per hour, across members. The p10 series is not one
  member's trajectory, and the daily sum of p10 is not the p10 of daily sums.
- There is no lead 0. The first lead is 1 h.
- `ssrd` at night is not exactly 0: about 0.4 W/m² per cell at lead 1 on 2026-09-03 01:00 UTC
  (measured on one extract). A clear-sky index divides by almost 0 at dawn and dusk.
- A grid cell is 0.1° (about 8 x 11 km in Switzerland), not a station point.
- lead_h against delivery_start: lead 1 is the hour [init, init + 1 h), so delivery_start =
  init_time + lead_h - 1 h. A forecast "for 12:00" means the hour that ends at 12:00 in the
  source, and the hour that starts at 12:00 in adele.
- The 00/06/12/18 UTC runs go to 360 h, the other 20 runs to 48 h. A query over "all runs" at a
  lead above 48 h mixes 4 runs per day with 24 below it (the sample stores leads 1-48 only).
- The knowledge time of a run is its init time plus the publication delay (about 7 h), not the
  init time. A backtest that uses the run of 06 UTC for a decision at 09 UTC uses a forecast that
  wasn't published yet.

## Questions for Renaud (2026-11-13)

1. Area: the Swiss box (1,456 cells), a box over CH + DE + FR (same read cost, more rows), or
   points (stations, or PV-weighted regions)?
2. Variables and statistics: the pass-1 set (ssrd, fdir, tcc, lcc) x (mean, p10, p50, p90), or
   all six statistics? Temperature and 100 m wind too?
3. Runs and leads: 00/06/12/18 UTC with leads 1-48 (day-ahead), all 24 runs of 2026, or leads
   to 360 h?
4. History: from 2026-07-01 (out of sample) only, or also 2024-2025 (out of sample, 8 runs per
   day, another store layout)? Jan-Jun 2026 left out, or kept with a `checkpoint` column?
5. Where the fetch runs: it needs Google credentials and about 120 MB/s. Is the adele Linux
   server steacher1?
6. Has the pass-1 pull of 2026-10-28 (12.6 TB from 2026-07-01, one file per run) run, and where
   are its files? A first `fetch.py` could read them instead of GCS.
7. Fetch window on the init time (`adele.window: init_time`): agreed?
8. Instant variables: (a) delivery_start = valid time and resolution PT0S, (b) a column
   `valid_at` for instants (no delivery_start), or (c) only accumulated variables for now?
9. Dependencies per dataset (PEP 723 metadata in `fetch.py`, run by `uv run` in the child
   process): agreed?
10. Who reads it: team members only? Then the experimental terms allow it, with their notice in
    `describe`.
