# Published figures for entsoe_load

Collected 2026-11-15 by a research agent (about 20 web searches, 15 documents), checked against
adele the same day with `qa/tools/published_check_entsoe_load.py <data_dir>` on the backfill of
the worktree `wp3` (2015-01-01 to 2026-11-15). Renaud asked for published figures as the QA of
the dataset instead of confirming the example queries himself.

`datasets/entsoe_load/checks.yaml` holds 50 checks: the 47 figures of the ENTSO-E factsheets
that match, two of Kazmi & Tao with a tolerance for their filter, and one of Tzortzis et al.
Generator: `gen_checks_load.py` in the session scratchpad (one-off); edit checks.yaml directly
from now on.

## Sources

| source | what | URL |
|---|---|---|
| ENTSO-E Statistical Factsheets 2019-2025 | "based upon data reported to the ENTSO-E Central Transparency Platform"; CH net consumption (TWh), highest and lowest hourly load with the hour (UTC), CH load at the hours of ENTSO-E's highest and lowest load | https://eepublicdownloads.entsoe.eu/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs2019_web.pdf (2019-2021); https://eepublicdownloads.blob.core.windows.net/public-cdn-container/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs2022_web.pdf (2022-2025) |
| Kazmi & Tao 2022, Applied Energy 323:119565 | Table 1: error of the TSO day-ahead load forecast per country, from the Transparency Platform (R2, ME, MAE, WAPE, rMAE) | https://lirias.kuleuven.be/retrieve/d4e0320a-92c6-409a-b024-fdd2e8e8e551 (preprint) |
| Tzortzis et al. 2023, arXiv 2310.15555 | Table 2: MAPE of a naive weekly forecast, test year 2021, 27 countries from the Transparency Platform | https://arxiv.org/html/2310.15555 |
| ENTSO-E Statistical Factsheets 2015-2018 | the same tables, from ENTSO-E's statistical data (not the platform), scaled to 100 %, times in CET/CEST | https://eepublicdownloads.entsoe.eu/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs2018_web.pdf (and 2015-2017) |
| BFE, Schweizerische Elektrizitätsstatistik 2024 | Landesverbrauch 2015-2024 (Tab. 6), Höchstlast on the third Wednesday of each month (Tab. 26a) | https://pubdb.bfe.admin.ch/fr/publication/download/12228 |

## Result (2026-11-15)

Factsheets 2019-2025: 47 of 49 figures match (whole MW to 0.5, TWh to 0.05). Every hourly value
matches at ENTSO-E's stamp, which is adele's stamp plus one hour before 2024-12-31 23:00 UTC:
the factsheets use the stamps as served. The two glitch lows that `datapackage.yaml` warns about
(3,747 MW at 2023-02-17 00:00, 2,743 MW at 2024-12-05 22:00, ENTSO-E's stamps) are ENTSO-E's
published yearly minima.

Kazmi & Tao (CH: R2 .74, ME -68, MAE 416, WAPE 5.84): adele gives R2 .729, ME -69.8, MAE 416.6,
WAPE 5.87 over 2015-2021 with ENTSO-E's stamps of the actual load; over 2017-2021 (the period
of most of their analysis) MAE 443.0, and with adele's stamps MAE 439.5. So their table is the
data as served, 2015-2021. They filtered "anomalous measurements" without describing how: MAE
(tolerance 5 MW) and ME (3 MW) are checks, R2 and WAPE are left out.

Tzortzis et al. (CH sNaive(168) MAPE 6.25 %, 2021): adele 6.25 % in local and in UTC years.

Left out:

| value | published | adele | why |
|---|---|---|---|
| 2023 net consumption | 60.3 TWh (SFS2023) | 61.07 | the factsheet's footnote: CH "Data is taken from SFOE (Swiss Federal Office of Energy) and Pronovo" |
| 2025 net consumption | 62.4 TWh (SFS2025) | 62.07 | unexplained; the hourly values of 2025 match, and no footnote names another source |
| 2015-2018 consumption | 63.4, 63.1, 63.4, 62.3 TWh | 62.15, 62.58, 61.14, 60.42 | statistical data scaled to 100 %, not the platform |
| 2015-2018 highest and lowest hours | e.g. 2018 highest 9,762 | 2018 highest 9,814 | same; only the 2018 lowest (4,476) matches |
| BFE Landesverbrauch 2015-2024 | e.g. 2019 61,501 GWh | 63,405 GWh | another series (the level differs, `datapackage.yaml` warnings) |
| BFE Höchstlast, third Wednesdays | e.g. 2022 10,271 MW | yearly max 10,189 | measured on 12 days only, another series |
| Barta et al. 2016, completeness of 2015 | 8.34 % missing | none missing | the platform was filled since |

Not found (by the agent): Hirth et al. 2018 (no CH), other benchmarks of TSO day-ahead load
forecasts with a CH row, Swissgrid's yearly peak load, Energy-Charts' CH figures (rendered by
JavaScript), ENTSO-E's Monthly Hourly Load Values files (not fetched: large).

## Found on the way: the timing of the forecast

The forecast's error depends on how its stamps line up with the actual load's. The MAE of the
forecast against adele's actual load, with the forecast moved by one hour or not (the months
where the forecast is a copy of the actual, 2021-09 to 2022-12, left out), is lowest:

- one hour earlier (the forecast stamped at the end of the hour, as the actual was) in each year
  2015-2018 (by 22 to 75 MW) and in each month of January-August 2023 (about 200 MW against
  370: the error halves);
- at the same hour in 2019-2021 and from October 2023 on (2024 has three months that point
  either way by less than 15 MW).

The swissgrid project found 2015 and 2022 "about 1 h late", 2016-2021 "not settled", start
stamps from 2023 (from the time of the morning rise), and moved nothing; for January-August
2023 it only assumed that the actual load is end-stamped. Whether to move the forecast in
2015-2018, and whether to keep the move of the actual in January-August 2023, is for Renaud to
decide before the backfill on the server (WP3-versions.md, open questions).
