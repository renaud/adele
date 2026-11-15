# Datasets of `swiss_energy_data` and `swissgrid_project`: inventory, and what adele needs to manage them

Status: inventory of 2026-11-14, asked by Renaud. The verdicts and the proposals of sections 4 and 5
are Claude's and are not decided. SED = `/Users/ren/switchdrive/backup/_EnTr/projects/swiss_energy_data/`,
SGP = `/Users/ren/switchdrive/backup/_EnTr/projects/swissgrid_project/`.

How it was made:

- Read in full by Claude: SED `SOURCES.md`, `MIGRATION.md` and `sources/ch_swissgrid/source.yaml`; SGP
  `data/README.md`, `data/catalog.csv` (184 files, 186 million rows), `code/datasets/README.md`, and
  the docstrings of the 9 fetch scripts in `code/datasets/`.
- Read by a research agent and not checked again by hand: every folder of SGP outside `data/` and
  `code/datasets/` (webcams, the collectors on steacher1, the WeatherNext pulls, Carlo's repository,
  `lit_search/`, `semester_project/`, `explainers/`, `talks/`).
- Not read: the README of each folder of SGP `data/`, beyond its licence lines. Where a route is
  not known, the table says so.
- "adele today" = SPEC.md, DECISIONS.md D1 to D21, and the server code of commit b26746f.

## In short

- Section 3 lists 83 datasets. **30 fit adele as it is built today** (3 of them are in adele).
  **8 fit once POC 2 is built** (`append-only`, `as_of`). **25 need something that adele doesn't
  have.** 18 stay out: data that is not a table and data delivered by hand (both non-goals since
  2026-11-14), copies, study folders. 2 are not worked out. Rules of use (licences, embargo) are
  not counted: not a concern so far.
- Of the 25: 13 need a table without a time column (G1, decided: D22) or a period that is not a
  fixed duration in UTC (G2, decided for calendar periods: a date column). 5 need a whole file
  compared at each fetch (G6). 3 are the Swissgrid files that overwrite themselves (raw answers
  kept, G4, and a fetch that must not be missed, G5). 1 is the Open-Meteo backfill (a budget of
  calls over 12 days, G7). 3 are groups of derived tables (G11, out for now).
- Memory between two fetches (section 4): none for now, no journal and no SQLite file (D23). What
  is stored stays computed from the Parquet files: measured, it costs under 1 ms per file.
- `datapackage.yaml` (section 5): 4 standard properties to start using (`sources`, `keywords`,
  `foreignKeys`, `constraints`) and additions of adele's own, ranked by the number of datasets
  that need them.

