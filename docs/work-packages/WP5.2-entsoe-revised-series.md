# WP5.2: the ENTSO-E series that are revised

Built 2026-11-15 by Claude in the worktree `wp5.2`, at Renaud's request ("build WP5.2"), from
the sub-package WP5.2 of `docs/work-packages/WP5-datasets.md`. Renaud chose `append-only` for
the physical flows and the scheduled exchanges too (his answer to open question 1 of that file,
2026-11-15), so all four datasets are built. On the Mac only: the server runs WP1's week until
2026-11-22.

## What exists

| dataset | tables (key) | rows | from | refresh | checks |
|---|---|---|---|---|---|
| `entsoe_generation` (A75) | `generation` (bidding_zone, production_type, delivery_start) | 610,647 | 2015-01-01 | every PT1H, lookback P100D | 40 |
| `entsoe_physical_flows` (A11) | `flows` (border, delivery_start) | 554,704 | 2015-01-01 | every PT3H, lookback P400D | 19 |
| `entsoe_scheduled_exchanges` (A09) | `day_ahead`, `total` (border, delivery_start) | 439,329 and 560,313 | 2018-02-27 and 2015-01-01 | every PT1H, lookback P31D, horizon P2D | 9 |
| `entsoe_imbalance_volume` (A86) | `imbalance` (control_area, delivery_start) | 407,708 | 2015-03-25 | every PT1H, lookback P430D | none found |

All four are `revisions: append-only`, format version 1, with the token of the other ENTSO-E
datasets. Each has its `datapackage.yaml` (every definition marked `# draft by Claude`), its
`fetch.py` (the measurements in its docstring) and, except the imbalance, its `checks.yaml`.
Tests on synthetic answers: `server/tests/test_entsoe_wp52_fetch.py` (20). The whole suite: 371
passed. Data on the Mac: `data_nosync/` of the worktree, 17 MB.

## Choices made during the build (Renaud: confirm or change)

1. **Ids and tables**: `entsoe_generation.generation`, `entsoe_physical_flows.flows`,
   `entsoe_scheduled_exchanges.day_ahead` and `.total`, `entsoe_imbalance_volume.imbalance`,
   after `entsoe_load`.
2. **The German border is the country DE** (10Y1001A1001A83F) over the whole span, and DE_LU is
   not fetched. Flows: DE and DE_LU differ in 2025 (24,782 of 35,040 quarter-hours) and
   Swissgrid's Energy Statistic agrees with DE. Schedules: equal values in 2025. Fetching both
   would count the border twice.
3. **Both directions on one row** (`from_ch`, `to_ch`, MW, >= 0), not one row per direction and
   not a net: the flows are gross (both directions above 0 in 658 of 756 quarter-hours on DE), so
   a net would lose data, and a row per direction invites adding both.
4. **Mixed resolutions between the two directions** (IT day-ahead schedules, 2025: CH --> IT
   hourly until 2025-09-03, IT --> CH at 15 minutes on single days): the hourly value is
   repeated in each quarter-hour of that hour (4,655 hours). Energy and hourly means stay
   exact; a warning says so. The other way (quarter-hours averaged to hours) would lose data
   as served.
5. **Two tables for the schedules**, one per contract type, so that no query adds day-ahead to
   total (total includes day-ahead).
6. **Imbalance as published**: an energy per quarter-hour in MWh, given the sign of its direction
   (A01 surplus +, A02 deficit -, A03 0), as the swissgrid project checked against Swissgrid's
   TSI. Also `mv_minus_sv` (from 2024-08) and `status` (intermediate, final, null): a value that
   becomes final is a new version.
7. **Generation**: readable codes (`solar`, `hydro_run_of_river`, ...) with ENTSO-E's psrType in
   the label. No energy column, as in `entsoe_load`; the descriptions give MW x duration.
8. **A `resolution` column in every table**, also where it is constant (generation, imbalance),
   as in `entsoe_load`.
9. **Refresh** from the revisions measured (`qa/revisions_entsoe_ch.md`): the lookback covers the
   latest correction seen (generation 93 days, flows under a year, schedules under 30 days, the
   imbalance about 14 months). A request takes 5 to 16 s whatever its length (the platform's
   time, not the size), so long lookbacks cost little time. Flows every 3 hours, not every hour:
   a run of 400 days is 16 requests, 139 s and about 12 MB. Horizon PT0S for the actuals.
10. **`fetch.py`**: whole hours in every request (entsoe-py rounds a time to the nearest hour),
    three attempts on a timeout, a connection error, 429 or 5xx, a split when an answer is cut
    or refused as too large, and a refusal of anything unknown (unit, curve type, area,
    production type, contract type, direction, document status, an interval served twice with
    two values). The token is removed from every error text.
11. **Examples (D31)**: two checks per dataset that teach a trap (energy from MW, the partial
    run-of-river, netting per hour, gross against netted). None for the imbalance (no check).
