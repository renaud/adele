# WP5.4: prices outside ENTSO-E

Built by Claude on 2026-11-15 in the worktree `wp5.4`, at Renaud's request ("build WP5.4", then "also include
published figures"). The sub-package is defined in `docs/work-packages/WP5-datasets.md` (four datasets). The
measurements behind each choice are in the docstrings of the two `fetch.py`; the published figures in
`qa/published_figures_<id>.md`.

## What was built

| dataset | table | rows (backfill on the Mac) | refresh | checks |
|---|---|---|---|---|
| `swissgrid_imbalance_prices` | `prices`: one row per quarter-hour, `price_regime`, `price_long`, `price_short`, `price_single` (EUR/MWh) | 131,420, 2023-01-01 to 2026-09-30 local | daily, lookback 93 days, `overwrite` | 47 (ElCom weekly reports) |
| `energy_charts_intraday_prices` | `prices`: one row per zone (CH, DE_LU, DE_AT_LU) and hour, `id_avg`, `id_low`, `id_high`, `id3`, `id1`, `ida1`, `ida2`, `ida15` (EUR/MWh) | 208,128, 2015-01-01 to 2026-11-14 | every 6 hours, lookback 3 days, `overwrite` | 12 (EPEX monthly reports) |

Both descriptors validate; a second fetch of the same window changes nothing; every check passes; 19 tests on
synthetic files (`server/tests/test_*_fetch.py` of each). Every definition in the descriptors is a draft by Claude.
Not yet on steacher1 (WP1 closed on 2026-11-16, so the install can start; `TODOs.md`).

## What Claude chose

1. **Two datasets, not four.** The CH and DE spot prices of Energy-Charts come from the same year files with the
   same series: one dataset, one table with `bidding_zone`.
2. **No day-ahead price from Energy-Charts.** The year files carry it until the auction moved to quarter-hours
   (DE until 2025-09-30, CH until 2026-11-03), and it equals `entsoe_day_ahead_prices` (99.97 % of DE hours, all CH
   hours but 2015, 2017 and 22 hours of 2018). The dataset "Energy-Charts API, DE-LU day-ahead" is not built for the
   same reason: the API equals adele's ENTSO-E DE_LU on all 8,784 hours of 2024, and it serves CH only until
   2026-11-03 (no quarter-hours for CH).
3. **Energy-Charts from 2015**, not 2019 as in the inventory: the files go back to 2015 and their stamps are right
   (see the finding below).
4. **CH hours written as 0 are stored as null**: 257 hours of 2021-2025 where the average, the low and the high are
   all exactly 0.00, mostly at night, while the day-ahead price had a median of 236.5 EUR/MWh (2022). Read as hours
   without a trade (before 2021 the source writes null). The DE hours with an average of 0.00 have trades and stay.
5. **Single price filled into both sides:** from 2026, `price_long = price_short = price_single`, so that "the price
   of a short group" is one column over the whole history; `price_regime` says which rule applies.
6. **Swissgrid: final prices only**, from the monthly notices. The provisional price of the control-area file waits
   for WP4. A month whose file is still missing 45 days after its end sets the status to failing.
7. **Lookbacks:** 93 days for Swissgrid (a month's notice appears on the 12th to 24th of the next month, and two
   notices of 2026 were uploaded again a month later); 3 days for Energy-Charts, short on purpose: with `overwrite`,
   a series that the source drops (IDA1/IDA2 of 2026, below) erases stored values only inside the lookback.
8. **Checks of 2026 with a stand-in:** ElCom splits the 2026 weeks by the state of the control area (TSI), which
   adele doesn't have; the checks split by the single price against the CH day-ahead price, and keep only the 17
   weeks where both splits give ElCom's figures.

## Findings

- **ENTSO-E's CH day-ahead price is one hour late from 2017-04-27 22:00 to 2017-10-29 01:00 UTC** (4,140 hours),
  and on about ten days of summer 2015 (277 hours). Evidence: in those stretches Energy-Charts' CH price at t equals
  ENTSO-E's at t + 1 h (100 % of hours); per month of 2017, the hourly changes of ENTSO-E's CH follow DE_AT_LU's
  best at a lag of one hour from May to October, Energy-Charts' CH at lag 0 in every month. This is in
  `entsoe_day_ahead_prices`, outside WP5.4: not changed, reported to Renaud.
- **Energy-Charts dropped the 2026 values of CH IDA1 and IDA2** between 2026-10-28 and 2026-11-15. SED holds 7,223
  and 3,612 of them (Carlo's download); adele can't get them from the source any more.
- **SED's reading of CH liquidity needs a correction:** its note says that the 60-minute contract traded in every
  hour since 2021-12-21; the 257 hours written as 0 say otherwise.
- **Swissgrid's notice and ElCom agree;** two weekly figures of 2026 differ (unexplained, notes in
  `qa/published_figures_swissgrid_imbalance_prices.md`). ElCom's text confirms an extreme with its time
  (2026-05-19 12:45 local, -3,352.2 EUR/MWh).

## Open

1. Renaud: the definitions (all drafts), and the choices above, in particular 1, 2 and 4.
2. Renaud's own documents with figures from these sources (skills/add-dataset, step 8), if any.
3. EPEX's monthly reports of 2020-2025 for more checks: EPEX refuses scripts. With `epexspot.com` in PinchTab's
   allowed domains (and `allowDownload`), or downloaded by hand. URLs found on 2026-11-15:
   `https://www.epexspot.com/sites/default/files/download_center_files/` + `2020-10-02_EPEX%20SPOT_Power%20Trading%20Results%2009-2020.pdf`,
   `2023-05-05_..._04-2023_0.pdf`, `2023-11-06_..._10-2023.pdf`, `2024-02-05_..._01-2024_1.pdf`,
   `2024-03-05_..._02-2024_1.pdf`, `2024-05-07_..._04-2024_0.pdf`, `2024-06-04_..._05-2024_0.pdf`,
   `2024-07-09_..._06-2024.pdf`, `2024-12-03_..._11-2024.pdf`, `2025-01-08_..._12-2024.pdf`,
   `2025-01-28_EPEX%20SPOT_Annual%20Power%20Trading%20Results%202024_finaldraft_0.pdf`, `2025-03-05_..._02-2025.pdf`,
   `2025-04-02_..._03-2025_1.pdf`, `2025-05-05_..._04-2025.pdf`, `2025-07-02_..._06-2025_2.pdf`,
   `2025-08-04_..._07-2025.pdf`, `2025-09-02_..._08-2025.pdf` (`...` = `EPEX%20SPOT_Power%20Trading%20Results%20`);
   and on eex-group.com (404 on 2026-11-15) the reports of 2021-01 and 2023-01 to 2023-08.
4. ElCom's weekly reports of 2023-2025 (dual price, plain means: the cleanest checks for Swissgrid).
5. The 15-minute intraday prices: Energy-Charts' year files are hourly. A file that turns to quarter-hours stops
   `fetch.py` on purpose.
6. Install and backfill on steacher1 (Swissgrid from 2023-01, Energy-Charts from 2014-12-31), then `adele-server check`; `review-dataset` before publishing.