Renaud's answers of 2026-11-14, in two rounds: G1 such tables are supported, and a row that the
source drops goes (D22). G2 a date column for calendar periods (way C of section 5). G3 fine with
POC 2. G5 must be supported (Swissgrid's TSI); how fetches run side by side is in discussion.
G7 no journal, no SQLite file, nothing between two fetches for now (D23). G8 a non-goal. G9 not a concern so far. G10 a non-goal. G11 stays
out.

## 1. What adele manages today

A dataset is a `datapackage.yaml` and a `fetch.py` with `fetch(start, end)`. The server calls it on
a schedule, for the window [now - lookback, now + horizon), keeps the fetched rows whose window
time falls inside it, checks them against the descriptor, and merges them into Parquet files (one
per month or per day).

- Every table has exactly one time column: `delivery_start` (an interval, with a resolution) or
  `valid_at` (an instant) (D17). The window column is a datetime of the primary key (D14).
- Revisions: `overwrite` and `none` (D15) are built. `append-only` and `as_of` are in SPEC.md and
  not built (POC 2).
- Per dataset, the server keeps `state.json` (the last fetch, the status, the problems) and a lock
  file. Coverage and row counts are computed from the Parquet files on each request.
- The timer runs every 15 minutes (`deploy/adele-fetch.timer`). `stale` is not built.
- One API key per team member; every key reads every dataset.

## 2. The gaps

Each gap has a code that the tables of section 3 use.

| code | gap | what the datasets need | status |
|---|---|---|---|
| G1 | **Tables without a time column.** A register of plants, a list of stations, of districts, of holidays. D17 and D14 refuse them | a table with a primary key and no time column, stored as one file and replaced whole at each fetch | decided: D22 (2026-11-14), not built |
| G2 | **Periods that are not a fixed duration in UTC.** (a) A calendar day, month or year in local time: a day of Europe/Zurich lasts 23 to 25 hours, so [start, start + P1D) is wrong on two days a year, and a month has no fixed duration. (b) A period with its own end: an outage, an event, a tender product | (a) a date column, and the zone in the catalog (way C of section 5); (b) a second column `delivery_end` | (a) decided by Renaud on 2026-11-14, details open. (b) waits for the first dataset that needs it |
| G3 | **Versions.** The source changes a value later, and the first value matters (a forecast before delivery, a provisional price) | `append-only` and `as_of` | decided, not built (POC 2) |
| G4 | **Raw answers are not kept.** adele stores only the parsed rows. For a source that overwrites itself, a parser error then loses the original for good | each answer kept as received, with its sha256 | known: `from-swiss-energy-data.md`, item 1 |
| G5 | **A missed fetch is lost.** Swissgrid's TSI file holds one quarter-hour and is replaced every 15 minutes. adele's timer runs every 15 minutes: one late run loses a quarter-hour. The poller of today asks every minute, from cron | a timer every minute, and three changes in the server (below the table) | new |
| G6 | **Whole files revised in place.** The server drops the fetched rows that fall outside [now - lookback, now + horizon) (`ingest.py`, `_stage`). A year file that the source revised 6 weeks back loses that revision when the lookback is 3 days | a lookback that covers the whole file, or a refresh that compares everything | new, small |
| G7 | **State of the download.** A budget of calls over days, answers that held no data, files already seen, a backfill that stops and goes on | nothing for now; a bookmark when the first dataset needs one (section 4) | decided: D23 (2026-11-14). No journal and no SQLite file |
| G8 | **Delivery by hand.** A CSV export in a browser, a table typed from a PDF, files from a colleague. `adele.refresh` requires `every`, `lookback` and `horizon` | out of adele | a non-goal in SPEC.md since 2026-11-14 |
| G9 | **Rules of use.** Licences that forbid redistribution (a server for a team counts as redistribution), and the embargo of the blind test | access per dataset, and the embargo | not a concern so far (Renaud, 2026-11-14). Not counted in section 3 |
| G10 | **Not a table.** Images, PDFs, rasters, full grids | out of adele | a non-goal in SPEC.md since 2026-11-14 |
| G11 | **Derived tables.** Tables computed from other datasets | out of adele for now, or SQL views | out for now (Renaud, 2026-11-14) |

G5 in the server (read in the code on 2026-11-14). A timer every minute is not enough by itself:

- `adele-server fetch --due` fetches the due datasets one after the other, in one process, and the
  service is `Type=oneshot`: while a run is active, the next ticks of the timer start nothing. A
  fetch of weathernext3 lasts minutes (the limit is 1,800 s), and TSI waits behind it. Each
  dataset needs its own process (the lock per dataset exists).
- `is_due` is `now >= last_attempt_at + every`. An attempt stamped 12:00:02 makes the tick of
  12:01:00 "not due", so `every: PT1M` gives a fetch every 2 minutes. The poller subtracts 15 s
  for this.
- After each fetch the server runs every check, changed rows or not: 1,440 times a day.

What a missed fetch loses: the values at 5 minutes inside the quarter-hour, and the time at which
they were first published. The quarter-hour value of TSI comes again in the daily file (24 h) and
in the year file.

## 3. The datasets

Last column: **yes** = fits what is built today. **later** = fits once a decided feature is built.
**no** = needs the gaps named. **out** = should not be in adele. **open** = not worked out. A
second gap after a semicolon is one that the dataset would profit from but that doesn't block it.

### 3.1 Swissgrid (swissgrid.ch)

No login. Licence: none stated (a disclaimer only): cite, don't redistribute the raw files. SED
worked the source out: URLs, German headers, units, signs and parsers are in `sources/ch_swissgrid/`.
4,094 files received, 833 MB.

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| `control_area_balance` | balance of the control area per quarter-hour since Nov 2024: TSI, activated aFRR, mFRR and RR, IGCC netting, FRCE, provisional imbalance price | one file per year, revised in place: prices changed 4 to 7 weeks after delivery; the poller holds 23 versions of the 2026 file | no: G6, G3 |
| `control_area_balance_daily` | the same balance, the last 24 h only | the file overwrites itself (lost after 24 h); a poller on steacher1 asks every 5 minutes and kept 1,797 versions | no: G4, G3 |
| `total_system_imbalance` | TSI at 5-minute stamps, one quarter-hour per file (3 rows) | the file is replaced every 15 minutes (lost after 15 minutes); the same poller asks every minute and kept 2,160 versions | no: G5, G4 |
| `energy_statistic` | production, consumption, border flows and control energy per quarter-hour since 2009 (622,268 rows), by canton since 2015 (8.2 million rows) | one xls or xlsx per year, updated each month, revised for months; the stamp marks the end of the interval until 2024 and the start from 2025 | no: G6; G3 |
| `imbalance_prices` | imbalance prices per quarter-hour, 2023 to Sep 2026 | one xml and one xlsx per month, one zip per year | yes |
| `activation_cost` | offered and activated aFRR and mFRR, average prices, cumulative cost per quarter-hour, 2026 | one csv per year, updated each week | no: G6 |
| `afrr_1s` | covered aFRR demand per second, the last 12 days or so (86,400 rows per day) | the file overwrites itself (22 versions, 127 MB); one fetch per day is enough | no: G4 |
| `mfrr_bids` | every mFRR energy bid per quarter-hour, anonymous: MW offered, MW called, price, status; from 2023, about 2 million rows per month | one csv per month, one zip per year | open: adele requires a primary key; do the files give one per bid? |
| `reserve_auctions` | results of the capacity tenders (FCR, aFRR, mFRR): volume, capacity price, country of the bid | one csv per year, one archive zip | no: G2 (a product covers a week, a day or a block of 4 hours) |
| `other_auctions` | D-1 redispatch with Germany, DW-MEAS-IT with Italy, energy for active losses | three csv files; SED read only their headers | open |
| lists of balance groups | 139 active groups, 18 to be activated, 59 deactivated (company, country, EIC, date) | transcribed from the web page on 2026-10-30 (`lit_search/L_balance_groups.md`) | out: G8 |
| annual reports 2011-2025 | 16,491 values with unit, period, page and quote | read out of 15 PDFs (`lit_search/G_swissgrid_financials/`) | out: G8. Its values can be checks of other datasets (D12) |
| numbers read from Swissgrid PDFs | BGM partner meeting 2025, balancing roadmap 2026-2030, tables of the EPSR paper | by hand, from charts and tables | out: they belong to the study that compares against them |

The poller (`PhaseThreeSwissgridImbalance/swissgrid_poll.py`, cron every minute on steacher1 since
2026-09-27) is the route of the three files that overwrite themselves. It keeps a `state.json`
with, per file, the ETag, the time of the last change, a hash and the time of the last try, and
one log line per fetch (35,294 lines in three weeks). adele replaces it only with G4 and G5.

### 3.2 ENTSO-E Transparency Platform

API with a token (`adele.secrets`). Licence: the terms of the platform; the raw answers are not
redistributed (SGP `data/entsoe/README.md`).

| dataset (document type) | what | how it arrives | fits? |
|---|---|---|---|
| CH `da_price` (A44) | day-ahead prices | in adele since 2026-11-13 (CH, DE, FR) | yes |
| CH `load` (A65) | actual load and day-ahead forecast, 207,442 rows from 2015 | actual load is corrected days later; stamped 1 h late before 2025 | later: G3 |
| CH `generation` (A75) | actual generation per type, 608,417 rows | the Swiss PV series is Pronovo rescaled | later: G3 |
| CH `ws_forecast` (A69) | wind and solar forecast: day-ahead, intraday, current; 235,094 rows | the platform keeps only the latest version of a forecast | later: G3; G4 |
| CH `forecast_versions` | each version of the Swiss PV and load forecasts; 634 values so far | a collector every 3 hours, 4 requests, keeps each answer (not deployed on 2026-11-01). The versions of 2026-10-16 to 2026-10-26 are lost | later: G3 (it is `append-only` with a refresh every 3 hours); G4 |
| CH `imbalance_volume` (A86) | 406,212 rows from 2015-03 | "intermediate" values become final | later: G3 |
| CH `imbalance_price` (A85) | 724,662 rows from 2016-03; two rows per interval (long, short) | | yes |
| CH `activated_price` (A84) | prices of activated aFRR, mFRR, RR; 1.6 million rows | | yes |
| CH `balancing_state_1min` (A86, B33) | area control error per minute, 3.0 million rows, 2019-09 to 2025-06 | | yes |
| CH `flows` (A11), `scheduled` (A09) | physical flows and scheduled exchanges per border; 1.5 and 2.4 million rows | | yes |
| CH `installed_capacity` (A68) | 48 rows, one per year and type | | no: G2 (year) |
| CH `outages` (A80, A77) | unavailability of large units; 30,089 rows, 25 columns | each row has a start, an end and a document status, and is revised | no: G2 (own end); G3 |
| neighbours `imbalance_volume` | A86 of AT, FR, IT, DE (10 areas); 3.6 million rows from 2015 | windows of half a year, split when the API answers "too large" | yes; G7 |
| neighbours `imbalance_price` | A85 of AT, DE_LU, FR; 1.8 million rows | same | yes |
| neighbours `ws_forecast` | A69 of 16 areas; 22.4 million rows | same; latest version only | later: G3 |

The download of the neighbours kept `answers_log.csv`: 607 answers "no data" or error. Without it,
a later run asks the same empty windows again (G7).

### 3.3 Other market sources

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| netztransparenz.de `aep_modules` | German imbalance price per quarter-hour and the module that set it, from 2022-06-22 | CSV export by hand in a browser (about a minute per year); the Web-API needs an account. Redistribution needs written consent | out: G8. It fits if a `fetch.py` uses the Web-API |
| netztransparenz.de `rebap` | the German settlement price per quarter-hour, from 2022-06-22 | same | out: G8. Same |
| netztransparenz.de `aep_module_counts` | number of quarter-hours per module | same; read only by QA | out: a check (D12) |
| Energy-Charts, CH spot prices | day-ahead, and hourly intraday (average, low, high, IDA1, IDA2), 2019 to 2026-10 | one JSON per country and year, no key | yes |
| Energy-Charts, DE spot prices | day-ahead, ID Full, ID3, ID1, low, high, IDA15; 68,616 hours from 2019 | same | yes |
| Energy-Charts API, DE-LU day-ahead | 38,548 quarter-hours from September 2025 (`api.energy-charts.info/price`), CC BY 4.0 (SMARD) | API, no key | yes |
| EPEX monthly report | monthly averages (December 2025) | read by hand | yes, as `checks.yaml` (done for the prices) |

The intraday prices are EPEX SPOT data that Energy-Charts shows: internal use, no redistribution
(SED `notes/swiss_intraday.md`, section 7).

### 3.4 PV production and capacity

Pronovo: directory listings, no login. Licence: private use with the source named; any other use
needs Pronovo's written consent. BFE: open use, the source must be named (the register; the terms
of the dashboard were not read).

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| `pronovo_15min` | measured production per technology (33), 15 minutes, 2020 to 2026-09; 7.6 million rows | a provisional zip per month (a median of 11 days after the month), a definitive zip per quarter; a file can be issued again | later: G3 (provisional --> definitive is a revision) |
| `pronovo_pv_canton_15min` | PV per canton, 6.6 million rows from 2023 | same | later: G3 |
| `pronovo_capacity` | capacity and number of units per canton and technology, per month from 2023-01 | same files | no: G2 (month) |
| BFE `pv_plants` | the register of plants: 337,455 PV plants, 8,829 MW, state of 2026-09-16 | one zip (19 MB) that BFE replaces now and then; retired plants disappear from it | no: G1; G3 to keep each state |
| BFE Energie Reporter (`er_pv_*`, `interim_pv_*`) | registered PV per municipality, station and zone; monthly states 2021-03 to 2026-09 | route not read in this pass (`data/bfe/README.md`) | no: G1, G2 (month) |
| BFE `pv_annual_official.csv` | official stock (MW), production (GWh), modules sold; 16 rows, 2010-2025 | typed from the statistics | out: G8 |
| BFE `edb_pv_estimate_hourly` | PV estimate of the energy dashboard per district (143) and hour, from 2026-07-12; 367,224 rows | API by month, no key | yes |
| BFE `edb_pv_forecast_hourly` | PV forecast of the dashboard per district; 1.3 million rows, 357 runs | the API keeps one run per target hour (the last), so the day-ahead run of 14:00 UTC is overwritten. A collector checks each hour and saves a new run once (not deployed on 2026-11-01) | yes, like weathernext3 (window on the run time, `revisions: none`); G4 |
| BFE `pv_capacity_*` | capacity per day, month, station, zone and cell | computed from the register | no: G11 |
| SolarEdge, the PV system of Renaud's house | production at 15 minutes; 1,155 daily CSVs | official API with a key (about 300 requests per day). The route that was used is a token copied from the browser, valid 24 h | yes with the official API |

