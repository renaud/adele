# Published figures for entsoe_physical_flows

Collected 2026-11-15 by a research agent (12 web searches for the four datasets of WP5.2, every
value read in the document), checked against adele the same day with
`qa/tools/published_check_entsoe_physical_flows.py <data_dir>` on the backfill of the worktree
`wp5.2` (2015-01-01 to 2026-11-15). Renaud's own documents: not asked yet.

`datasets/entsoe_physical_flows/checks.yaml` holds 19 checks: the figures of ENTSO-E's
factsheets that match in UTC years. Generator: `gen_checks_wp52.py` in the session scratchpad
(one-off); edit checks.yaml directly from now on.

## Sources

| source | what | URL |
|---|---|---|
| ENTSO-E Statistical Factsheets 2019-2025 | "Physical energy flows" map and "Exchange Balance" table: flow per border and direction, GWh, footnote "Hourly netted physical flow values". The four CH borders add up exactly to the printed sums of imports and exports in 2019-2024 (2025: 1 GWh off). Editions as for generation (2025: June 2026) | as in `qa/published_figures_entsoe_generation.md` |
| BFE, Schweizerische Elektrizitätsstatistik 2025, Tab. 29 | physical import and export per neighbour, calendar years 2016-2025, GWh, measured at the border meters, not netted, with lower voltage levels, border hydro plants and supply areas abroad (BFE's Steckbrief, https://pubdb.bfe.admin.ch/de/publication/download/12136) | https://pubdb.bfe.admin.ch/de/publication/download/12681 |

## How the factsheet figure is computed

In each hour, net the two directions of a border, then sum the positive part of each direction
over the year. For DE from 2021-08 (quarter-hours), the hour is the mean of its quarter-hours
(the factsheets don't say how they make hours; the 2025 figures of DE match this way). Summing
each direction without netting gives larger values: that is the trap the checks test.

## Result (2026-11-15)

21 of 56 figures match within 0.5 GWh, 19 of them in UTC years (the two others only in local
years: 2024 CH --> IT and AT --> CH, left out). All 8 figures of the 2025 edition match. The
older editions differ:

| year | CH --> DE | DE --> CH | CH --> FR | FR --> CH | CH --> IT | IT --> CH | CH --> AT | AT --> CH |
|---|---|---|---|---|---|---|---|---|
| 2019 | +0.9 | -3.4 | +1.3 | -4.1 | -4.6 | ok | ok | -2.2 |
| 2020 | ok | -2.9 | -0.9 | -0.9 | -2.1 | ok | ok | ok |
| 2021 | +7.4 | -11.1 | +1.0 | ok | -7.4 | ok | -1.0 | -1.8 |
| 2022 | +4.7 | +1.7 | +1.0 | ok | -7.9 | -0.5 | +2.3 | -3.2 |
| 2023 | +14.8 | -19.3 | -9.5 | +82.5 | -1.5 | ok | +1.0 | ok |
| 2024 | +20.1 | -8.4 | -4.9 | +10.8 | -0.7 | -5.9 | -3.7 | +0.6 |
| 2025 | ok | ok | ok | ok | ok | ok | ok | ok |

(adele minus the factsheet, GWh, UTC years; "ok" within 0.5.)

Why, most likely: ENTSO-E corrects flows after the editions were made. Flows are corrected up to
a year after delivery (`qa/revisions_entsoe_ch.md`), and against the swissgrid project's download
of 2026-10-31 adele already holds 3,362 changed values of July to October 2026. The edition made
last (2025, June 2026) matches on every border. Not verified for 2019 and 2020: those editions
were re-issued in November 2024, five years after delivery, and still differ by up to 4.6 GWh.
The largest gap, FR --> CH in 2023 (82.5 GWh, 0.9 %), is unexplained.

Left out as well:

| value | why |
|---|---|
| BFE Tab. 29, per neighbour | not netted, and another scope (lower voltage levels, border plants, supply areas abroad): no exact match can be expected |
| Factsheet 2018 (CH imports 30,420, exports 31,693 GWh) | "consolidated yearly values" with national statistics, not the platform |

A later correction by ENTSO-E can make a check of 2025 fail. Then compare with the next edition
of the factsheet before changing the figure.
