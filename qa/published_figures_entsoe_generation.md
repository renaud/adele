# Published figures for entsoe_generation

Collected 2026-11-15 by a research agent (12 web searches for the four datasets of WP5.2, every
value read in the document, none from a search snippet), checked against adele the same day with
`qa/tools/published_check_entsoe_generation.py <data_dir>` on the backfill of the worktree
`wp5.2` (2015-01-01 to 2026-11-15). Renaud's own documents: not asked yet.

`datasets/entsoe_generation/checks.yaml` holds 40 checks: the figures of ENTSO-E's factsheets
that match. Generator: `gen_checks_wp52.py` in the session scratchpad (one-off); edit
checks.yaml directly from now on.

## Sources

| source | what | URL |
|---|---|---|
| ENTSO-E Statistical Factsheets 2019-2025 | "based upon data reported to the ENTSO-E Central Transparency Platform"; table "ENTSO-E in figures", CH net generation per type and total, TWh to 0.1. Editions: 2019 and 2020 re-issued November 2024, 2021 March 2023, 2022 June 2023, 2023 April 2024, 2024 March 2025, 2025 June 2026 | https://eepublicdownloads.entsoe.eu/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs2019_web.pdf (2019-2021); https://eepublicdownloads.blob.core.windows.net/public-cdn-container/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs2022_web.pdf (2022-2025) |
| BFE, Schweizerische Elektrizitätsstatistik 2025 | Tab. 6 and 7: production per type, calendar years, whole fleet, GWh | https://pubdb.bfe.admin.ch/de/publication/download/12681 |
| Energy-Charts, yearly JSON for CH | copies the BFE figures (reservoir + pumped storage = BFE storage hydro in every year); only the split of storage hydro is new, its method not stated | https://www.energy-charts.info/charts/energy/data/ch/year_2024.json |

## Result (2026-11-15)

Factsheets 2019, 2020, 2021, 2022, 2024, 2025: 40 of 42 figures match (TWh to 0.05), with UTC
and with local years alike. Matching: nuclear, pumped storage, run-of-river and wind in all six
years; reservoir and solar in 2019-2024; the total of all types in 2019-2024, and the total
without pumped storage in 2025 ("exclusive storage units"). The 2024 run-of-river (2.3 TWh) and
the 2025 one (14.5 TWh) confirm the break of coverage at 2025-01-01 that `datapackage.yaml`
warns about.

Left out:

| value | published | adele | why |
|---|---|---|---|
| 2025 hydro_reservoir | 9.8 TWh | 9.852 | unexplained. The parts printed for 2025 add up to 48.1 TWh, the printed total is 48.0, as in adele (48.04): the parts and the total of that edition disagree. ENTSO-E may have revised 2025 after June 2026 |
| 2025 solar | 5.2 TWh | 5.107 | same |
| 2023, every type | e.g. run-of-river 17.5, solar 5.2 TWh | 2.131, 3.538 | the factsheet's footnote 3: CH "Data is taken from SFOE (Swiss Federal Office of Energy) and Pronovo. For Wind and Solar estimations based on model data have been used." Not the platform |
| BFE production per type, 2015-2025 | e.g. 2024 run-of-river 19,403 GWh, PV 5,961 GWh, total 81,054 GWh | 2,273, 4,306, 53,202 GWh | the whole fleet and every type (thermal, small hydro); the platform has only some types, and part of the fleet. Nuclear is close in 2024 (22,983 against 22,959 GWh) but not in 2019 (25,280 against 25,724 GWh): another measure. The gaps are in the warnings |
| Energy-Charts | | | copies BFE |

Not found: a figure computed from the platform's A75 with an hour (an extreme with its stamp),
which would test the stamps; ENTSO-E's factsheets give only yearly sums for generation.
