# WeatherNext 3 as adele's second dataset: design notes

Status: draft by Claude, 2026-11-13, for discussion. Sources: the swissgrid project
(`semester_project/sem project/03_WN3/README.md` and `WN3.md`, `pull_wn3_box.py`, the extract
`wn3_stats_ch_20260903_00.parquet`), and the sample dataset `datasets/weathernext3/` built the same
day. Renaud's answers (2026-11-13): CH only, all 24 runs per day, earlier runs (2024-2025) too,
a few hours of runs from the Mac for now and the backfill on steacher1 (the adele Linux server),
which is reachable from outside. Defaults below confirmed the same day. Then "just ssrd and
clouds": no temperature, no wind, no direct radiation; cloud cover goes to a second table of
instants (`weather`, time column `valid_at`). Open: the pass-1 pull on steacher1 (question 6), who
reads it (question 10), Renaud's review of the draft definitions in the descriptor.

## Sample dataset (2026-11-13)

`datasets/weathernext3/`, fetched on the Mac through the server (`adele-server backfill`):

| table | runs | rows | Parquet |
|---|---|---|---|
| `solar_radiation` | 9: 2026-11-12 00-05 UTC (production), 2025-11-12 00 and 03 UTC, 2024-11-12 00 UTC (evaluation) | 628,992 (69,888 per run = 48 leads x 1,456 cells) | 8.8 MB (14 bytes per row) |
| `weather` | 2: 2026-11-12 00 UTC, 2025-11-12 00 UTC | 139,776 | 3.6 MB (26 bytes per row) |

Times from the Mac: about 6 min per run for the 4 ssrd fields (4.4 GB, 12.5 MB/s), 14-16 min per
run for all 12 fields (13.3 GB, 14-16 MB/s). The clouds of the two runs were fetched after their
solar radiation: the server fetched both tables again, found the solar rows equal and left their
files untouched. The 7 runs without clouds count as not stored: the next fetch of their window
reads them again (all 12 fields) to add their clouds.

What the sample shows:

- Both tables: the key is unique, p10 <= p50 <= p90 in every row, no value is missing.
- Solar radiation: daylight 06/07-15 UTC; the box mean peaks at 335 W/m2 at 11 UTC on 13 Nov
  2026 (264 on 12 Nov 2024, 408 on 12 Nov 2025). At night the box mean is 0.1-0.2 W/m2, not 0.
  The forecast of 13 Nov 2026 11-12 UTC moved by 7 W/m2 across the 6 runs (334.6 at lead 36,
  327.5 at lead 33). The 03 UTC run of 2025 (interim store) has the same daylight hours as the
  00 UTC run: its init time is decoded right (see the trap on the two time bases).
- Cloud cover: every value in [0, 1]; mean total cloud cover over the box 0.76 (2025-11-12) and
  0.79 (2026-11-12). Around noon, total cloud cover at the end of a radiation hour correlates with
  that hour's radiation at -0.48 (the expected sign).

Defaults chosen by Claude, confirmed by Renaud on 2026-11-13 ("ok, but earlier runs too"):

- Dataset `weathernext3`, two tables: `solar_radiation` (per forecast hour, `delivery_start`) and
  `weather` (per forecast instant, `valid_at`: total and low cloud cover, as mean, p10, p50, p90,
  fraction 0-1 as stored; key init_time, valid_at, lat, lon). Answer to question 8: (b).
