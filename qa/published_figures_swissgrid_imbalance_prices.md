# Published figures for swissgrid_imbalance_prices

Collected 2026-11-15 by Claude (WP5.4), checked the same day with
`qa/tools/published_check_swissgrid_imbalance_prices.py <data_dir> [<SED store>]` on the backfill of the worktree
`wp5.4` (2023-01-01 to 2026-09-30 local). Renaud asked for published figures as the QA of each dataset of WP5.4. His
own documents were not asked for yet.

`datasets/swissgrid_imbalance_prices/checks.yaml` holds 47 checks: 12 weekly figures of 2025, 34 of 2026 (17 weeks),
and the time of the lowest price of 2026-05-19. Generator: `gen_checks_wp54.py` in the session scratchpad (one-off);
edit checks.yaml directly from now on.

## Sources

| source | what | URL |
|---|---|---|
| ElCom, weekly market reports ("Marktbericht"), 2025-11-11 to 2026-08-18 | page "Regelzone", table "Ausgleichsenergiepreis" in whole EUR/MWh, this week and the week before. 2025: "AE+ (short)", "AE- (long)", "ungewichtetes Mittel". 2026: "AE short", "AE long", in August "AE für RZ short/long", defined as "Ausgleichsenergiepreis für den Fall, dass die Regelzone short (negative Unausgeglichenheit) oder long (positive U.) ist". Also events in the text | listed per check in `checks.yaml`; index: https://www.elcom.admin.ch/elcom/en/home/topics/market-surveillance/marktberichte.html |

23 reports were found by web search and read; 4 reports of 2025 (26.08, 23.09, 21.10, 28.10) were found but their
URLs answered 404. ElCom names some reports in the month-first form (`Marktbericht vom 02-24-2026` is 24 February).

## Result (2026-11-15)

- **2025, dual price: 12 of 12 match.** ElCom's figures are the plain means of `price_short` and `price_long` over the
  local week, Monday 00:00 to Monday 00:00 (6 weeks, 2025-10-27 to 2025-12-08).
- **2026, single price, ElCom's own definition: 48 of 50 match** when the quarter-hours are split by the TSI of
  Swissgrid's control-area file (SED's `control_area_balance_15min`, TSI < 0 short, > 0 long). The week of
  2025-12-29 (Monday to Sunday across the new year) matches too: ElCom uses the price by the 2026 rules for the
  three days of 2025 (`price_single`, published next to the dual price).
- **2026 in `checks.yaml`, a stand-in:** adele has no TSI (it comes with the control-area file, WP4). The checks
  split the quarter-hours by the single price against the CH day-ahead price (above: short; at or below: long). In
  17 of the 25 weeks this gives both of ElCom's figures within 0.5; only those 17 weeks are checks. Where the
  control-area file enters adele, the checks can use the TSI and take the other weeks too.
- **The event of 2026-05-19** (report of 2026-05-26: "Aktivierungskosten um 12:45 Uhr auf über 450'000 EUR/15min,
  was sich in einem Ausgleichsenergiepreis von über 3'300 EUR/MWh niederschlug", the control area long): the lowest
  price of that day is -3,352.2 EUR/MWh at 12:45 local. A check of the local time: it tests the stamps (the start of
  the quarter-hour, UTC) and the zone.
- The report of 2026-03-31: "die Aktivierung fast der gesamten TRE-Gebote am Samstag, was die Ausgleichsenergiepreise
  auf fast -7'000 EUR/MWh drückte": the lowest price of that week is -6,884.8 EUR/MWh on Saturday 2026-03-28 at 10:45
  local. Not a check (no exact figure).

## Differences

| week | ElCom | adele | reason |
|---|---|---|---|
| 2026-01-26, short | 214 | 219.1 (with TSI and with the stand-in) | unexplained. The long figure (83) matches. Possibly a price that Swissgrid corrected after ElCom's report (the January notice was uploaded again on 2026-03-24) |
| 2026-03-23, short | 227 | 226.3 (with TSI) | unexplained, 0.7 off. The week holds the clock change (668 quarter-hours); ElCom may cut the week otherwise |
| 8 weeks of 2026, stand-in only | | | the stand-in misses where the price lies on the "wrong" side of the day-ahead price for the state of the control area; with the TSI these weeks match (except the two above). Left out of the checks |

## Not found

- No yearly mean of the imbalance price in ElCom's report on balancing ("Bericht Regelleistung und Regelenergie
  2024": prices of balancing energy, not imbalance prices). Swissgrid's annual reports were not read.
- No figure before 2025-10 yet: ElCom's reports of 2023-2025 should give many weeks of the dual price (plain means,
  the cleanest checks). Their URLs are listed on ElCom's index page; a later session can add them.
