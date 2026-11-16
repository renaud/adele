# Published figures for entsoe_imbalance_prices

Collected 2026-11-15 by a research agent (about 26 web searches; it stopped at the usage limit),
checked against adele on 2026-11-16 by Claude on the worktree `wp5.1`'s backfill (2014-12-31 to
2026-11-15). The figures that match are the 60 checks of
`datasets/entsoe_imbalance_prices/checks.yaml` (`adele-server check entsoe_imbalance_prices`:
all pass). The figures that differ are recomputed by `qa/tools/published_check_wp51.py`.
Renaud's own documents: not asked yet.

## Sources

| source | what | URL |
|---|---|---|
| ElCom, Besondere Ereignisse in der Regelzone Schweiz im Jahr 2025 (May 2026) | Tabelle 2: quarter-hours per year 2017-2025 with \|AEP short\| and \|AEP long\| above 1,000, 2,000 and 3,000 EUR/MWh; Tabelle 4: prices of single quarter-hours of 2025 | https://www.elcom.admin.ch/dam/it/sd-web/lpdgJ8PUh5mk/Bericht%20Besondere%20Ereignisse%20in%20der%20Regelzone%20Schweiz%202025.pdf |
| BNetzA, Festlegung BK6-19-217 (2019-12-11) | the two highest reBAP ever (2017-10-17), the reBAP of 2019-06-12 11:45-12:00 | https://www.amprion.net/Dokumente/Strommarkt/Bilanzkreise/Ausgleichsenergiespreis/2019/Festlegung_BK6-19-217.pdf |

ElCom computes on Swissgrid's own prices ("Prices for Balance Energy"), which equal A85 in every
quarter-hour of 2023 and 2024 (swissgrid project, QA 3).

## Result (2026-11-16)

- **Stamps.** Of the 24 single quarter-hours of Tabelle 4, 21 match (both prices) at the local
  start of the quarter-hour, none at the local end, none in UTC. The checks use local times.
- **Tabelle 2, 2022 and 2024:** all 12 counts match. **2023:** 5 of 6 match; |short| > 2,000
  gives 28 against 29, and Swissgrid's own price file (`swiss_energy_data`, table
  `imbalance_price_15min`) gives 28 too: unexplained, left out.
- **Tabelle 2, 2017-2021: a finding for Renaud.** The counts match exactly, but under the other
  label: ElCom's row "AEP long" (e.g. 59 quarter-hours above 1,000 EUR/MWh in 2018) is adele's
  `price_short` (A05), whose extremes in those years are large positive prices (up to 8,170
  EUR/MWh in 2020); ElCom's row "AEP short" is 0 where adele's `price_long` is 0. From 2022 the
  labels agree. A positive price above 1,000 EUR/MWh fits a short position, so the labels of
  ElCom's table for 2017-2021 look swapped; adele's A04/A05 follow ENTSO-E's codes, as in
  2022-2026. The checks follow adele's columns and say so in the question.
- **Tabelle 2, 2025:** |short| > 2,000 (15) and > 3,000 (5) match; the other four differ (65
  against 60, 194 against 196, 54 against 50, 14 against 11). ENTSO-E's 2025 prices differ from
  Swissgrid's in about 1 % of the quarter-hours (swissgrid project: 98.9 % equal), and ElCom's
  long counts above 2,000 and 3,000 differ even from Swissgrid's own file (55 and 14): left out.
- **Tabelle 4, 2025:** the yearly extremes match (short 5,565.9 against 5,566 on 2025-02-12
  14:00 local; long -6,825.8 against -6,826 on 2025-09-06 14:15 local). Six single quarter-hours
  became checks (two of them one hour apart on 2025-02-17, which UTC stamps would swap). Three
  differ: 2025-02-12 14:00 long 49.9 against 60 (ElCom prints 50 for the same quarter-hour in
  its Tabelle 5), 2025-06-21 15:45 short 134.9 against 136, 2025-09-21 13:00 long -7.7 against 8.
- **BNetzA:** 24,455.05 and 20,614.97 EUR/MWh are the two highest DE_LU prices of 2017-10-17
  (17:30 and 17:15 UTC), and 376.57 is the price at 2019-06-12 09:45 UTC (11:45 local, the start
  of the quarter-hour).

## Not usable

- Volume-weighted means only: ElCom's yearly aFRR costs, ACER's MMR 2023 (CH aFRR and mFRR),
  ElCom Regelleistung und Regelenergie 2023 and 2024.
- AT: APG slides give shares of quarter-hours above thresholds per control-area state, without
  the period or the denominator.
- FR: CRE's report on 2022-04-04 states the rule (long = spot - 5 %, short = spot + 5 %), not
  a value. DE: BET 2018 "99 % within +/- 190 EUR/MWh" is rounded.
- Not read (over 10 MB): BNetzA Monitoringbericht 2020 and 2022, RTE Bilan électrique 2024,
  ENTSO-E Balancing Report 2024.