### 3.5 Weather observations

MeteoSwiss: open data, CC BY 4.0, "Source: MeteoSwiss", no key. DWD: CC BY 4.0. EBAS: CC BY 4.0.
IGRA2 (NOAA): no licence stated. AERONET (NASA): cite the network and the investigators of the site.

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| MeteoSwiss `smn_radiation_hourly` | GHI, diffuse, sunshine, longwave at 135 stations from 2015; 13.7 million rows | per station, one "historical" file per decade and one "recent" file | yes. Before 2018 an hourly value covers [stamp - 20 min, stamp + 40 min) |
| MeteoSwiss `smn_regime_hourly` | temperature, humidity, pressure, wind, precipitation, snow depth, foehn index at 33 stations; 3.4 million rows | same | yes |
| MeteoSwiss `smn_tenmin` | GHI and sunshine per 10 minutes at 135 stations from 2023-10; 21.8 million rows | same | yes |
| MeteoSwiss `smn_daily` | daily values at 157 stations; the day is the UTC day | same | yes |
| MeteoSwiss `nime_daily` | fresh snow, snow depth, precipitation at 273 stations; the day runs from 06 UTC to 06 UTC | same | yes |
| MeteoSwiss `obs_daily` | visual observations at 20 stations (fog day, cloud cover); calendar date | same | no: G2 (local day) |
| MeteoSwiss lists of stations, parameters, inventory | 159, 181 and 19,554 rows | CSV | no: G1 |
| MeteoSwiss satellite grids (`sis`, `cfc`, `sisdif` per hour; `srel` per day) | 103 x 241 cells from 2004; one netCDF of about 74 MB per month and product | STAC | yes for an extract (the cells of the stations, blocks), as SGP did: 25 million rows. The full grid is out (G10): 4.8 billion rows per product |
| MeteoSwiss bulletins | 85 PDFs, 260 MB | by URL | out: G10. They are the source of the event tables (3.7) |
| IGRA2, radiosonde of Payerne | 13,237 soundings (most at 00 and 12 UTC), 1.7 million levels, derived parameters | one zip for the whole period (65 MB) that NOAA rewrites about daily | no: G6. Then yes, with `valid_at` |
| EBAS `aod_pfr_hourly`, `jfj_insitu_hourly` | optical depth at Davos and Jungfraujoch, in-situ aerosol at Jungfraujoch; 19,201 and 103,734 rows | netCDF files (route not read in this pass) | yes |
| AERONET `aeronet_aod_points`, `aeronet_sda_points` | optical depth at instants, 4 sites, levels 1.5 and 2.0; 402,135 and 398,899 rows | web service, text. The file of the current year changes between two fetches | yes, with `valid_at` and the level in the key; G3 |
| DWD `gwl_hb_daily` | Hess-Brezowsky weather type per day from 2010 | parsed from PDFs (one per month from 2016), issued a median of 33 days after the month, some issued again | no: G2 (calendar day); G3 |
| DWD `wlk_daily` | objective class of the 12 UTC analysis, 40 classes | one text file with the whole history | no: G6. Then yes, with `valid_at` |
| DWD `wlk_forecast` | the classes of the forecast per run day and lead (10 leads); 61,441 rows | one text file | yes (window on the run day, D14) |
| DWD `gwl_rea_daily` | objective catalogue from ERA5, 30 classes, from 1940 | one CSV per release (v1.6). The 30 classes fit in `categories` | no: G2 (calendar day) |
| Grams `regimes_grams_3h` | 7 Atlantic-European regimes every 3 hours; 48,232 rows | one zip per release on Zenodo; a new release has a new URL (a change of `fetch.py`) | yes |
| DWD `gwl_hb_monthly_counts` | the counts that DWD prints | | out: a check (D12) |

