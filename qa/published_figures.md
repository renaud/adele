# Published figures for entsoe_day_ahead_prices

Collected 2026-11-13 by a research agent (13 documents, about 100 values), checked against adele
the same day with `qa/tools/published_check_entsoe_day_ahead_prices.py <data_dir>` (87 values:
annual means, minimum, maximum, standard deviation, hours with a negative price; CH, DE, FR;
2015-2025). Candidates for QA questions with known answers, and for checks that the server could
run after each fetch.

## Sources

| source | what | URL |
|---|---|---|
| SMARD (Bundesnetzagentur) | DE-LU yearly mean, min, max, negative hours 2020-2025; FR and CH means 2024-2025 | https://smard.de/page/en/topic-article/5892/215704 and https://www.smard.de/page/en/topic-article/5892/219038/record-high-for-solar-generation-in-each-quarter |
| ElCom, Market Transparency 2019-2022 | CH, DE, FR yearly means (means of daily base prices), CH hours above thresholds | https://www.elcom.admin.ch/dam/en/sd-web/LF60QBlvQwoS/markttransparenz2022berichtderelcom.pdf |
| ElCom, negative prices 2015-2020 (Jan 2021) | CH, DE, FR negative hours and minimum per year | https://www.elcom.admin.ch/dam/en/sd-web/QuXm2cRVxBau/analysedernegativenpreisefuerdieschweizfrankreichunddeutschlandzwischen2015und2020.pdf |
| CRE, monitoring report 2024 | FR means 2022-2024, peak, FR-DE spread, negative and zero hours | https://www.cre.fr/fileadmin/Documents/Rapports_et_etudes/2025/Rapport_de_surveillance_2024.pdf |
| RTE, Bilan électrique 2024 and 2025 | FR means, negative hours, hours at or above 100 | https://assets.rte-france.com/prod/public/2026-02/Bilan-electrique-2025-principaux-resultats.pdf |
| Keles et al. 2020, Energy Economics 90:104802 | CH 2015-2018 mean, std, min, max | https://publikationen.bibliothek.kit.edu/1000125633/142347297 |
| EPEX, Power Trading Results 2025-12 | December 2025 base averages | local copy in the swissgrid project, `papers/EPEX_2026_Power_Trading_Results_2025-12.md` |

## Result of the check (2026-11-13)

79 of 87 values match to 0.01 (to 0.5 for hour counts). The 8 differences:

| value | published | adele | why |
|---|---|---|---|
| DE 2015 negative hours | 126 (ElCom) | 110 | ENTSO-E's DE_AT_LU and FR series start on 2015-01-05: 1-4 January 2015 are missing |
| FR 2015 mean | 38.44 (Tschora et al.) | 38.46 | probably the same missing days |
| DE 2018 negative hours | 119 (ElCom), 134 (Bundesnetzagentur) | 134 (DE_AT_LU 107 + DE_LU 27) | ElCom's 119 matches neither code nor the sum: unexplained |
| DE 2025 negative hours | 573 (SMARD), about 575 (FfE) | 574.75 time, 576 hours with a negative hourly mean, 588 hours with a negative quarter | definition after 2025-10-01; SMARD's matches none of the three |
| FR 2025 negative hours | 513 (RTE) | 513 hours with a negative hourly mean (509.25 time) | RTE counts hours whose mean of four quarters is negative |
| CH 2016 std | 16.80 (Keles) | 16.78 | small; their data or their treatment of the clock-change hours |
| FR 2023 mean | 96.9 (CRE, rounded) | 96.86 | rounding |
| FR 2015 negative hours | 0 | 0 (the script shows "None") | none |

Also found: on 2024-06-26, EPEX's German auction was decoupled (prices up to 2,325.83 EUR/MWh), and
ENTSO-E publishes the coupled price of the other exchanges (adele's maximum that day: 134.39). That
explains why CRE's German mean for 2024 (about 79.6, derived from its FR-DE spread) differs from
SMARD's 78.51. A warning for the analyst to write.