- In solar_radiation, only ssrd (surface solar radiation downwards, accumulated over the hour: it
  fits the interval convention). Statistics mean, p10, p50, p90 as columns `ssrd_<statistic>`, in
  W/m2 (the source's J/m2 per hour / 3600). delivery_start = valid time - 1 h; resolution PT1H for the
  whole dataset (`adele.resolution`, from 2024-01-01).
- Columns of solar_radiation: init_time, delivery_start, lead_h, lat, lon, checkpoint. In
  weather, valid_at = init + lead (the instant of the value) and lead_h = valid_at - init_time.
  `lead_h` is the source's lead
  (hours from init to the END of the forecast hour, 1 for the first hour); it is redundant with
  delivery_start - init_time + 1 h, and is there against that off-by-one. Key (init_time,
  delivery_start, lat, lon). lat and lon rounded to 0.01 (the store's float32 gives 47.29999924).
- `checkpoint` (proposed 2026-11-13, to confirm): `evaluation` for the runs of 2024-2025 (model
  trained on data to 2023-12-31), `production` for the runs from 2026 (trained to 2026-06-30, so
  January-June 2026 is in sample). Taken from the store that a run comes from. Labels and
  description: drafts by Claude.
- The Swiss box of `pull_wn3_box.py` (lat 45.5-48.0, lon 5.5-11.0: 26 x 56 = 1,456 cells).
  Leads 1-48 for every run, also for the 00/06/12/18 UTC runs that go to 360 h.
- Runs from 2024-01-01: 8 per day in 2024-2025 (00, 03, ..., 21 UTC), 24 per day from 2026.
  fetch() refuses a window that starts before 2024-01-01 (no store holds earlier runs).
- `adele.window: init_time` (agreed 2026-11-13): the fetch window, the [start, end) filter and
  the partitions use init_time, so a run is read once and stored whole in one file.
- `revisions: none` (agreed 2026-11-13): a run never changes once written. The server fetches
  only the parts of a window that hold no stored run, so each run is read once: a refresh reads
  the runs that appeared since the last one (about 1 per hour), and a backfill that stops can be
  run again and continues where it stopped. A run counts as stored only when both tables hold
  it: runs stored before the clouds were added get their clouds on the next fetch of their window
  (their solar rows come again, are equal, and are skipped).
- Cost with 12 fields (4 ssrd + 8 cloud; 13.3 GB read per run, about 110 s at 120 MB/s): about
  320 GB read per day live (24 runs, about 45 min of transfer per day on steacher1). Backfill:
  2024-2025 78 TB (about 180 h), 2026 about 116 TB per year (about 270 h). From the Mac (12 MB/s):
  about 18 min per run.
- `adele.partition: day` (agreed 2026-11-13): one file per init day (1.7 million rows, about 23
  MB at 24 runs per day). A refresh rewrites only the file of the current day.
- Refresh every PT1H with lookback PT12H. fetch.py skips a 2026 run whose `success` marker isn't
  there yet, and fails if a run has no marker 10 h after its init time (a gap, not a late run).
  A failing status then lasts while the run stays in the lookback (2 h), and clears afterwards:
  a permanent gap shows in the alerts log, not in the status. Decided 2026-11-14 (D21): declare
  `adele.expected_spacing` (PT3H in 2024-2025, PT1H from 2026), and the server reports each
  missing run as a problem until it is filled. Not built yet. With the sparse sample, the first
  period must start at a continuous stretch of runs (e.g. 2026-11-12), or the check fails.
- Definitions (title, descriptions, licenses, warnings, labels): drafted by Claude
  (2026-11-13), accepted by Renaud as they are (2026-11-14). Open: the licence text says
  "Copyright 2024-6 Google LLC" (copied from the swissgrid notes); Renaud checks it against
  Google's terms. The query footer printed all 8 warnings; once D20 is built, only the warnings
  marked `footer: true` go there.

Backfill on steacher1 (one run = 13.3 GB with the clouds, about 110 s at 120 MB/s). A window of
12 h in 2024-2025 (4 runs) or 6 h from 2026 (6 runs, about 11 min) keeps each fetch call below the
time limit of 30 min. A backfill that stops (or fails on a window) continues where it stopped when
it is run again with the same arguments:

```bash
cd <checkout>/server
# a few days first
uv run adele-server --config <config> backfill weathernext3 --start 2026-11-09 --end 2026-11-13 --step-hours 6
# all of 2024-2025 (5,848 runs: 78 TB read, about 180 h; 409 million rows per table)
uv run adele-server --config <config> backfill weathernext3 --start 2024-01-01 --end 2026-01-01 --step-hours 12
# 2026 up to now (24 runs per day: about 116 TB read per year, 270 h; 612 million rows per table per year)
uv run adele-server --config <config> backfill weathernext3 --start 2026-01-01 --step-hours 6
```

Four days of 2026 are 96 runs: about 1.3 TB read (about 3 h at 120 MB/s), 6.7 million rows per
table.

Measured 2026-11-13 (from the Mac):

- `2026_to_present/` holds 7,597 entries, one store per run (`<YYYYMMDD>_<HH>hr_01_preds/`, with
  `predictions.zarr`, `success`, `BQ_picked_grid_0p1deg`, `BQ_picked_grid_0p05deg`). 135 entries
  in a store: 21 variables x 6 statistics, plus coordinates (`lat_0p1`, `lon_0p1`, `lat_0p05`,
  `lon_0p05`, `lead_time`, `init_time`, `datetime`).
- Arrays: dims (lead_time, lat_0p1, lon_0p1), chunks (1, 1801, 3600), no shards, 23.1 MB per
  chunk; units `J m**-2`, `step_type: accumulated`. lat -90..90 ascending, lon 0..359.9.
  lead_time in hours: 1..360 for the run of 00 UTC, 1..48 for the run of 01 UTC. init_time is a
  scalar, "days since <init>".
- `2024/` and `2025/` hold two stores each: `6hr_inits.zarr` (00/06/12/18 UTC, lead_time 1..360)
  and `interim_inits.zarr` (03/09/15/21 UTC, lead_time 1..48). Arrays: dims (init_time,
  lead_time, lat_0p1, lon_0p1), chunks (1, 1, 1801, 3600): the same 23 MB per run and lead as in
  2026, so a run costs the same to read. 1,464 runs per store in 2024, 1,460 in 2025 (4 per day,
  none missing). init_time is int64 "hours since 2025-01-01 00:00" in 6hr_inits and "hours since
  2025-01-01 03:00" in interim_inits: both start at 0 and step by 6, so the raw values of the two
  stores are equal and only the units tell 00 UTC from 03 UTC. Same grid (lat -90..90, lon
  0..359.9), same units (`J m**-2`, accumulated). No `success` marker.
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
  bytes = fields x leads x 23 MB. Measured: 120-150 MB/s from steacher1; from the Mac 0.34 MB/s
  once, 10.5 MB/s on 2026-11-13 (24 chunks in parallel).
- Licence: values that relate to a time 1 h ago or more are CC BY 4.0. Newer values (every
  forecast of the future) fall under Google's experimental terms: internal use allowed,
  required notices, "experimental modelling only".
- Training: 2024-2025 come from the evaluation checkpoint (trained to 2023-12-31, out of
  sample); 2026 from the production checkpoint (trained to 2026-06-30): Jan-Jun 2026 in sample.
  Confirmed by the WeatherNext team by email on 2026-10-29, to Renaud's question: the store has
  one hierarchy (weathernext_3_0_0) and no checkpoint string in the metadata; forecasts "from
  July 1, 2026 onward are out of sample". The warning reads this as init_time from 2026-07-01.
- Latency: one run observed, written about 7 h after its init time.

## What doesn't fit the current spec

1. **The fetch window.** SPEC.md: `fetch(start, end)` returns rows whose delivery time falls in
   [start, end). A forecast run covers init + 1 h to init + 48 h (or 360 h), and one run costs
   GBs to read. With a window on delivery time, two consecutive windows read the same run
   twice. Proposal: a dataset declares the column of its window (`adele.window: init_time`).
   Agreed and implemented 2026-11-13: the column also sets the [start, end) filter and the
   partitions; default delivery_start. With `revisions: none`, the server fetches only the parts
   of a window that hold no stored run.
2. **Instant values.** `ssrd` is accumulated over the hour that ends at `valid_time`: it fits
   the convention (delivery_start = valid_time - 1 h, resolution PT1H, stored as W/m² = J/m² /
   3600, so the trap of the unit is removed at ingestion). Cloud cover, wind and temperature
   are values at an instant. The convention "a timestamp marks the start of its interval"
   doesn't cover them. Decided 2026-11-13 (option b): a table of instants has `valid_at`
   instead of `delivery_start`; resolution doesn't apply to it, coverage uses valid_at, and the
   describe card adds a sentence on instants to its conventions.
3. **Two time axes in the key.** Grain: one row per (init_time, delivery_start, lat, lon). The
   knowledge time is the init time plus the latency, not adele's fetch time (a backfill fetches
   two years of runs on one day). Backtests need "the latest run available at time T".
4. **Partitions.** Partition by delivery month (as now) or by init month? Queries ask for "the
   day-ahead run for day D" (by init) and "all forecasts for hour H" (by delivery). Decided
   2026-11-13: by init day (`adele.window: init_time`, `adele.partition: day`). A query by
   delivery hour reads every file; DuckDB skips row groups by their min/max of delivery_start.
5. **Size.** The Swiss box (1,456 cells), 4 runs per day, leads 1-48: about 280,000 rows per day,
   100 million per year. Reading: 4 variables x 4 statistics x 48 leads x 23 MB = 18 GB per run.
   The prices dataset is 2 MB per year. The "few GB" of TODOs.md no longer holds.
6. **Dependencies.** Reading needs zarr and gcsfs (with google-auth, aiohttp). Since fetches run
   in a child process, each `fetch.py` could declare its own dependencies (PEP 723 inline
   metadata, run by `uv run`), so the server doesn't carry every source's libraries.
   Agreed 2026-11-13 and implemented: a fetch.py with a `# /// script` block runs through
   `uv run --script`; both datasets use it, and the server no longer depends on entsoe-py.

## Traps to write down (for the analyst)

- Jan-Jun 2026 is in sample. Normalized by the column `checkpoint` (evaluation, production),
  to confirm. A skill score over 2024-2026 mixes two models; over January-June 2026 it flatters
  the model.
- Low cloud cover can exceed total cloud cover, which is impossible in the atmosphere: the means
  in 6,022 of the 69,888 rows of the run 2026-11-12 00 UTC (355 in the run 2025-11-12 00 UTC), by
  up to 0.04; the medians too. The model forecasts each variable on its own.
- The mean can lie outside [p10, p90]: in 1,567 of 139,776 rows, by up to 0.02 (cloud cover).
- Cloud cover is stored by the source as float32: a value prints as 0.4119434952735901.
- 8 runs per day before 2026, 24 from 2026. "The latest run before 09:00 UTC" is the run of 08:00
  in 2026 and the run of 06:00 in 2025; a count of runs per day changes on 2026-01-01.
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
   points (stations, or PV-weighted regions)? Answered 2026-11-13: CH only for now.
2. Variables and statistics: the pass-1 set (ssrd, fdir, tcc, lcc) x (mean, p10, p50, p90), or
   all six statistics? Temperature and 100 m wind too? Answered 2026-11-13: ssrd with mean, p10,
   p50, p90 for now (the default); the other variables wait for question 8.
3. Runs and leads: 00/06/12/18 UTC with leads 1-48 (day-ahead), all 24 runs of 2026, or leads
   to 360 h? Answered 2026-11-13: all 24 runs, leads 1-48.
4. History: from 2026-07-01 (out of sample) only, or also 2024-2025 (out of sample, 8 runs per
   day, another store layout)? Jan-Jun 2026 left out, or kept with a `checkpoint` column?
   Answered 2026-11-13: earlier runs too. The `checkpoint` column is proposed, to confirm.
5. Where the fetch runs: it needs Google credentials and about 120 MB/s. Is the adele Linux
   server steacher1? Answered 2026-11-13: yes.
6. Has the pass-1 pull of 2026-10-28 (12.6 TB from 2026-07-01, one file per run) run, and where
   are its files? A first `fetch.py` could read them instead of GCS.
7. Fetch window on the init time (`adele.window: init_time`): agreed? Answered 2026-11-13: yes.
8. Instant variables: (a) delivery_start = valid time and resolution PT0S, (b) a column
   `valid_at` for instants (no delivery_start), or (c) only accumulated variables for now?
   Answered 2026-11-13: (b), with total and low cloud cover only.
9. Dependencies per dataset (PEP 723 metadata in `fetch.py`, run by `uv run` in the child
   process): agreed? Answered 2026-11-13: yes.
10. Who reads it: team members only? Then the experimental terms allow it, with their notice in
    `describe`.
