# WeatherNext 3 as adele's second dataset: design notes

Status: draft by Claude, 2026-11-13, for discussion. Sources: the swissgrid project
(`semester_project/sem project/03_WN3/README.md` and `WN3.md`, `pull_wn3_box.py`, the extract
`wn3_stats_ch_20260903_00.parquet`). Nothing here is decided.

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

## Traps to write down (for the analyst)

- Jan-Jun 2026 is in sample. Candidate normalization: a column `checkpoint` (evaluation,
  production).
- p10 ... p90 are quantiles per cell and per hour, across members. The p10 series is not one
  member's trajectory, and the daily sum of p10 is not the p10 of daily sums.
- There is no lead 0. The first lead is 1 h.
- `ssrd` at night is not exactly 0: about 0.4 W/m² per cell at lead 1 on 2026-09-03 01:00 UTC
  (measured on one extract). A clear-sky index divides by almost 0 at dawn and dusk.
- A grid cell is 0.1° (about 8 x 11 km in Switzerland), not a station point.

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
