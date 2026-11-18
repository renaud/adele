# WP5.1: ENTSO-E without versions

Built by Claude on 2026-11-15 in the worktree `wp5.1` (branch `wp5.1`, from `ab8c532`), at
Renaud's request ("build WP5.1"). The list of datasets is in `docs/work-packages/WP5-datasets.md`
(untracked in `main` on 2026-11-15), section "WP5.1 ENTSO-E without versions". Every definition
in the descriptors is a draft by Claude (`# draft by Claude`) until Renaud changes or confirms it
(WP7).

## What was built

Five datasets instead of the six rows of WP5-datasets.md: the imbalance prices of CH and of the
neighbours share one dataset, as the day-ahead prices do (same document A85, same columns).

| dataset | document | rows on 2026-11-15 | span | revisions | refresh |
|---|---|---|---|---|---|
| `entsoe_imbalance_prices` | A85, CH, AT, DE_LU, FR | 1,281,598 | 2014-12-31 to now | append-only (neighbours revised) | PT6H, lookback P400D |
| `entsoe_activated_balancing_prices` | A84, CH | 1,619,793 | 2015-04-30 to now | overwrite | PT1H, lookback P14D |
| `entsoe_balancing_state` | A86 B33, CH | 2,995,554 | 2019-09-30 to 2025-06-18 | overwrite | P1D, lookback P7D |
| `entsoe_imbalance_volume_neighbours` | A86, 10 areas | 2,552,230 | 2014-12-31 to now | append-only (revised) | PT6H, lookback P400D |
| `entsoe_installed_capacity` | A68, CH, by year (D26) | 48 | 2015 to 2026 | overwrite | P1D, lookback P366D |

Each has `datapackage.yaml`, `fetch.py` (requests and the standard library only, no entsoe-py),
passes `adele-server validate`, was fetched twice on a short window (the second fetch changed
nothing) and backfilled on the Mac (`data_nosync/` of the worktree). Tests on synthetic answers:
`server/tests/test_entsoe_balancing_fetch.py`. On the server: after WP1's week (TODOs.md).

## Checked against the swissgrid project's downloads (2026-10-31 and 2026-11-01)

Every stored value joined on its key with `swissgrid_project/data/entsoe/*.parquet` and
`data/entsoe_neighbours/*.parquet`, up to 2026-10-31:

- activated prices (1.6 million values, products and categories included), balancing state
  (2,995,554 minutes, direction and signed value), installed capacity (48): identical, nothing
  on one side only.
- imbalance prices: CH identical (724,594 values); AT 132 and FR 41 values differ (revisions,
  below); nothing on one side only once the backfill started at 2014-12-31.

## Choices made while building

1. **Status of the documents not stored.** A85 and A86 come as an "intermediate" (A01) and a
   "final" (A02) document, each covering other days (CH 2026: final until 2026-04-06, then
   days of both kinds mixed until 2026-06-25, then intermediate; AT 2025: February, June and
   November still intermediate). The pattern of CH did not change between 2026-10-31 and
   2026-11-15. With a lookback of 14 days a stored status would stay "intermediate" after
   ENTSO-E finalizes: the status only decides which value wins when an interval comes twice.
2. **The two imbalance prices side by side** (`price_long` = A04, `price_short` = A05), one
   row per interval, instead of two rows per interval.
