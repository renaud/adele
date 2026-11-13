# What adele keeps from `swiss_energy_data`

Status: harvest of 2026-11-13, before Renaud drops the project (DECISIONS.md, D11). SED below =
`/Users/ren/switchdrive/backup/_EnTr/projects/swiss_energy_data/`. Read by a research agent; the
blockers were checked by hand the same day. Paths are relative to SED unless they say otherwise.

## Before deleting SED (blockers)

- SED's git repository has no commit (checked: "does not have any commits yet"). Its code exists
  only on disk. Commit it once, or archive the folder, before deleting.
- 22 scripts outside SED read SED paths (checked by grep): 16 in `swissgrid_project/code/`
  (e.g. `pv_imbalance/load_tsi.py`, `datasets/derive_grid.py`, `imbalance_explorer/build.py`)
  and 6 in `11_replication_intraday-orderbook-to-imbalance-Pinson-Jalal/code/` (`01_target.py`
  ... `02_de_modules.py`). Deleting SED breaks them until adele serves the same data.
- The netztransparenz downloads (`store/raw/de_netztransparenz/`, 8.5 MB) exist nowhere else.
  They can be downloaded again by hand, about a minute per year (`sources/de_netztransparenz/README.md`).
- Copies exist elsewhere for the Phase 3 poller archive
  (`_EnTr/class_/Pinson.../PhaseThreeSwissgridImbalance/data/`, 1.3 GB) and the annual-report CSV
  (`swissgrid_project/lit_search/G_swissgrid_financials/tables/long.csv`).

## 1. Mechanisms adele lacks

1. **Raw files with provenance** (`sedlib/raw.py`, ARCHITECTURE.md D2, D11). Each file is kept
   byte for byte as received, with one row of provenance: file, url, retrieved_utc, bytes,
   sha256. Sources that overwrite themselves (Swissgrid daily balance, 5-minute TSI, 1-second
   aFRR) can only be recovered this way. adele keeps only normalized Parquet.
   --> SPEC.md Storage; a TODO before any Swissgrid dataset.