### 3.6 Weather forecasts

Open-Meteo: CC BY 4.0, no key. Free tier: 600 calls per minute, 5,000 per hour, 10,000 per day,
and a request counts for more than one call when it is large.

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| Open-Meteo Previous Runs (`nwp_runs`) | ECMWF IFS, ICON-EU, GFS: GHI and cloud at 79 stations, per lead day; 28.6 million rows from 2024-01 | one request per station | yes (the lead is a key column); G7 for the backfill |
| Open-Meteo Single Runs | one model run per request (ECMWF IFS from 2024-03, ICON-CH1 and CH2 from 2026-04): the only free day-ahead forecast of low cloud | backfill running since 2026-11-01 | yes (D14, D15); G7 |
| Open-Meteo ERA5 and CAMS | reanalysis (cloud layers, boundary layer, GHI), dust and optical depth, 79 stations | queued in the same backfill | yes; G7 |
| the Open-Meteo backfill as a whole | 105,000 calls: 11 to 12 days at 9,500 calls per 24 hours. A ledger holds the weight of every request | a script in Renaud's terminal | no: G7 |
| Open-Meteo `stations.csv`, `variables.csv` | the grid cell of each station (54 cells for 79 stations) | | no: G1 |
| WeatherNext 3 (Google DeepMind) | solar radiation and cloud cover over Switzerland | in adele since 2026-11-13. SGP also pulled more fields (126 for the explainer) | yes |
| ECMWF IFS ENS through dynamical.org | 51 members, 0.25 degree, every 3 hours, from 2024-04-01; CC BY 4.0 | Icechunk store on S3, no login. Only extracts at points were made | yes for an extract (run, lead and member in the key) |

### 3.7 Context tables, built by hand

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| `calendar_daily` | one row per local date 2009-2027: day type, share of the population on holiday, clock changes, bridge days | computed by a script | no: G2 (local day), G11 |
| `holidays_by_canton`, `holidays_summary` | 624 and 24 rows | from a PDF of SECO and from Wikipedia | out: G8 |
| `eclipses.csv` | 8 eclipses, for Bern and for Zurich (6 visible) | computed | no: G1 |
| `regime_breaks.csv` | 45 dated changes in balancing, markets, regulation and data, each with a URL and a quote | by hand | out: G8. The rows about one dataset belong in its descriptor (section 5, `breaks`) |
| `events_all.csv` | 220 grid events and weather episodes with start, end and quote, 2015 to 2026-09 | by hand, from the MeteoSwiss bulletins and ElCom reports | out: G8 |

### 3.8 Images

| dataset | what | how it arrives | fits? |
|---|---|---|---|
| Roundshot panoramas, Les Diablerets (4 cameras) | 147,893 JPEG, 34 GB, one image per 10 minutes by day, 2023-08 to 2026-10. Licence: none stated | one request per slot of 10 minutes. A slot without an image answers 404 after about 10 s, so two files hold the 47,373 slots already asked | out: G10. A table of the images (`valid_at`, path, sha256) would fit, the files not |
| cameras of the Cabane de Tracuit and Turtmann | samples, 16 MB | the north camera lists only its last 1,000 files, about 7 days | out: G10, G5 |

### 3.9 Copies, derived tables, and what is not a dataset

| dataset | what | fits? |
|---|---|---|
| Carlo Maino's cache (`swissgrid-2026/data/raw/`, 118 MB) | his downloads of Swissgrid, ENTSO-E (CH, DE_LU, FR, AT), Energy-Charts and the BFE register | out: the same sources as above |
| Carlo's database of webcams, Copernicus DEM | not on this machine | out: G10 |
| SGP `data/derived/` (34 files) | joins and features: `grid_*`, `pvsignal_*`, `daytypes_*`, `sky_*`, `nwperr_*`, `context_daily`, `pvmeas_*`, `weather_daily` (327 columns), `analysis_daily` (461 columns) | no: G11 |
| SED `tsi_proxy_15min` | a stand-in for TSI before Nov 2024, computed from the Energy Statistic | no: G11 |
| study folders of SGP (`pv_imbalance`, `imbalance_explorer`, `swissgrid_bids`, `da_id_spread_de`, `day_20260701`) | frozen inputs and outputs of studies | out: a study must keep the files that it read |
| exports for the course allocation (Moodle, Forms) | personal data | out |

