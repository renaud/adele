# Published figures for entsoe_scheduled_exchanges

Collected 2026-11-15 by a research agent (12 web searches for the four datasets of WP5.2, every
value read in the file), checked against adele the same day with
`qa/tools/published_check_entsoe_scheduled_exchanges.py <data_dir>` on the backfill of the
worktree `wp5.2` (2015-01-01 to 2026-11-16). Renaud's own documents: not asked yet.

`datasets/entsoe_scheduled_exchanges/checks.yaml` holds 9 checks, all on the table `total`.
No published figure was found for `day_ahead`, nor for any single border.

## Sources

| source | what | URL |
|---|---|---|
| T. Buckley, M. Schäfer (Universität Freiburg), Annual imports, exports and balances for European bidding zones, TIB LDM4Energy, created 2025-05-13 | four CSV files (`comm_flows_total_annual_sums_<year>.csv`, 2021-2024): CH over all borders, imports and exports, each also netted per hour, unrounded floats (TWh by their size). "All data based on scheduled commercial exchanges as published by ENTSO-E" | https://doi.org/10.71694/1b92fgz8 |
| BFE, Schweizerische Elektrizitätsstatistik 2025, Tab. 28 | commercial foreign trade per partner country, 2016-2025, GWh, from customs data (BAZG) from 2017 | https://pubdb.bfe.admin.ch/de/publication/download/12681 |

## Result (2026-11-15)

The table `total` reproduces Buckley & Schäfer; `day_ahead` reproduces none of their figures
(e.g. 2021 imports 30.42 against 33.28 TWh): their files hold total schedules, although their
page links to the platform's day-ahead view.

| year | imports | exports | imports netted | exports netted |
|---|---|---|---|---|
| 2021 | -0.010 | -0.006 | -0.010 | -0.005 |
| 2022 | -0.011 | -0.003 | -0.010 | -0.002 |
| 2023 | -0.677 | +3.979 | -0.008 | +4.648 |
| 2024 | -4.070 | -1.294 | -2.664 | +0.112 |

(adele's `total` minus the published figure, GWh, UTC years; "netted": the two directions of a
border netted in each hour, the positive parts summed.)

2021 and 2022 agree to 2 to 11 MWh on 20 to 34 TWh: the same data, apart from a few intervals or
the summation. These 8 figures and the netted imports of 2023 are checks, with a tolerance of
0.00002 TWh (20 MWh). 2023 and 2024 differ by 0.1 to 4.6 GWh: unexplained. Their files were
made in May 2025; schedules corrected later could explain 2024, not 2023 (all corrections that
we measured came within 30 days of delivery, `qa/revisions_entsoe_ch.md`). Their "Balance"
column is exports minus imports, although their page says the opposite: not used.

Left out as well:

| value | why |
|---|---|
| BFE Tab. 28, per country | trade from customs declarations, not TSO schedules; from 2013 the large balance-group transactions with Germany were removed (BFE, section 6.1) |
| any figure for day_ahead or per border | none found from ENTSO-E, Swissgrid, ElCom or ACER |