2. **Knowledge time** (ARCHITECTURE.md section 4). Separate columns `issued_at` (model run),
   `published_at` (the source's stamp) and `retrieved_at`. A new version is stored only when a
   value changes; a null row marks a key that disappeared from a source that delivers full
   files. ENTSO-E's `doc_created` is not a publication time. --> POC 2 (`append-only`, `as_of`);
   also WN3 (init_time + latency).
3. **`_asof` macro** (`sedlib/serve.py`): latest version with `retrieved_at <= ts` per key.
   Backfilled rows carry the backfill time, so "a value may look later than it was, never
   earlier". --> TODOs V1, the item on `as_of` before the first fetch.
4. **Embargo** (`embargo.yaml`, `sedlib/embargo.py`, section 7). The blind test of the
   swissgrid project reserves dates from 2026-10-16. Columns are classed grid / pv_weather /
   free by name; an unclassified column counts as both. `stored_to` against `served_to` makes
   the cut visible. --> needed before adele serves Swissgrid or PV data to the swissgrid
   project: an access rule per key or per dataset (SPEC.md, new section).
5. **A gate tied to the bytes** (`sedlib/gate.py`, D6). A build waits until it passes; a view is
   in `main` only if its file's sha256 has a passing row in `qa_runs.parquet`, else it sits in
   `unverified`. adele merges first and then sets the status to failing, so failing data stays
   queryable. --> a decision to make (DECISIONS.md).
6. **Checks adele doesn't run** (`sedlib/contract.py`): largest gap on the time grid, 92/100
   quarter-hours on clock-change days, ranges, signs. --> `server/src/adele_server/checks.py`,
   through Table Schema `constraints`. Also named tests declared before the run, and checks
   between sources (`sources/*/qa.py`). --> skill `review-dataset`.
7. **Column keys**: `sign`, `null` (what a null means), `stamp_check` (how the timestamp
   convention was proved). --> SPEC.md, Keys.
8. **Licence as a rule of use**: Energy-Charts (personal use only), EPEX (internal only) and
   netztransparenz (written consent) must not be redistributed. A server for a team counts as
   distribution. --> SPEC.md, Catalog; `notes/swiss_intraday.md` section 7.
9. **Dated breaks** (`catalog.breaks`, 45 rows with URL and quote;
   `swissgrid_project/data/calendar/regime_breaks.csv`), QA levels (received < structural <
   plausible < consistent < reconciled) and licence classes (open, cite, none-stated,
   restricted). --> the `adele:` block.

## 2. Source facts for `skills/common-traps.md` and later datasets

- ENTSO-E A16 load is stamped 1 h later than Swissgrid's Energy Statistic in 2015-2024, and no
  shift fits 2017, 2018 and 2023 (`sources/ch_swissgrid/README.md`, "Time stamps" point 5).
  Matters for POC 2.
- ENTSO-E A85 CH includes a scarcity add-on of 10 EUR/MWh x (|TSI| - 1000) that Swissgrid's
  files leave out (2026-07-01). ENTSO-E has no German imbalance price after 2022-06-21.
- The ENTSO-E series A69 for `pv_da` also holds wind.
- One series can change its timestamp convention: the Energy Statistic stamps the end of the
  interval until 2024 and the start from 2025; files of 2009-2020 mislabel one fall-back row
  per year.
- Wrong units in the source: prices in ct/kWh (x 10 --> EUR/MWh), energy in kWh per
  quarter-hour (/ 250 --> MW), a header "[EUR]" over kEUR, cumulative costs that restart every
  Monday.
- Swissgrid revised prices up to 7 weeks after delivery (one went from 107 to -122.5 EUR/MWh).
  Recent rows with blank components are placeholders.
- netztransparenz: "Module 3 = 0.00" is not a price (15,428 rows, until 2023-10-04).
- Energy-Charts: the intraday average is known only after delivery; gap 2020-10-12 to
  2020-12-31.

## 3. Later datasets already worked out

- Swissgrid, 10 datasets with URLs, file names, German headers, units and signs:
  `sources/ch_swissgrid/source.yaml` and README.md.
- netztransparenz AEP modules and reBAP: `sources/de_netztransparenz/` (manual download; the
  Web-API needs an account).
- Energy-Charts JSON `price_spot_market/data/<cc>/year_<y>.json`: `sources/eu_energy_charts/`.
- Not worked out in SED: ENTSO-E beyond prices, Pronovo, BFE, MeteoSwiss, Open-Meteo, AERONET.
  Known flags (MeteoSwiss `reference_timestamp` and BFE `datetime_api` unverified; Pronovo
  provisional against definitive) are in `MIGRATION.md` and ARCHITECTURE.md section 2.

## 4. Reference figures not in `qa/published_figures.md`

- EPEX December 2025, CH intraday: ID Full 112.89, ID3 112.72, ID1 112.56. CH continuous volume
  818.6 / 1,143.7 GWh (2024 / 2025), auctions 43.9 / 59.8 GWh (`notes/swiss_intraday.md`
  sections 2 and 4).
- Yu et al.: DE 2024 extreme imbalance-price counts 115 and 24; AEP module shares 2024/2025
  (`sources/de_netztransparenz/README.md`).
- Swissgrid annual reports 2011-2025: 16,491 values with page and quote (control energy,
  import, export, transit in GWh): `store/reference/swissgrid_annual_reports_2011-2025.csv`.
- IGCC netting avoids about 35 GWh/month (Swissgrid factsheet). DNV 2026 p. 59: scarcity
  thresholds 1,000 MW long, 1,200 MW short.

## 5. Code worth porting

- `sedlib/contract.py`, `check_table` (gaps, clock-change days, ranges)
- `sedlib/serve.py` (`_asof` macro, embargo cut, freshness and `stale`)
- `sedlib/raw.py` (`pack` with sha256 read-back, provenance)
- `sedlib/gate.py` (`qa_runs`)
- `sources/ch_swissgrid/build.py`: `local_to_utc`, `eu_year`, `parse_price_xml`,
  `parse_price_xlsx`, `eur_mwh`, `step_activation`
- `sources/ch_swissgrid/qa.py` (differences between versions)
- the parsers in `sources/de_netztransparenz/build.py` and `sources/eu_energy_charts/build.py`,
  which stop on an unknown series or zone
