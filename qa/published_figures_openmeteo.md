# QA of the WP5.10 datasets: comparisons and published figures

Claude, 2026-11-16 (WP5.10). Datasets: `openmeteo_previous_runs`, `openmeteo_single_runs`,
`openmeteo_era5`, `openmeteo_cams`, `openmeteo_stations`, `ecmwf_ifs_ens`.

## Where figures could come from

- **Figures published by others**: none sought on the web. Forecasts at points and reanalysis cells
  at stations are not what weather services, ECMWF or Copernicus publish (they publish scores over
  regions, or measured values), so a published figure would not be computed from the same values.
  A search can still be run if Renaud wants one (CAMS dust episodes, ERA5 in papers on Swiss PV).
- **The analyst's own documents**: the swissgrid project (SGP) downloaded the same APIs at the same
  79 points in October and November 2026 and documented its counts in
  `swissgrid_project/data/nwp/README.md` (QA C1 to C7, run 2026-10-31). Those figures are the
  checks below, now for the cells, after the backfill for the forecasts.

## Checks now: `datasets/openmeteo_stations/checks.yaml`

Six figures of SGP's QA C7, all reproduced on 2026-11-16: 54 ecmwf_ifs025 cells for the 79 stations,
29 for the Plateau, 45 stations that share their cell, 10.5 km from an Alpine station to its cell
on average, 78 cells for icon_eu and 75 for gfs_global (SGP: distinct series). They fail when
Open-Meteo moves a model to other cells, which breaks the series of the other datasets.

## Comparisons with SGP's downloads (`qa/tools/compare_sgp_openmeteo.py`)

Value by value, not figures; they test the stamps, the units and the keys of `fetch.py`.

| dataset | SGP's data | window | values compared | result |
|---|---|---|---|---|
| `openmeteo_previous_runs` | raw answers of tiers t1 to t5 (`data/nwp/raw_nosync/`) | 2026-10-24 to 2026-10-30 22:00 UTC, 79 points | 917,980 | all equal except temperature_2m: 1.3 to 1.9 % per model and lead differ by 0.1 degC (Open-Meteo changed them after 2026-11-03). None missing in adele; 78,684 only in adele (day0 radiation and cloud cover of three models, which SGP didn't ask for) |
| `openmeteo_single_runs` | `data/nwp/parts_nosync/single-runs/` (IFS, 10 stations) | runs of 2026-10-20 to 2026-10-25 | 30,120 | all equal |
| `ecmwf_ifs_ens` | `semester_project/sem project/03_WN3/data/ecmwf_ens_payerne_*.parquet` | runs of 2026-09-03 and 2026-10-20, Payerne | 867 per run | all equal |
| `openmeteo_stations` | `data/nwp/stations.csv` | | 79 points | the same ecmwf_ifs025 cell at all 79; terrain height equal at 77 |

ERA5 and CAMS: SGP never downloaded them (its backfill has been stuck since 2026-11-06).

## Candidate checks, once the backfill covers SGP's period (2024-01-20 to 2026-10-30)

From SGP's QA C1 and C4 (t1, 79 points, `delivery_start` or `valid_at` from 2024-01-19 23:00 UTC to
2026-10-30 23:00 UTC). Each is a count, tolerance 0.5.

- Rows with a value, per series (15 figures), e.g. ecmwf_ifs025 previous_day1 shortwave_radiation
  1,835,881; gfs_global previous_day1 shortwave_radiation 1,924,440; icon_eu previous_day2
  cloud_cover 1,915,987; ecmwf_ifs025 day0 cloud_cover_low 1,897,896. SQL:
  `SELECT count(shortwave_radiation) FROM openmeteo_previous_runs.hourly WHERE model = 'ecmwf_ifs025'
  AND lead = 'previous_day1' AND delivery_start >= TIMESTAMPTZ '2024-01-19 23:00:00Z' AND
  delivery_start < TIMESTAMPTZ '2026-10-30 23:00:00Z'`. They test the backfill (no hole, the start of
  each archive).
- The two holes: icon_eu previous_day2 has no radiation for 95 hours from 2026-04-07 12:00 UTC
  (expected 0 rows), ecmwf_ifs025 previous_day2 no cloud cover for 129 hours from 2026-04-17 15:00 UTC.
  They test that adele keeps the holes as holes.
- GFS cloud cover outside [0, 100]: previous_day1 167 below 0 and 817 above 100, previous_day2 151 and
  816, day0 cloud_cover_low 264 and 430. They test that values are kept as served.
- Single Runs: SGP's table holds 952 IFS runs from 2024-03-14 to 2026-10-25 (956 days); if adele finds
  the same 952, the count of runs is a check.

Temperature is not a candidate: Open-Meteo changed 1 to 2 % of the values by 0.1 degC within two
weeks.

## Candidate checks for `ecmwf_ifs_ens` (options given to Renaud on 2026-11-16, not decided)

Renaud asked how the forecasts can get checks. The options, by Claude; none is in a checks.yaml yet:

1. dynamical.org's validation report (https://dynamical.org/catalog/ecmwf-ifs-ens-forecast-15-day-0-25-degree/validation/,
   2026-08-19), counted over the whole grid, independently of adele: 871 runs from 2024-04-01 to
   2026-08-19; 645 complete for wind gusts and precipitation type (from 2024-11-13); 272 for cloud
   cover (from 2025-11-21); 870 for precipitation (one incomplete, 2026-07-12); 51 members. Tests
   lost runs, members and variables that go empty, not the values. Pass only once the ENS backfill
   covers 2024-04-01 to 2026-08-19.
2. SGP's figure for the run of 2026-10-20 (`semester_project/sem project/03_WN3/ECMWF_BASELINE.md`,
   2026-10-25): at Payerne (grid point 46.75 N, 7.00 E), GHI at lead 12 (09 to 12 UTC), ensemble
   mean 196 W/m2, p10 to p90 126 to 264. adele reproduced it on 2026-11-16: 196.2, 126.5, 264.0
   (`avg`, `quantile_cont` over the 51 members of `three_hourly`, station PAY, lead_h 12). Could go in
   at once (tolerance 1 W/m2). Tests units, lead and members; same archive and Renaud's own project,
   so it tests adele's pipeline, not the archive.
3. Open-Meteo's ensemble API (ECMWF IFS 0.25, 51 members), a second redistribution of the same
   forecast: spot values as figures. Not probed: whether it serves past 00 UTC runs, and whether
   its values are raw or interpolated.
4. Not recommended: skill against measurements compared with ECMWF's published scores (other
   stations and periods, so a difference is no error).

Claude's recommendation: 2 now, 1 after the ENS backfill, 3 only if a probe shows raw values. For
ERA5 and CAMS no figure was found yet (a published Saharan dust episode with values at Swiss
stations would need a search).
