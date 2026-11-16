# WP5: datasets

Draft by Claude, 2026-11-15, at Renaud's request. From `docs/datasets-inventory.md` (section 3),
`qa/revisions_entsoe_ch.md`, `PLAN.md` and `TODOs.md`. The same list, grouped by the build that
each dataset needs, is in the Claude Doc "adele: WP5 by dataset"
(https://claude.ai/artifact/Jg2jVRVd4AW9URE7iJtsBY). The sub-packages are Claude's proposal, not
decided.

## Where WP5 stands (2026-11-15)

- 3 datasets are in adele: `entsoe_day_ahead_prices` and `weathernext3` (no build),
  `entsoe_load` (WP3, `append-only`). The EPEX monthly report is in adele as checks of the
  day-ahead prices, not as a dataset.
- WP1 runs its week on steacher1 until 2026-11-22. WP3 is in `main`. WP2 is decided (D22, D26),
  not built.

## Goal and assumption

This file assumes that WP1, WP2 and WP3 are done. Then WP5 can write **44 datasets**: 26 that
fit adele as it is built today, 9 that need versions (WP3) and 9 that need a table shape of WP2.

By the definitions of `PLAN.md`, the 18 datasets that need WP2 or WP3 belong to WP6. This file
puts them in WP5 because those builds are assumed done; `PLAN.md` is not changed. WP4 is not
assumed: its 8 datasets and 7 others are under "Not in WP5".

Each dataset: a descriptor and a `fetch.py` (`skills/add-dataset`), a backfill on steacher1
(`PLAN.md`). Its checks from published figures (WP8) and what its data means (WP7, Renaud's) go
with it.

Rows follow the rows of the inventory, with one exception: physical flows (A11) and scheduled
exchanges (A09) share a row there and get one each here. A row can hold several tables (the
MeteoSwiss lists, EBAS, AERONET). "Rows already downloaded" are the counts of the swissgrid
project (SGP). "Measured" means `qa/revisions_entsoe_ch.md`: two downloads 15 days apart.

## Sub-packages

The datasets of a sub-package share their fetch: a source, a client, a file format, or a
reference table. Order: ENTSO-E first (`TODOs.md`: the API and token of
`entsoe_day_ahead_prices`). The rest is not ordered.

| | sub-package | datasets | no build | WP3 | WP2 |
|---|---|---|---|---|---|
| WP5.1 | ENTSO-E without versions | 6 | 5 | | 1 |
| WP5.2 | ENTSO-E revised series | 4 | | 4 | |
| WP5.3 | ENTSO-E forecasts | 3 | | 3 | |
| WP5.4 | Prices outside ENTSO-E | 4 | 4 | | |
| WP5.5 | Pronovo | 3 | | 2 | 1 |
| WP5.6 | PV of BFE and SolarEdge | 4 | 3 | | 1 |
| WP5.7 | MeteoSwiss stations | 7 | 5 | | 2 |
| WP5.8 | Satellite, aerosols, eclipses | 4 | 3 | | 1 |
| WP5.9 | Weather regimes and types | 4 | 2 | | 2 |
| WP5.10 | Weather forecasts at stations | 5 | 4 | | 1 |
| | total | 44 | 26 | 9 | 9 |

WP2 builds two shapes: a table without a time column, replaced whole at each fetch (D22), and a
table by calendar day, month or year, with a column `delivery_date`, `delivery_month` or
`delivery_year` and one time zone per table (D26).

### WP5.1 ENTSO-E without versions

Shared: the client and the token of `entsoe_day_ahead_prices`, and `revisions: overwrite`.
Prices and installed capacity were not revised in 15 days (measured). The 1-minute balancing
state and the neighbours were not compared. The neighbours are fetched in windows of half a year,
split when the API answers "too large".

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| CH `imbalance_price` (A85) | imbalance price, two rows per interval (long, short) | 724,662 from 2016-03 | none | |
| CH `activated_price` (A84) | prices of activated aFRR, mFRR, RR | 1.6 million | none | |
| CH `balancing_state_1min` (A86, B33) | area control error per minute, 2019-09 to 2025-06 | 3.0 million | none | the series ended in June 2025: a backfill, then nothing new |
| neighbours `imbalance_volume` (A86) | AT, FR, IT, DE (10 areas), from 2015 | 3.6 million | none | 607 answers held no data or an error (G7). See open question 3 |
| neighbours `imbalance_price` (A85) | AT, DE_LU, FR | 1.8 million | none | |
| CH `installed_capacity` (A68) | one row per year and type | 48 | WP2: `delivery_year` | |

### WP5.2 ENTSO-E revised series

Shared: `revisions: append-only` (D30), the same client, and `entsoe_load` as the model. These
are the series that the measure found revised; Renaud agreed to build them (`TODOs.md`). The
lookback decides which corrections adele keeps: flows are corrected up to 12 months later.

| dataset | what | rows already downloaded | build | why versions |
|---|---|---|---|---|
| CH `generation` (A75) | actual generation per type | 608,417 | WP3 | 36 values changed in 15 days, mostly the last hours (measured). The Swiss PV series is Pronovo rescaled |
| CH `flows` (A11) | physical flows per border | 1.5 million | WP3 | 6,398 values changed in 2025-2026, most at 1 to 12 months (measured). See open question 1 |
| CH `scheduled` (A09) | scheduled exchanges per border, day-ahead and total | 2.4 million | WP3 | 541 of 1,258 hours ahead changed before delivery (measured). See open question 1 |
| CH `imbalance_volume` (A86) | imbalance volume, from 2015-03 | 406,212 | WP3 | "intermediate" values become final; one day of 2025 corrected a year later (measured) |

### WP5.3 ENTSO-E forecasts

Shared: the versions are the point. The platform keeps only the latest version of a forecast,
so adele holds a version only if a fetch saw it before the next one replaced it.

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| CH `ws_forecast` (A69) | wind and solar forecast: day-ahead, intraday, current | 235,094 | WP3 | G4 would help |
| neighbours `ws_forecast` (A69) | 16 areas | 22.4 million | WP3 | |
| CH `forecast_versions` | each version of the Swiss PV and load forecasts | 634 values | WP3 | a fetch every 3 hours (4 requests). The versions of 2026-10-16 to 2026-10-26 are lost. See open question 6 |

### WP5.4 Prices outside ENTSO-E

Shared: what they measure (prices per quarter-hour or hour) and how they are checked (published
averages, the EPEX monthly report). Energy-Charts gives one JSON per country and year, or an API,
without a key. Swissgrid gives xml and xlsx files, read with the parsers of SED
(`sources/ch_swissgrid/`).

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| Swissgrid `imbalance_prices` | imbalance prices per quarter-hour, 2023 to Sep 2026 | | none | one xml and one xlsx per month, one zip per year. ENTSO-E's CH A85 (WP5.1) may be the same quantity: a possible check (D12) |
| Energy-Charts, CH spot prices | day-ahead, and hourly intraday (average, low, high, IDA1, IDA2), 2019 to 2026-10 | | none | EPEX data: internal use |
| Energy-Charts, DE spot prices | day-ahead, ID Full, ID3, ID1, low, high, IDA15, from 2019 | 68,616 hours | none | same |
| Energy-Charts API, DE-LU day-ahead | quarter-hours from September 2025 | 38,548 | none | |

### WP5.5 Pronovo

Shared: the same zips (directory listings, no login): a provisional zip per month (a median of
11 days after the month), then a definitive zip per quarter, and a file can be issued again. One
dataset with three tables needs the `adele:` block per table (the first step of WP2); three
datasets don't.

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| `pronovo_15min` | measured production per technology (33), 15 minutes, 2020 to 2026-09 | 7.6 million | WP3 | provisional --> definitive is a revision |
| `pronovo_pv_canton_15min` | PV per canton, from 2023 | 6.6 million | WP3 | same |
| `pronovo_capacity` | capacity and number of units per canton and technology, per month from 2023-01 | | WP2: `delivery_month` | |

### WP5.6 PV of BFE and SolarEdge

Shared: the two datasets of the energy dashboard use one API (by month, no key). The register
and SolarEdge are here by subject only: PV below the national level.

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| BFE `edb_pv_estimate_hourly` | PV estimate of the energy dashboard per district (143) and hour, from 2026-07-12 | 367,224 | none | |
| BFE `edb_pv_forecast_hourly` | PV forecast of the dashboard per district, 357 runs | 1.3 million | none | the API keeps only the last run per target hour: window on the run time, `revisions: none`, like weathernext3. G4 would help |
| BFE `pv_plants` | the register of plants: 337,455 PV plants, 8,829 MW, state of 2026-09-16 | | WP2: no time column | one zip (19 MB) that BFE replaces now and then. See open question 4 |
| SolarEdge, Renaud's house | production at 15 minutes | 1,155 daily CSVs | none | the official API with a key (about 300 requests a day), not the token copied from the browser |

### WP5.7 MeteoSwiss stations

Shared: the open-data files per station (one "historical" file per decade and one "recent"
file), and the reference tables of stations and parameters. The "recent" files are rewritten
twice a day, and one fetch of all of them moves 851 MB: once a day is enough (inventory,
section 4).

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| `smn_radiation_hourly` | GHI, diffuse, sunshine, longwave at 135 stations, from 2015 | 13.7 million | none | before 2018 an hourly value covers [stamp - 20 min, stamp + 40 min) |
| `smn_regime_hourly` | temperature, humidity, pressure, wind, precipitation, snow depth, foehn index at 33 stations | 3.4 million | none | |
| `smn_tenmin` | GHI and sunshine per 10 minutes at 135 stations, from 2023-10 | 21.8 million | none | |
| `smn_daily` | daily values at 157 stations | | none | the day is the UTC day, so it keeps `delivery_start` and `P1D` |
| `nime_daily` | fresh snow, snow depth, precipitation at 273 stations | | none | the day runs from 06 UTC to 06 UTC |
| `obs_daily` | visual observations at 20 stations (fog day, cloud cover) | | WP2: `delivery_date` | the source does not state the zone of its days: the author writes the most likely one (D26) |
| lists of stations, parameters, inventory | the reference tables of SwissMetNet | 159, 181 and 19,554 | WP2: no time column | the SMN tables could point to them (`foreignKeys`, proposed in the inventory, not decided) |

### WP5.8 Satellite, aerosols, eclipses

Shared: the subject (radiation and what dims it, seen from other sources than the stations).
Little code in common: netCDF from STAC (satellite) and from EBAS, text from a web service
(AERONET), a script (eclipses).

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| MeteoSwiss satellite extract (`sis`, `cfc`, `sisdif`, `srel`) | the cells of the stations and blocks, from 2004 | 25 million | none | an extract only: the full grid is 4.8 billion rows per product |
| EBAS `aod_pfr_hourly`, `jfj_insitu_hourly` | optical depth at Davos and Jungfraujoch, in-situ aerosol at Jungfraujoch | 19,201 and 103,734 | none | route not read |
| AERONET `aeronet_aod_points`, `aeronet_sda_points` | optical depth at instants, 4 sites, levels 1.5 and 2.0 | 402,135 and 398,899 | none | `valid_at`, the level in the key. The file of the current year changes between two fetches (G3 would help) |
| `eclipses.csv` | 8 eclipses, for Bern and for Zurich | 8 | WP2: no time column | computed by a script, not fetched |

### WP5.9 Weather regimes and types

Shared: each value is a class from a fixed list (`categories`): 40 classes for the DWD objective
classes, 30 for the ERA5 catalogue, 7 regimes for Grams. The two daily DWD catalogues don't state
the zone of their days (D26: the author writes the most likely one).

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| DWD `wlk_forecast` | the forecast classes per run day and lead (10 leads) | 61,441 | none | window on the run day (D14) |
| Grams `regimes_grams_3h` | 7 Atlantic-European regimes every 3 hours | 48,232 | none | a new release on Zenodo has a new URL: a change of `fetch.py` |
| DWD `gwl_hb_daily` | Hess-Brezowsky weather type per day, from 2010 | | WP2: `delivery_date` | parsed from PDFs (one per month from 2016), issued a median of 33 days after the month, some issued again (G3 would help) |
| DWD `gwl_rea_daily` | objective catalogue from ERA5, 30 classes, from 1940 | | WP2: `delivery_date` | one CSV per release (v1.6) |

### WP5.10 Weather forecasts at stations

Shared: the 79 stations and their grid cells (`stations.csv`), and the run and the lead in the
key. The three Open-Meteo datasets share one budget of 10,000 calls a day: fine with a fetch per
day. Their backfill (105,000 calls over 11 to 12 days) was a script in Renaud's terminal on
2026-11-14; adele's backfill doesn't track a budget of calls (G7).

| dataset | what | rows already downloaded | build | to watch |
|---|---|---|---|---|
| Open-Meteo Previous Runs (`nwp_runs`) | ECMWF IFS, ICON-EU, GFS: GHI and cloud at 79 stations, per lead day, from 2024-01 | 28.6 million | none | the lead is a key column |
| Open-Meteo Single Runs | one run per request: ECMWF IFS from 2024-03, ICON-CH1 and CH2 from 2026-04 | | none | |
| Open-Meteo ERA5 and CAMS | reanalysis (cloud layers, boundary layer, GHI), dust and optical depth at 79 stations | | none | |
| Open-Meteo `stations.csv`, `variables.csv` | the grid cell of each station (54 cells for 79 stations) | | WP2: no time column | |
| ECMWF IFS ENS (dynamical.org) | 51 members, 0.25 degree, every 3 hours, from 2024-04-01 | | none | an extract at points; run, lead and member in the key. Icechunk store on S3, no login |

## Done when

- Each dataset of the sub-packages has its `datapackage.yaml` and `fetch.py`, passes
  `uv run adele-server validate`, is backfilled on steacher1 and fetched there on its schedule.
- Each has its checks from published figures (WP8), and its curation is done or on its way
  (WP7).

## Not in WP5

15 datasets need more than WP1 to WP3:

| dataset | needs | why |
|---|---|---|
| Swissgrid `control_area_balance` | WP4 | one file per year, revised in place: prices changed 4 to 7 weeks after delivery (G6) |
| Swissgrid `control_area_balance_daily` | WP4 | the file overwrites itself and is lost after 24 h (G4) |
| Swissgrid `total_system_imbalance` | WP4 | the file is replaced every 15 minutes (G4; G5 is built, D27) |
| Swissgrid `energy_statistic` | WP4 | one file per year, updated each month and revised for months (G6) |
| Swissgrid `activation_cost` | WP4 | one csv per year, updated each week (G6) |
| Swissgrid `afrr_1s` | WP4 | the file overwrites itself, about 12 days kept (G4) |
| IGRA2, radiosonde of Payerne | WP4 | one zip for the whole period that NOAA rewrites about daily (G6) |
| DWD `wlk_daily` | WP4 | one text file with the whole history (G6) |
| Swissgrid `reserve_auctions` | a period with its own end (G2b), in no WP | a product covers a week, a day or a block of 4 hours |
| ENTSO-E CH `outages` (A80, A77) | G2b, in no WP, and versions | each row has a start, an end and a document status, and is revised |
| BFE Energie Reporter (`er_pv_*`, `interim_pv_*`) | a state at a date, not decided | the capacity on the last day of each month: stored as a month, it moves 30 days back (inventory, way C, finding 6). Route not read |
| Swissgrid `mfrr_bids` | not worked out | adele needs a primary key: do the files give one per bid? |
| Swissgrid `other_auctions` | not worked out | three csv files; only their headers were read |
| `calendar_daily` | a derived table (G11), out for now | one row per local date, computed by a script |
| BFE `pv_capacity_*` | a derived table (G11), out for now | computed from the register |

Not counted at all: the 18 datasets that stay out of adele (not a table, delivered by hand,
copies, study folders). netztransparenz.de is among them: it would fit only with a `fetch.py` on
its Web-API, which needs an account.

## Open questions

1. **Flows (A11) and scheduled exchanges (A09):** `append-only` (this file, Claude's proposal in
   `TODOs.md`) or `overwrite` (the inventory)? With WP3 done, that is the only choice left. Until
   Renaud decides, a WP5 session leaves them out.
2. **WP2 frees 9 datasets, not 13.** `TODOs.md` says 13: that is every dataset marked G1 or G2.
   Four of them need more than D22 and D26: `reserve_auctions` and `outages` (a period with its
   own end), the Energie Reporter (a state at a date), `calendar_daily` (a derived table).
3. **Imbalance volume of the neighbours (A86)** counts as fitting today, while the CH series of
   the same document type needs versions ("intermediate" values become final). The neighbours
   were not measured.
4. **BFE `pv_plants`:** replaced whole at each fetch (D22), it loses the retired plants. D22 and
   D30 don't say whether `append-only` works on a table without a time column.
5. **One dataset or several** for the rows that hold several tables (MeteoSwiss lists, EBAS,
   AERONET, the satellite products, ERA5 and CAMS), and whether `pronovo_capacity` goes into the
   dataset of `pronovo_15min`.
6. **`forecast_versions` overlaps two other datasets.** With `append-only`, `entsoe_load` (A65)
   already keeps each version of the day-ahead load forecast that a fetch sees, and CH
   `ws_forecast` (A69) would keep each version of the PV forecast. Is `forecast_versions` still a
   dataset of its own, or only the import of the 634 versions already collected?
   **Answer (Renaud, 2026-11-16): no dataset.** Its collector saw one version of each hour; its
   438 A69 values equal adele's except 3 (the older values of three revised night values of
   2026-10-26/27). The load forecast is in `entsoe_load`. adele can't import old versions: the
   server stamps `fetched_at` itself.

## Log

### 2026-11-15, the list and the sub-packages

Claude split WP5 into datasets at Renaud's request: first the Claude Doc (grouped by build),
then this file, with the datasets grouped into sub-packages by what their fetch shares. Counts
checked against `PLAN.md` ("3 of 30 datasets are in adele") and `TODOs.md` ("27 datasets that
fit today"): 26 + flows and schedules as one row = 27.

### 2026-11-16, WP5.3 in `main`

Built by Claude in the worktree `wp5.3` (2026-11-15/16), landed before WP5.2 at Renaud's
request:

- `entsoe_wind_solar_forecast` (CH `ws_forecast`) and `entsoe_wind_solar_forecast_neighbours`
  (16 areas), `append-only`, the same columns; one `fetch.py` that differs only in `AREAS`.
  Backfilled on the Mac: 236,584 and 22,567,278 rows, from 2015.
- 125 published figures as checks: 11 + 14 for CH, 100 for the neighbours.
  `qa/published_figures_entsoe_wind_solar_forecast*.md`.
- D34: 14 CH checks read `entsoe_generation` (WP5.2), so until WP5.2 is in `main` they fail
  where the forecast data exists without it. On steacher1, install WP5.2 with WP5.3 or before
  it. The server removes the declared secrets from what `fetch.py` prints.
- `forecast_versions`: not built (open question 6).
- Left: Renaud's review of the definitions (drafts by Claude, WP7); the backfill on steacher1
  after WP1.
