# WP5.10: weather forecasts at stations

Built by Claude on 2026-11-16 in the worktree `wp5.10`, at Renaud's request ("build WP5.10"). The
sub-package is defined in `docs/work-packages/WP5-datasets.md` (five rows). The measurements behind
each choice are in the docstrings of the `fetch.py`; the comparisons with the swissgrid project
(SGP) and the checks in `qa/published_figures_openmeteo.md`.

## What was built

| dataset | tables | fetched on the Mac (rows) | refresh | checks |
|---|---|---|---|---|
| `openmeteo_previous_runs` | `hourly` (radiation, snowfall: `delivery_start`), `instant` (cloud cover by level, temperature, snow depth: `valid_at`); key station, model, lead, time. 8 models, leads day0, previous_day1, previous_day2 | 2026-10-24 to 2026-10-31 (637,056) | daily, lookback 7 days, `overwrite` | none yet (candidates after the backfill) |
| `openmeteo_single_runs` | `hourly`, `instant`; key init_time, station, model, time. The 00 UTC run of ECMWF IFS (from 2024-03-14), ICON-CH1 and ICON-CH2 (from 2026-04-02), 72 h | 14 runs between 2024-03-14 and 2026-11-16 (340,648) | every 3 h, window on `init_time`, `none` | none |
| `openmeteo_era5` | `hourly` (radiation), `instant` (cloud layers, boundary layer, temperature of ERA5 and ERA5-Land, snow depth); key station, time | 2015-01-01 to 01-13, 2026-11-01 to 11-15 (87,137) | daily, lookback 10 days | none |
| `openmeteo_cams` | `instant` (dust, aerosol optical depth); key station, domain, time | 2022-07-28 to 08-09, 2023-09-28 to 10-04, 2026-11-02 to 11-15 (85,320) | daily, lookback 7 days | none |
| `openmeteo_stations` | `stations` (79), `cells` (1,106: the cell of each of 14 models at each station): no time column (D22) | whole | every 7 days | 6 (SGP's figures on the cells) |
| `ecmwf_ifs_ens` | `three_hourly` (radiation, precipitation, gusts over 3 hours), `instant` (15 variables at instants), `stations` (the grid point of each station); key init_time, station, member, time. 51 members, the 00 UTC run, leads 0 to 48 h, all 19 variables of the store | 3 runs with 19 variables (2024-11-13, 2025-11-21, 2026-10-20); before, the 30 runs of 2025-11 with 3 variables | every 3 h, window on `init_time`, `none` | none |

All six descriptors validate; a second fetch of the same window changes nothing (Previous Runs:
0 of 637,056 rows; Single Runs: no run asked again); 17 tests on synthetic answers
(`server/tests/test_openmeteo_fetch.py`), 425 tests in all. Every definition in the descriptors is
a draft by Claude. Not yet on steacher1 (WP1's week runs until 2026-11-22) and not backfilled:
the backfill takes about a month of Open-Meteo's free tier (below).

## What Claude chose

1. **Six datasets, not five.** ERA5 and CAMS (one row in WP5-datasets.md) are two datasets: two
   APIs, other lags and cells, and a failure of one must not mark the other failing (open question 5
   of WP5-datasets.md, for these rows). `variables.csv` is not a table: the unit of each variable
   and what a value covers (an hour or an instant) are in the field descriptions.
2. **One list of 79 points**, SGP's (43 Plateau and 36 Alpine stations with measured GHI), with the
   coordinates that SGP asked for, so the cells are SGP's. A copy of `stations.csv` is in each of
   the six folders, because a dataset folder stands alone (D18); a test checks that the copies are
   equal. The key column is `station`, as in WP5.7. The group column is `region` (`group` is an SQL
   keyword).
3. **Two tables per source, by the time of a value**: `hourly` (`delivery_start`, PT1H: radiation,
   snowfall, stamped at the end of the hour by Open-Meteo, stored at the start) and `instant`
   (`valid_at`: cloud cover, temperature, snow depth), one column per variable, model and lead in
   the key. Not SGP's long table with one `value` column: one unit per column.
4. **Previous Runs keeps every series of SGP's tiers t1 to t6**, plus day0 radiation and total
   cloud cover for ECMWF IFS, ICON-EU and GFS (the models that share their series go in one
   request). Each series is asked for from the start of its model's archive; rows where every value
   is null are dropped. 74 series: 616 calls per daily fetch for the 79 points.
5. **Previous Runs**: `overwrite`, daily, lookback 7 days (a request costs the same for 1 and 14
   days), horizon 0 (a value of a future hour can still change), pieces of 13 days (14 dates).
6. **Single Runs: the 00 UTC run only**, of three models, 72 h; `revisions: none` with the window on
   `init_time`, as weathernext3. A run is stored only whole (every model that should have it, every
   point, all radiation hours): a run that isn't whole is skipped for 18 h, then kept without the
   missing model, which `fetch.py` reports on stderr. IFS also has 06, 12 and 18 UTC runs.
7. **ERA5 from 2015-01-01**, as the SwissMetNet datasets (from 1940 would cost about 320,000
   calls). ERA5-Land gives `temperature_2m_land` and `snow_depth`; ERA5 the rest.
8. **CAMS: both domains**, with `domain` in the key; optical depth from the global domain only (it
   is empty in the European one).
9. **`openmeteo_stations.cells`**: one request per model at all points (14 models, 1,106 calls),
   every 7 days, with `stations_in_cell` (how many of the 79 stations share the cell).
10. **ENS: all 19 variables of the store** (Renaud, 2026-11-16: "ENS should get more variables";
    the first version kept radiation, total cloud cover and temperature), leads 0 to 48 h (as
    weathernext3 and SGP), one row per station with the grid point in its own table. Two tables by
    what a value covers: `three_hourly` (radiation short-wave and long-wave, precipitation in mm
    over the 3 hours, wind gusts) and `instant` (the 15 others, pressures in hPa, the levels 925,
    850 and 500 hPa included: an inversion between 2 m and 925 hPa goes with high fog on the
    Plateau). Wind as u and v, as the source gives it (speed and direction in the field
    description). A run counts as written when temperature has every value and radiation at least
    one value per lead, because the store's `ingested_forecast_length` is empty and its radiation
    has isolated nulls for good.
11. **Snow depth in cm** (Open-Meteo gives m; MeteoSwiss and SGP use cm).
12. **The client** (the same in the five openmeteo `fetch.py`, a test checks it): several points
    per request (each answer carries `location_id`), at most 200 calls per request; a 429
    "minutely" waits 65 s, "hourly" 600 s, the day or the month fails the fetch. Calls are counted
    as SGP did: each model x variable x lead is one variable, each point one location (the pricing
    page doesn't say how points count).
13. **No backfill on the Mac**: it would use a month of the free tier from the Mac's IP; a few
    windows at the edges of each archive instead. ENS for November 2025 only (about 0.7 GB read).
11. **Snow depth in cm** (Open-Meteo gives m; MeteoSwiss and SGP use cm).
12. **The client** (the same in the five openmeteo `fetch.py`, a test checks it): several points
    per request (each answer carries `location_id`), at most 200 calls per request; a 429
    "minutely" waits 65 s, "hourly" 600 s, the day or the month fails the fetch. Calls are counted
    as SGP did: each model x variable x lead is one variable, each point one location (the pricing
    page doesn't say how points count).
14. **The call budget is in the fetchers** (Renaud, 2026-11-16: "put directly in the Python code,
    in the fetcher"), not in the server. The openmeteo_* fetches of one machine write each request
    in one file (`$XDG_STATE_HOME/adele/openmeteo-calls.tsv`; steacher1: `/var/cache/adele/state`,
    set in the fetch unit, since `adele` has no home) and keep together under 500 calls per
    minute, 4,000 per hour and 9,000 per 24 h (rolling windows, so a calendar day stays under them
    too; 9,000 x 31 days stays under the month's 300,000). A window that ended more than 14 days
    ago is a backfill and stops at 7,500 per 24 h: the scheduled fetches (about 1,300 a day) always
    find calls left. A wait longer than 20 minutes fails the fetch with `BudgetSpent` and the time
    from which the request fits, since a fetch may last 30 minutes on steacher1
    (`fetch_timeout_s`).
15. **The backfill is one script**, `deploy/wp5.10-backfill.sh` (root, Renaud), which runs
    `deploy/backfill_by_window.py`: one `adele-server backfill` per window, and after a
    `BudgetSpent` the same window again from the time that it names. One lock per window, so the
    scheduled fetches run between two windows; the timers are on from the start. The windows
    done are written down, so a restart after a reboot skips them. No server change: the
    server's backfill fetches all windows in one go and holds the lock for days.

## Findings

- **SGP's Open-Meteo backfill has been stuck since 2026-11-06 07:43** (processes 29318 and 79650
  still run): one ERA5 request weighs 555 calls and `fetch_openmeteo.py:179` waits until a minute
  holds at most 550, which never happens. So ERA5 and CAMS were never downloaded there. Not touched.
- **Equal to SGP's downloads.** Previous Runs: 917,980 values of tiers t1 to t5 (2026-10-24 to
  10-30, 79 points), all equal except temperature: 1.3 to 1.9 % per model and lead differ by
  0.1 degC, changed by Open-Meteo between SGP's downloads (2026-10-31 to 11-03) and 2026-11-16 (a
  second fetch the same day changed nothing). Single Runs: 30,120 values (IFS, 6 runs, 10 stations),
  all equal. ENS: 867 values per run at Payerne (2 runs), all equal. Cells: the 54 ecmwf_ifs025
  cells are SGP's at all 79 points.
- ERA5 is on a 0.25-degree grid too, but picks other cells than ecmwf_ifs025 (56 cells against 54).
- CAMS global starts on 2022-08-04 at these stations (not 08-01). Its hours between the 3-hourly
  values are filled by Open-Meteo, not on a straight line (mean distance to the linear value
  0.04 and 0.06 ug/m3 at the first and second hour, mean dust 0.23 ug/m3).
- A Single Runs request that names a model without that run fails as a whole (HTTP 400), so the
  models are asked by date (ICON-CH from 2026-04-02).
- The ENS store held the run of 2026-11-16 whole at 09:00 UTC; its `ingested_forecast_length` is
  NaT for all 960 runs. Its total cloud cover is empty up to the run of 2025-11-20 and complete
  from 2025-11-21 (the 30 runs of 2025-11 backfilled on the Mac, none failed); precipitation type
  and wind gusts are empty up to 2024-11-12 and complete from 2024-11-13 (bisection at Payerne).
  dynamical.org's catalog says the same, and its validation report (2026-08-19, 871 runs) counts
  645 runs complete for gusts and precipitation type, 272 for cloud cover, 870 for precipitation
  (one incomplete, 2026-07-12), and "NaN at isolated points where the source's running total
  decreases" in radiation and precipitation.
- Reading ENS is slow: 12 to 24 s per variable and run from the Mac (one chunk of about 8 MB per
  variable). All 19 variables: 235 s for the run of 2026-11-15, 455 s for 2024-04-01.
- The answers of the Previous Runs API run 3 days into the future for previous_day1 and
  previous_day2 too (from the latest run that qualifies).

## Backfill on steacher1 (when WP1 is done)

Calls estimated from the `fetch.py` (their weight and requests), windows of 13 or 14 days:

| order | dataset | from | calls | days of budget |
|---|---|---|---|---|
| 1 | `openmeteo_stations` | | 1,106 | |
| 2 | `ecmwf_ifs_ens` | 2024-04-01 | none (S3; 19 variables: about 140 GB read, estimated from the chunks; about 2 days at 2 to 4 minutes per run, as from the Mac; about 1.3 GB stored, 1.3 MB per run on the Mac) | |
| 3 | `openmeteo_previous_runs` | 2024-01-18 (all models) | about 46,500 | 6 |
| 4 | `openmeteo_previous_runs` | 2021-03-22 (day0 of GFS and ICON-EU) | about 6,700 | 1 |
| 5 | `openmeteo_cams` | 2022-08-01 | about 15,500 | 2 |
| 6 | `openmeteo_single_runs` | 2026-04-02 (three models) | about 39,000 | 5 |
| 7 | `openmeteo_era5` | 2015-01-01 | about 49,000 | 6 |
| 8 | `openmeteo_single_runs` | 2024-03-14 (IFS only) | about 60,000 | 7.5 |

About 220,000 calls: 30 days at 7,500 calls a day (choice 14), beside the scheduled fetches of
the four datasets (Previous Runs 616, Single Runs about 190, ERA5 and CAMS 158 each, the cells 158
a day on average). Renaud chose on 2026-11-16 to run every row ("let's take the time"), on
steacher1, as soon as it is online, and not to import SGP's downloads.

How: land WP5.10, push main, then `ssh s 'sudo bash -s start' < deploy/wp5.10-backfill.sh`. It
pulls main into `/opt/adele`, installs the fetch unit (with `XDG_STATE_HOME`), restarts the query
server, enables the six timers, and starts two backfills in instances of the fetch unit that are
not datasets: `adele-fetch@openmeteo-backfill` (rows 3 to 8 in this order, by
`backfill_by_window.py`) and `adele-fetch@ens-backfill` (row 2). Claude follows them with sc-run
(`journalctl -u adele-fetch@openmeteo-backfill.service`); `finish` removes the drop-ins once both
have stopped.

## Open

1. Every definition is a draft by Claude: titles, descriptions, warnings, labels.
2. SGP's stuck backfill (processes 29318 and 79650): stop it, or fix `fetch_openmeteo.py:179`.
   With these datasets, its ERA5 and CAMS steps are no longer needed.
3. Checks for the forecasts (Renaud asked how, 2026-11-16): the options and Claude's
   recommendation are in `qa/published_figures_openmeteo.md` (last two sections); Renaud has not
   chosen yet.
4. The backfill on steacher1: push main, then `ssh s 'sudo bash -s start' < deploy/wp5.10-backfill.sh`.
   ENS with all 19 variables (Renaud, 2026-11-16: "all 19"; about 140 GB read, about 2 days).
   Leads beyond 48 h would cost no more reading (one chunk holds all leads), only storage.

## Log

### 2026-11-16, the build

Probes of the four Open-Meteo APIs and the ENS store at Payerne (about 30 calls), then the six
datasets in turn, each fetched on short windows, fetched again, compared with SGP. About 6,300 of
the day's 10,000 calls from the Mac's IP were used.

### 2026-11-16, after Renaud's answers

Renaud: the budget may go into the fetchers; no import of SGP's downloads; backfill everything on
steacher1 as soon as it is online (he expects it on 2026-11-17); ENS gets more variables; he asked
how the forecasts can get checks. Built: the shared call ledger (choice 14), the driver and the
root script (choice 15), ENS with 19 variables (choice 10). On the Mac: the ledger written from
inside the runner (CAMS, 2 x 79 calls), the driver on 2 CAMS windows, 3 ENS runs with 19
variables (133,036 rows each, 2 to 4 minutes each). The run of 2026-10-20 is again equal to SGP's
extract at Payerne (867 rows; radiation, cloud cover, temperature), and it reproduces SGP's
published figure for that run (`ECMWF_BASELINE.md`: ensemble mean GHI at lead 12 196 W/m2,
p10-p90 126-264): 196.2, 126.5 and 264.0. The old local ENS tables `radiation` and `weather`
stay in `data_nosync/ecmwf_ifs_ens/` of the worktree (the delete was refused; 4.9 MB, unused).
Landed in `main` the same day (6ef3c3f), after a TODOs.md commit of Renaud's.