3. **Signs normalized, directions kept.** The volumes of the neighbours and the balancing state
   carry a signed column (> 0 = long) and the direction code as served. AT before 2024-12-01
   uses the opposite convention except where a point carries `secondaryQuantity` (the swissgrid
   project's finding); the cut is placed at 2024-12-01 00:00 local. B33's codes run opposite to
   A86's (A01 = short). `secondaryQuantity` (MV - SV) is not stored: its sign convention was
   never checked.
4. **Readable codes for A84**: reserve aFRR/mFRR/RR, resource generation/mixed/load, direction
   up/down. Product and price category stay as served (code list v36r0 has no list of market
   products and no A08 price category).
5. **Installed capacity: no year to come.** The platform answers the latest values for any
   future year (2027 and 2028 equal 2026 on 2026-11-15), so `fetch.py` never asks a year that
   has not started.
6. **Areas without data are not asked**: German TSO areas, German control block and Italy for
   A85; the control block for A86 (none in any window of the swissgrid project's download).

## The neighbours are revised (open question 3 of WP5-datasets.md)

`qa/tools/revisions_entsoe_ch.py --neighbours` compared the swissgrid project's answers of
2026-11-01 with fresh ones (2026-11-15). A86: 3,592,511 values equal, 3,075 changed (47 under 2
days, 52 at 2-7 days, 18 at 7-30 days, 2,958 at 1-12 months: TenneT's whole August 2026), 258
added, 61 removed. A85 (from the stored backfill against the project's parquet): AT replaced
its prices of the last week before the old download, FR changed 2026-05-13 (six months later)
and some of October 2026; CH unchanged. The tool's A85 run (AT, DE_LU, FR): 1,829,339 values
equal, 335 changed (238 under 2 days, 73 at 2-7 days, 14 at 7-30 days, 10 at 1-12 months: FR
2026-05-13 15:15-15:45 UTC, e.g. 52.97 --> -88.13 EUR/MWh), 12 added, none removed.
So both datasets are `append-only` (Renaud's rule for revised ENTSO-E series), with a lookback
of 400 days every 6 hours (proposal). The sign check: the signed imbalance correlates
negatively with the imbalance price in every month of AT (144) and DE_LU (90), 143 of 144 for FR.

## Published figures (step 8, 2026-11-16)

Two research agents collected candidates on 2026-11-15 (one stopped at the usage limit, the
other at the search limit); Claude checked each quote in their text extracts and compared each
figure with the stored data on 2026-11-16. Notes per dataset: `qa/published_figures_<id>.md`;
the figures that differ: `qa/tools/published_check_wp51.py`. Renaud has no reports of his own
with figures from these series (asked on 2026-11-16).

| dataset | checks | sources |
|---|---|---|
| `entsoe_imbalance_prices` | 60, all pass | ElCom, Besondere Ereignisse 2025 (counts of extreme prices 2017-2025, single quarter-hours of 2025); BNetzA BK6-19-217 (DE_LU) |
| `entsoe_installed_capacity` | 16, all pass | ENTSO-E Statistical Factsheets 2019, 2020, 2022, 2024 |
| `entsoe_imbalance_volume_neighbours` | 3, all pass | ENTSO-E Balancing Report 2020 (FR 2018-2019) |
| `entsoe_balancing_state` | none | ENTSO-E LFC reports: computed on Swissgrid's FRCE, not on B33 |
| `entsoe_activated_balancing_prices` | none | only volume-weighted figures |

Findings:

1. **ElCom's labels for 2017-2021 look swapped.** Its counts of extreme prices match adele
   exactly, but its row "AEP long" holds what adele has in `price_short` (positive prices up to
   8,170 EUR/MWh); from 2022 the labels agree. The checks follow adele's columns.
2. **Stamps: local start of the quarter-hour.** 21 of ElCom's 24 single quarter-hours of 2025
   match at that stamp, none in UTC; BNetzA's 376.57 EUR/MWh of 2019-06-12 11:45 local too.
3. **ENTSO-E's 2025 prices differ from Swissgrid's in a few quarter-hours**: 4 of ElCom's 6
   counts of 2025 differ (left out).
4. **The spike of 2023-11-28 in the balancing state is an error of the B33 publication**:
   Swissgrid's FRCE in the LFC report agrees with B33 in every month of 2023 but November. The
   spike of 2024-07-13 is in that FRCE too. The warning of the descriptor was corrected.
5. France 2018-2019: adele's sign reproduces the report's asymmetry (55 % positive periods);
   the negative mean differs by 6 MWh (-356.2 against -350), unexplained.

## Left to do

1. Renaud, after the landing: the drafts of every definition (WP7), the change to
   `append-only` for the two neighbour datasets, the refresh proposals, and finding 1 above.
2. On the server, after WP1's week: install and backfill the five datasets (another agent's task).

Not needed for now (Renaud, 2026-11-16): copying these findings into WP5-datasets.md (open
question 3 answered).

## Bugs found during the build

- `fetch.py` of the imbalance prices dropped every interval of a document without a status
  (all of 2015-2018): pandas' `Series.map(dict)` does not look up `None`, and the NaN rank lost
  against itself. Fixed in both files that rank statuses; covered by a test.