12. **QA tolerances**: TWh to 0.05 and GWh to 0.5 as printed; 0.00002 TWh for Buckley &
    Schäfer, who print unrounded floats (the reason is in the header of `checks.yaml`). Flows:
    UTC years only, the factsheets' basis.

## What the build measured

- Yearly answers come whole for all four series (no cut seen). A week takes as long as a year.
- Against the swissgrid project's download of 2026-10-31 (`qa/tools/compare_sgp_entsoe_wp52.py`):
  every common value is equal, except the revisions since. Generation: 6 of 608,361 (2026-07-30
  +105 MW, five of October 2026). Imbalance: 13 in September 2025 (the correction of
  2025-09-11), and 7 quarter-hours of 2024-2025 that ENTSO-E has filled since. Flows: 2,239 and
  1,123 of 552,012 values per direction, all from July 2026. Schedules: 5 values of October 2026 in total.
- The first scheduled run after the backfills, 13 minutes later: generation 3 rows stored,
  imbalance 2, flows 4, schedules 277, of which 181 new versions of quarter-hours still ahead
  (the total schedule changes before delivery).
- Traps found and written as warnings: A75 solar below the national PV production (4.3 against
  6.0 TWh in 2024, BFE); gross schedules far above the border's capacity (FR 21,799 MW on
  2019-04-24, net 2,429 MW); A86 is not Swissgrid's control area balance in any year from 2017
  (ElCom's counts). Three traps added to `skills/common-traps.md` (a token in an error text,
  gross flows per direction, one border under two areas).
- Profile (`qa/tools/profile_entsoe_wp52.py`): no hole in flows and schedules; the holes of
  generation and imbalance are those of the source (in the warnings); the days of the clock
  change have 92 and 100 quarter-hours.

## QA with published figures

| dataset | source | match | notes |
|---|---|---|---|
| generation | ENTSO-E Statistical Factsheets 2019-2025 (2023 left out: SFOE data) | 40 of 42 | `qa/published_figures_entsoe_generation.md` |
| physical flows | the same factsheets, flows netted per hour | 19 of 56 (all 8 of the 2025 edition) | `qa/published_figures_entsoe_physical_flows.md` |
| scheduled exchanges | Buckley & Schäfer, TIB, CH totals 2021-2024 | 9 of 16 on `total`, none on `day_ahead` | `qa/published_figures_entsoe_scheduled_exchanges.md` |
| imbalance volume | none after two searches (2026-11-15 and 2026-11-16): ElCom and DNV use Swissgrid's data, ENTSO-E and Compass Lexecon draw CH only in charts | 0 | `qa/published_figures_entsoe_imbalance_volume.md` |

The research agent's report, every value with its table or page, is in
`qa/published_figures_wp52_sources.md`; the values used are also in the scripts
`qa/tools/published_check_entsoe_*.py`. Its ElCom and Swissgrid figures (quarter-hours per bin
beyond +-500 MW, 2017-2025) are on Swissgrid's control area balance: candidates for the checks of
`swissgrid_balance`, which WP4 added to `main` without a `checks.yaml`.

## Next

- Renaud: the definitions (drafts) of the four descriptors; your own documents with figures
  computed from these series (skills/add-dataset, step 8), above all for the imbalance, which
  has no check.
- On the server, after WP1 (2026-11-22): pull, install the four timers, backfill from 2015 (on the
  Mac, all four in parallel: generation and imbalance 4 minutes each, flows 9, schedules 16), then
  look at the first scheduled runs and at `versions_since`.
- `review-dataset` on the four datasets, before they are published.
- `docs/work-packages/WP5-datasets.md` (tracked in `main` since b30f70e): at `land`, after the
  rebase, mark its open question 1 as answered (`append-only` for all four, 2026-11-15) and add
  a log entry for WP5.2.
- QA gaps (2026-11-16, not searched yet): no check for the imbalance, for `day_ahead`, or per
  border and direction for the schedules; generation has yearly totals only. Sources not yet
  opened: ENTSO-E's Balancing Reports and ACER's balancing monitoring (imbalance), JAO's
  nominations and ElCom's reports on border capacity (day-ahead schedules), monthly figures
  from Energy-Charts or ENTSO-E (generation). Already searched: `qa/published_figures_wp52_sources.md`.

## Log

### 2026-11-15, the build

Measured raw answers of the four series (a week and a year each, every border and direction),
wrote the four datasets, tested them on synthetic answers, backfilled them from 2015 on the Mac,
compared them with the swissgrid project's download, collected published figures with a research
agent and turned the matching ones into checks, and ran one scheduled fetch of each.

On the way: the backfill of the schedules failed on its window [2024-12-29, 2025-12-29) (the IT
day-ahead with two resolutions, choice 4) and still ended with status ok (the known defect of
`TODOs.md`: a backfill doesn't resume, and a failed window leaves a hole). The first rerun used
the window [2024-12-30, 2025-12-30): 365-day steps from 2015-01-01 drift by one day per leap
year, so 2024-12-29 stayed empty until the profile showed it.