Named in the two projects and never downloaded: GME (Italy), Elia open data, PVOutput, kk7, the PV
open data of St. Gallen and Winterthur, EnviDat, CKW smart meters, METAR, Cloudnet, OPERA radar,
MeteoSwiss CAP and GWT weather types (not open data).

### Counts

A second count, on files instead of datasets. SGP `data/catalog.csv` holds 85 tables of sources
(without logs, probes, QA outputs, derived tables and study folders). 41 have a timestamp below one
day, 14 a date, 5 a year, 3 a month, 4 a start and an end, and 18 have no time column. So about
half of the tables don't have the shape that D17 allows.

## 4. A SQLite file per dataset?

Renaud's idea (2026-11-14): each dataset gets its own SQLite file that keeps track of how much of
the data has been downloaded.

### What the two projects kept, and whether the stored Parquet can give it

| state | where the old projects kept it | can the Parquet give it? |
|---|---|---|
| what is stored: coverage, rows | recounted by a script (`catalog.csv`) | yes. adele computes it on each request |
| the last fetch, the status, the problems | logs | no. `state.json` today |
| every answer: URL, time, bytes, sha256 | a `provenance.csv` per source (4,754 rows for Open-Meteo, 4,116 for Swissgrid, 1,973 for ENTSO-E CH) | no |
| the answers that held no data | `answers_log.csv` of ENTSO-E (607), `missing_quarter.txt` of the webcams (47,373 slots) | no: an empty answer leaves no row |
| the budget of a rate limit | the ledger of Open-Meteo: the weight of every call of the last 24 hours | no |
| content already seen | a hash per file: the log of the poller, `snapshot_log.csv` of the BFE collector (saved, known, publishing) | partly: compare the rows, not the bytes |
| progress of a long backfill | one part file per window or per station | yes with `revisions: none` (D15), else no |
| the history of the fetches | logs | no: `state.json` keeps only the last fetch |

So there is state that the data can't give. It comes in two sizes. A few values per dataset (the
ETag of the last answer, the position of a backfill, the calls of the last 24 hours) fit in
`state.json`. A record of every request does not: the poller of today writes about 1,700 log lines
per day.

### What it costs to compute what is stored

Renaud's objection (2026-11-14): computing what is downloaded from the Parquet files may be very
expensive, because all of them must be read. Measured the same day on the Mac (duckdb 2.0.0, the
files in the cache of the system):

| table | files and rows | what is computed | time |
|---|---|---|---|
| `entsoe_day_ahead_prices.prices` (real) | 144 files, 371,910 rows | rows, first and last time (`table_stats`, run on each request) | 6 to 15 ms |
| `weathernext3.solar_radiation` (real sample) | 3 files, 628,992 rows | same | 1 to 2 ms |
| synthetic, shaped like `weathernext3.solar_radiation` at full scale | 120 day files, 201 million rows, 0.73 GB | same | 68 to 108 ms |
| same | same | the same numbers from the footers of the files only | 11 to 19 ms |
| same | same | every distinct run time (the check on gaps of D21) | 39 ms |
| same | same | the runs stored in the last 12 hours (D15), all files given | 12 to 14 ms |
| same | same | the same, only the 2 files that the window touches | 3 ms |

Every file is opened, but its data is not read. A Parquet file ends with a footer that holds, for
each column, the number of rows and the smallest and largest value. And each column is stored
apart from the others, so reading the time column doesn't read the values. The cost follows the
number of files (under 1 ms per file here), not the number of rows. Three years of day files
(1,095) come to about 1 s per table with today's code, and to about 0.1 s from the footers. Not
measured: a cold disk, and the disk of steacher1.

If it gets slow: the server is the only writer of these files. When it writes a file, it can
write one line about it (rows, first, last, the distinct values of the window column) into a
summary. That summary is a cache. It can be rebuilt from the files at any time, so it can't
contradict them for long.

### Three ways to remember between two fetches

| way | what it holds | what it covers | cost |
|---|---|---|---|
| nothing | | the sources where asking again is cheap (most of them) | none |
| a bookmark | a small JSON per dataset that `fetch` gets and returns changed. The server stores it in `state.json`, and only after the rows are merged | the ETag of the last answer (Swissgrid), the position of a backfill, the calls of the last 24 hours as 24 counts (Open-Meteo), a few hundred empty windows (ENTSO-E) | `fetch(start, end)` gets a third argument |
| a journal | one row per request, in SQLite or in Parquet | the above, and the record of every answer (URL, time, sha256), which goes with keeping the raw answers (G4) | a second store |

The poller of today is the second way: a `state.json` with 18 entries, and a log file per month
beside it. It has asked every minute since 2026-09-27.

### Decision and recommendation (2026-11-14)

Decided by Renaud: no SQLite file and no journal.

Between nothing and a bookmark: nothing for now (D23). A bookmark comes when the first dataset
needs one.

