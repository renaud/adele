# WP5.5: Pronovo

Built by Claude on 2026-11-15 and 2026-11-16 in the worktree `wp5.5`, at Renaud's request ("build
WP5.5", then "also include published figures", then "search the web for documents that we could
use as QA tests"). The sub-package is defined in `docs/work-packages/WP5-datasets.md` (three
datasets). The measurements behind each choice are in the docstring of
`datasets/pronovo_production/fetch.py`; the published figures in
`qa/published_figures_pronovo_production.md`.

## What was built

One dataset, `pronovo_production`, `revisions: append-only`, refreshed daily with a lookback of
400 days:

| table | what | rows (backfill on the Mac) |
|---|---|---|
| `by_technology` | national production per technology and quarter-hour: `production_mwh` (-A), `production_mw`, `auxiliary_mwh` (+A), `version`, `suspect` | 3,485,968, 2020-01 to 2026-10 |
| `pv_by_canton` | PV per canton and quarter-hour | 3,491,520, 2023-01 to 2026-10 |
| `capacity_by_technology` | capacity (`capacity_mva` until the files of 2025, `capacity_mw` from 2026) and `units` per technology, at the end of each local month (`delivery_month`, Europe/Zurich) | 789, 2023-01 to 2026-10 |
| `pv_capacity_by_canton` | the same for PV per canton | 1,196 |

The descriptor validates; a second fetch of the same window stores nothing; a scheduled run (400
days) takes about a minute; 168 checks pass (156 of them BFE's monthly volumes of its reference
market prices, computed from the same files); 11 tests on synthetic files
(`server/tests/test_pronovo_fetch.py`). Every definition is a draft by Claude. Not yet on
the server (WP1's week, then WP3 there).

## What Claude chose

1. **One dataset with four tables**, not three datasets (open question 5 of the WP5 doc): one
   download serves every table, and all of them have the same revision policy.
2. **National and cantons in separate tables**, for the production and for the capacity: a
   national total next to the cantons would be summed twice.
3. **Which file gives a month:** per local month and per CSV (the national one, or a canton), the
   definitive file when it covers the whole month, else the file with more quarter-hours. The
   provisional zip is downloaded only when needed. A backfill stores the best file of that day,
   so the provisional values from before the first scheduled fetch are not in adele (they stay in
   Pronovo's archive and in the swissgrid project).
4. **2020-2022 from the monthly CSVs of Pronovo's archive**, `version = archive`: their values
   equal the annual xlsx in every common quarter-hour, and they hold the 1,093 quarter-hours of
   March 2021 that the xlsx lacks. The xlsx is not read.
5. **Energy and power:** `production_mwh` (summable) and `production_mw`, rounded to 7 decimals
   (the files give at most 4 decimals of kWh).
6. **Two columns of capacity**, one unit each: kVA in the files up to 2025, kW from 2026.
7. **`suspect`** marks known bad values, kept as published: two single spikes of 2022, PV doubled
   on 1-7 Aug 2021, the national PV of Sep 2024, and the nuclear of Sep 2024 and Feb-Mar 2025
   (one unit missing from the file, found with BFE's monthly balance).
8. **`fetch.py` fails on purpose** on an unknown name of technology, of CSV or of unit, on a local
   stamp that isn't the UTC stamp, and on a month older than 40 days without any file.
9. **No `adele.raw: keep` (D33):** Pronovo keeps every file in its archive, so a missed answer can
   be fetched again, and `append-only` keeps each version of a row.
10. **A server bug fixed rather than worked around** (below): `fetch.py` first returned an empty
    table by month with an Arrow date type (and declared pyarrow); after the fix of 2026-11-16 it
    returns plain pandas columns.

## Findings

- **BFE's reference market prices are computed from these files** (method note, section 3.3):
  monthly volumes of PV, wind, hydro (five categories) and biomass (five), as -A minus +A. All
  156 volumes of 2023-07 to 2026-09 match within 0.5 MWh. BFE's older quarterly PV volumes
  (2018 to 2023/2, -A alone) match for 2022/3, 2023/1 and 2023/2; the 11 other quarters of
  2020-2022 differ by -3.9 to +0.6 % (unexplained).
- **A nuclear unit is missing from the files of Sep 2024, Feb 2025 and Mar 2025:** capacity 1,980
  instead of 3,015 MW, energy 0.66 of BFE's monthly nuclear, against 1.000 to 1.014 in every other
  month. In Sep 2025 the file lists 1,980 MW too, but the energy matches (the unit was off).
  This answers an open question of the swissgrid project (an outage, or a unit missing?).
- **Hydro lacks plants in the same months**, and in Sep 2025: 0.59 to 0.68 of BFE's hydro, against
  0.76 to 0.94 otherwise.
- **Pronovo's -A for nuclear equals BFE's net production**, although Pronovo calls its profiles
  gross production.
- **Pronovo's hydro files by size class** (from 2026-08) break down the same meter data: three
  hydro types match the definitive September 2026 to the kWh; they list more plants.
- **Server bug, fixed on 2026-11-16 at Renaud's request:** `server/src/adele_server/ingest.py`,
  `_window_filter`: when a fetch returned no row for a table by month or day, DuckDB typed the
  empty date column as NULL, and `NULL + INTERVAL 1 MONTH` failed the fetch (the first backfill
  of 2020-2022, which has no capacity, failed so). The column is now cast to DATE first; test
  `test_an_answer_without_periods_stores_nothing_and_succeeds` in `server/tests/test_table_shapes.py`.

## Open

1. Renaud: the definitions (all drafts), and the choices above, in particular 1, 3, 4 and 7.
2. Renaud's own documents with figures from Pronovo (skills/add-dataset, step 8), if any.
3. Pronovo's raw data of issued guarantees of origin (2024, 2025): larger than WebFetch can load;
   a download script in the main session, then a comparison (another set of plants: net, every
   registered plant).
4. Backfill on the server after WP1's week and WP3 there, and `review-dataset` before publishing.