A subagent then looked for a dataset that needs memory (2026-11-14: from the code, the notes of
the two projects and the poller's log; no request to a source). Among the 83 datasets it found no
API with a cursor, no source that serves only what changed since the last call, and no recorded
limit that is exceeded at the `every` that the source needs. Its numbers:

| case | measured | consequence |
|---|---|---|
| Swissgrid's TSI | an answer is 120 bytes (median of about 2,300 downloads). An earlier version of this section said 0.4 KB | every minute without an ETag: 0.17 MB a day. No memory needed |
| Swissgrid's year files | control-area-balance: 0.7 to 4.6 MB. EnergieUebersichtCH: 18.2 MB (2026), 26.4 MB (2025). The poller asked the file of 2026 every hour: 360 of 469 answers were "not modified", 1.1 GB saved in 20 days | once a day without memory is fine. More often needs a conditional request |
| MeteoSwiss SMN, the "recent" files | one fetch of all of them is 851 MB; the source rewrites them twice a day | once a day is fine. Every hour would move 20 GB a day |
| Open-Meteo, `nwp_runs` with all tiers | about 569 calls per fetch (estimated): 13,650 a day at PT1H, against a limit of 10,000 | fine at P1D. The budget belongs to the source: the old backfill shared one ledger between two scripts, so a bookmark per dataset can't enforce it |
| the poller as a whole | 35,292 requests in 20.1 days; 84.9 % were answered "not modified" | conditional requests pay when a file is asked far more often than it changes |

So three cases will need a bookmark or a conditional request when they come: the year files and
the "recent" files of MeteoSwiss if they are asked more often than once a day, and the Open-Meteo
backfill. A possible first step, smaller than a bookmark: the server gives `fetch` the time of
the last successful fetch, which it already holds, and `fetch` sends it as If-Modified-Since.

The same check found three defects in the server that memory would not solve (TODOs.md):

- A hole older than the lookback was never fetched again: the window was always
  [now - lookback, now + horizon). A long backfill left such a hole between its end and the
  first scheduled fetch (weathernext3: a lookback of 12 h, a backfill of days). Fixed on
  2026-11-15 (D25): a scheduled run starts at the last run that succeeded.
- A backfill doesn't resume. `--start` is required and a second run fetches every window again.
  A window that failed in the middle leaves a hole, and the status ends "ok".
- With `revisions: none`, a run that is stored in part counts as stored and is never completed.
  weathernext3 has a `success` marker per run; a source that publishes a run over several
  minutes (the BFE dashboard) has none.

### If a journal is built

The first recommendation (2026-11-14) was one SQLite file per dataset as a journal: what was
asked, when, and what came back. The recommendation above replaces it. Its five rules still hold
for a journal:

1. **It records events, never holdings.** What is stored stays computed from the Parquet files.
   Then the journal and the data can't contradict each other after a restored backup, a deleted
   partition or a repartition.
2. **Only the server writes it.** `fetch.py` reports its requests to the server, e.g. as one more
   table next to the data tables (`_requests`: URL without token, time, status, bytes, sha256,
   weight, outcome). "A connector never writes files" still holds.
3. **It sits outside the folder that queries of agents may read.** Tested on 2026-11-14 with
   adele's engine (duckdb 2.0.0) on `data_nosync/`: a query reads any file under `data_dir` with
   `read_json`, `read_text` or `read_blob`. It read `state.json`, and `logs/queries.jsonl`: the SQL
   of every team member, with the member's name. It can't parse a SQLite file (the extension is not
   loaded), but it reads its bytes. So the journal and the logs belong outside `data_dir`, or
   `allowed_directories` is narrowed to the folders of the tables.
4. **`state.json` stays the summary that the HTTP process reads.** That process can't write
   (D10). Tested with sqlite 3.53.1: a reader without write permission opens a SQLite file in the
   default journal mode. In WAL mode, once the writer has closed, the same reader fails ("attempt
   to write a readonly database"). So: the default mode, and the HTTP process doesn't open the
   file at all.
5. **Build it with the first dataset that needs it** (the first one whose raw answers are kept,
   G4), not before. The two datasets of today don't need it.

Two tables are enough to start:

    fetches(id, started_at, ended_at, window_start, window_end, outcome, rows_fetched, rows_changed, error)
    requests(fetch_id, at, url, status, outcome, bytes, sha256, weight, raw_file)

`outcome` of a request is `data`, `empty` or `error`. `raw_file` is the place of the kept answer
(G4). With these, the server can enforce a budget of calls across runs, skip a slot that is known
to be empty, and show the history of a dataset.

Details: name the file `journal.sqlite`, not `adele.db` (next to DuckDB, `.db` reads as a DuckDB
file). Back it up with `VACUUM INTO` or `.backup`, not with a copy during a write.

### Other containers for a journal

- **Everything in `state.json`.** The file is rewritten whole at each fetch. Fine for one summary,
  not for 315,000 rows.
- **Append to JSON lines.** Simple, but each lookup ("was this slot asked before?") reads the whole
  file.
- **The journal as Parquet tables of the dataset** (`<id>._fetches`, `<id>._requests`), written by
  the merge code that exists. No new store, and agents could query provenance with `adele query`.
  Against it: each fetch rewrites a file to add a few rows. This is the closest alternative.
  Choose it if agents should read the journal.
- **One SQLite file for the server.** Questions across datasets get simpler, but D18 treats a
  dataset as a unit, and all fetches would then write to one file.

## 5. What to add to `datapackage.yaml`

Ranked by the number of datasets of section 3 that need each item. The sketches show the keys; the
values are illustrations, not definitions (the definitions are Renaud's).

### Standard properties that adele doesn't use yet

1. **`foreignKeys`** (Table Schema), with G1. A table of measurements points to its table of
   stations, of zones, of districts or of plants. The server checks after each fetch that every
   code exists in the other table. It replaces `categories` when the list is long (135 stations)
   or when a code has attributes (latitude, altitude, valid from).
2. **`constraints`** per field (`minimum`, `maximum`, `required`, `enum`). Ranges and signs that the
   server checks after each fetch: aFRR+ >= 0, a cloud cover between 0 and 1. SED had these
   checks in `sedlib/contract.py`.
3. **`sources`** at package level: the publisher and the page. Today the publisher is only in the
   title.
4. **`keywords`**: the classes of a dataset (grid, pv, weather, market). For `adele list` and for
   search.

### New keys

5. **Tables without a time column** (G1). No key: a change of D17. A table has `delivery_start`,
   or `valid_at`, or no time column. A table without one is stored as one file and replaced whole
   at each fetch. Decided: D22.
6. **An `adele:` block per table**, for `resolution` and `partition` (G2). Today `adele.resolution`
   is at package level, and weathernext3 already needs a comment to say which table it means.
   Pronovo has a table at 15 minutes and a table per month.
7. **Calendar periods** (G2a): a day, a month or a year of a time zone. Three ways, compared
   below under "Calendar periods: three ways". Decided by Renaud on 2026-11-14: way C, a date
   column, with the zone in the catalog.
8. **`adele.breaks`**: dated changes of a series. `{date, tables, text, source}`. The inventory holds
   more of them than of any other trap: the Swiss PV forecast changes scale on 2023-12-31,
   2025-04-01 and 2026-04-25; the sign of Austria's imbalance flips on 2024-12-01; France goes
   from 30 to 15 minutes on 2024-12-30; the Energy Statistic stamps the end of the interval until
   2024. Today they are sentences in `adele.warnings`. With a date, `describe` can sort them, and
   the server can check that the date is inside the coverage.
9. **`adele.known_gaps`**: `{from, to, where, text}`. Gaps that are accepted: Italy's imbalance volume
   from 2018-07 to 2021-12, a forecast run that the source never published. The check on gaps
   (D21) skips them and `describe` prints them. This answers the question that D21 leaves open.
10. **`adele.irreplaceable: true`** (G4, G5): the source keeps no history. The server then keeps
    each raw answer, alerts at the first failed fetch, and refuses `revisions: overwrite`.
11. **`lookback: all`** (G6): each fetch returns the whole table and the server compares all of
    it. (`refresh: manual` is dropped: delivery by hand is a non-goal.)
12. **`sign` and `nulls` per field**, next to `unit`. `sign: "> 0 = control area long"`. `nulls:`
    what a null means ("not published", never zero). Not `null:`, which YAML reads as an empty
    key. They are prose, like `unit`, but `describe` prints them in a fixed place.

These keys change what a server must understand, so they make `adele.format_version: 2` (D19).

### Calendar periods: three ways

The example is the local day 2026-03-29 in Europe/Zurich. The clocks go forward, so it has 23
hours: it starts at 2026-03-28 23:00 UTC and ends at 2026-03-29 22:00 UTC. A table of quarter-hours
holds 92 rows for it. Tested with duckdb 2.0.0 and `TimeZone = 'UTC'`, as adele's engine sets it.

| way | what a row stores | quarter-hours joined to that day | what goes wrong |
|---|---|---|---|
| A. The start, and the zone in the catalog | `delivery_start` = 2026-03-28 23:00 UTC. The catalog says P1D in Europe/Zurich | 96 with `delivery_start + INTERVAL 1 DAY`: 4 quarter-hours are counted in two days. 92 only when the query computes the end in the zone | the reader computes the end. `epoch(INTERVAL 1 MONTH)` gives 30 days, so a weight by duration is wrong for months. And the filter by date of way B |
| B. The start and the end | `delivery_start`, and `delivery_end` = 2026-03-29 22:00 UTC | 92 | a filter by date reads the wrong day: `delivery_start >= '2026-03-29' AND delivery_start < '2026-03-30'` returns the row of 2026-03-30, which starts at 2026-03-29 22:00 UTC |
| C. A date | `delivery_date` = 2026-03-29, of type date. The catalog says Europe/Zurich | 92, with `CAST(q.delivery_start AT TIME ZONE 'Europe/Zurich' AS DATE) = d.delivery_date` | the join needs the zone: a cast without it moves 1 to 2 hours of each day to the next day. The server's window and partitions work on timestamps today |

A fourth way stores all three columns: `delivery_start`, `delivery_end` and `delivery_date`. A filter
by date uses the date, a join uses the start and the end, and neither needs the zone. It costs
two more columns, and D17 ("exactly one time field") changes.

Way B is also the only one for a period with its own end (G2b: an outage, an event, a tender
product).

Claude's recommendation was the fourth way for calendar periods, and way B for periods with
their own end. SGP used way C (`date` = local date). **Decided by Renaud on 2026-11-14: way C.**
Periods with their own end wait for the first dataset that needs them (ENTSO-E outages,
Swissgrid's reserve auctions).

### Way C, checked against the code and the datasets (2026-11-14)

Three details were proposed for way C: the column is named `delivery_date`, a month and a year
are stored as their first day, and the zone sits next to the resolution. A subagent tested them
against the server code, the datasets marked G2 and duckdb 2.0.0 (synthetic data, one run per
timing). Its findings change the proposal. They are open until Renaud answers.

1. **One name for three periods gives wrong results without an error.** A join of a table by day
   with a table by month, `USING (zone, delivery_date)`, returns 12 rows for 2026 and not 365: it
   matches only the first day of each month. Proposal: `delivery_date` for a day,
   `delivery_month` for a month, `delivery_year` for a year, all of type date. The same join then
   fails with an error. It is the reason of D17: one name per meaning.
2. **`P1M` and `P1Y` are refused by the catalog**, on purpose (`catalog.py`, `parse_duration`:
   their length varies), and `PT1M` is one minute. With a name per period, the name gives the
   resolution, so such a table needs no `resolution`.
3. **One zone per table**, as a key of its own (`timezone: Europe/Zurich`), not inside each
   period of `resolution`. An IANA name or `UTC`. Not `CET`: DuckDB applies summer time to it.
   3 of the 4 tables by day of the inventory don't state their zone (`obs_daily`, `gwl_hb_daily`,
   `gwl_rea_daily`). Decided by Renaud on 2026-11-14 for such a table: the author writes the
   most likely zone, and the description of the column says that the source does not state it
   ("write it down, so this is known").
4. **A prerequisite.** `resolution`, `window` and `partition` are per dataset today
   (`catalog.py`). A dataset with a table by quarter-hour and a table by month (Pronovo) can't
   load. The `adele:` block per table (item 6 above) comes first.
5. **The window of a fetch.** `_stage` keeps a date only when its UTC midnight falls in
   [start, end). Tested: a table by month with a lookback of 3 days keeps 0 rows, and the status
   stays ok. Rule: a period is kept when it overlaps the window.
6. **A state at a date is not a period.** The BFE Energie Reporter gives the capacity on the last
   day of each month. Stored as the first day, the state moves 30 days back. It needs a date form
   of `valid_at`, when that dataset comes.
7. **The join**, tested on the two days of the time change (92 and 100 quarter-hours):
   `date_trunc('day', q.delivery_start AT TIME ZONE 'Europe/Zurich') = d.delivery_date`, and
   `'month'` or `'year'` for the two other periods. A cast without the zone gives 96 on every
   day, without an error: 2,300 of the 35,040 quarter-hours of 2026 go to the wrong day. The
   correct form reads every row group of the table by quarter-hour (351 ms on 20.5 million rows).
   With a plain filter on `q.delivery_start` next to it (the period, padded by a day) it read 15
   row groups of 176 (54 ms). `describe` should print both.
8. **The 9 datasets marked G2.** Handled: installed capacity (year), Pronovo capacity (month) and
   4 tables by day. Not handled: the Energie Reporter (finding 6), ENTSO-E outages (own end), the
   reserve auctions (a week, a day or a block of 4 hours). No quarter, season, hydrological year
   or gas day among them.
9. **Elsewhere.** A DuckDB on a laptop uses the zone of the machine: the cast without a zone
   gives 92 there and 96 on the server, which matters for a local copy. And
   `skills/adele/SKILL.md` weights by `epoch(resolution)`, which gives 720 hours for every month.

A UTC day is a fixed duration (24 h): such a table keeps `delivery_start` and `P1D`, as
`smn_daily` does.

### Sketch

```yaml
name: meteoswiss_smn
title: SwissMetNet station measurements (MeteoSwiss)
sources:                                    # 3
  - {title: "MeteoSwiss, open data", path: https://opendatadocs.meteoswiss.ch/}
keywords: [weather, observation]            # 4
resources:
  - name: stations                          # 5: no time column, replaced whole at each fetch
    schema:
      primaryKey: [station]
      fields:
        - {name: station, type: string, description: Abbreviation of the station (PAY = Payerne).}
        - {name: lat, type: number, unit: degree_north}
        - {name: altitude, type: number, unit: m}
  - name: radiation_hourly
    adele:                                  # 6
      resolution:
        - {from: 2015-01-01, value: PT1H}
    schema:
      primaryKey: [station, delivery_start]
      foreignKeys:                          # 1
        - {fields: [station], reference: {resource: stations, fields: [station]}}
      fields:
        - {name: station, type: string}
        - {name: delivery_start, type: datetime}
        - name: ghi
          type: number
          unit: W/m2
          nulls: The station did not measure in this hour. Never zero.   # 12
          constraints: {minimum: 0, maximum: 1500}                       # 2
  - name: observations_daily                # 7: its time column is `delivery_date`, of type date
    adele:
      timezone: Europe/Zurich               # one zone per table; the name of the column gives the period
    schema: ...
adele:
  format_version: 2
  refresh: {every: PT1H, lookback: P30D, horizon: PT0S}
  revisions: overwrite
  breaks:                                   # 8
    - date: 2018-01-01
      tables: [radiation_hourly]
      text: Before this date an hourly value covers [stamp - 20 min, stamp + 40 min).
  known_gaps:                               # 9
    - {from: YYYY-MM-DD, to: YYYY-MM-DD, where: "station = 'BLA'", text: Blatten has no radiation for 355 days.}
```

A source that overwrites itself, and a year file revised in place:

```yaml
adele:
  irreplaceable: true                                         # 10
  refresh: {every: PT1M, lookback: PT30M, horizon: PT0S}
  revisions: append-only
---
adele:
  refresh: {every: P1D, lookback: all, horizon: PT0S}         # 11
```

### What should not go in the descriptor

- The state of the download (section 4): it changes at each fetch, and the descriptor is in git.
- Who may read a dataset, if that is ever needed: config of the server. Rules of use are not a
  concern so far (G9). The descriptor gives the licence (`licenses`), and a warning marked for the
  footer (D20) can say "internal use" where an agent reads it.

### Later, when a dataset asks for it

- `delivery_end` for periods with their own end (G2b: outages, events, tender products).
- `adele.rate_limit` (`{calls: 9500, per: P1D}`): needs the journal.
- `adele.available_after` (weathernext3: a run is readable about 7 h after its start), for `as_of`.
- Derived tables as SQL views over other datasets (G11).

## 6. Decisions

Taken by Renaud on 2026-11-14:

- G1: adele supports tables without a time column, and a row that the source drops goes (D22).
- G2: calendar periods get a date column (way C of section 5), named after its period:
  `delivery_date`, `delivery_month` or `delivery_year`, with one `timezone` per table and no
  `resolution` (D26, 2026-11-15). When the source does not state the zone of its days, the
  author writes the most likely zone and says in the description of the column that it is
  assumed.
- G3: fine with POC 2.
- G5: adele must support a source where a missed fetch is lost (Swissgrid's TSI). The fetches
  keep the sandbox settings of the systemd unit ("I insist on sandbox settings"), so a plain cron
  line is out. One systemd timer and service per dataset (2026-11-15).
- Swissgrid: the 5-minute TSI file and the daily balance file are two datasets, each with its
  own `fetch.py` and refresh (2026-11-15; rows `total_system_imbalance` and
  `control_area_balance_daily` of section 3.1). The daily one has a margin of 24 hours, so a
  missed version of the 5-minute file costs detail, not the quarter-hour.
- G7: no journal, no SQLite file, and nothing between two fetches for now (D23).
- G8: a non-goal (SPEC.md, Non-goals).
- G9: not a concern so far.
- G10: a non-goal (SPEC.md, Non-goals).
- G11: derived tables stay out for now.

Open:

1. G2: decided (D26), not built. Its prerequisite is the `adele:` block per table. Still open:
   a period with its own end, and a state at a date (the BFE Energie Reporter).
2. G5: how fetches of different datasets run side by side, with the sandbox settings kept.
   Investigated on 2026-11-15 with prototypes on the Mac (TODOs.md, `deploy/scheduling-poc/`):
   one systemd timer and service per dataset is the recommendation, a scheduler that stays
   running has the best numbers but a restart stops every fetch in progress. Nothing was tested
   on systemd yet. And the changes in the server (section 2, TODOs.md).
3. Two of the three defects that the check of G7 found (section 4): a backfill that doesn't
   resume, a run stored in part. The third, a hole older than the lookback, is fixed (D25).
4. G4: raw answers kept, with the Swissgrid files. Does adele take over the poller, or does the
   poller stay and adele reads its archive?
5. Queries and files (D24, built on 2026-11-14). A query reads only the folders of the tables, no
   longer the query log and the state files. Found the same day and closed: a query could write
   a file inside the folder of a table (`EXPLAIN ANALYZE COPY ... TO`, a COPY in a CTE, three
   table functions), so it could add or replace a partition. Since 2026-11-15 a query is one
   SELECT and nothing else, also no EXPLAIN (D29).
6. G6: `lookback: all`.
