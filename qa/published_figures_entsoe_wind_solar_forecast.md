# Published figures for entsoe_wind_solar_forecast (CH)

Collected 2026-11-15 by Claude (WP5.3), at Renaud's request ("try to find some, either in other
projects, or on the web"; he has no documents of his own with such figures). Sources: two web
searches by research agents (38 and 18 searches), the literature PDFs of `predico_enlab`
(`docs/literature_review/pdfs/`), and the PV paper of Zsiborács et al. 2023, which Renaud
downloaded (`adele/tmp/`). Compared with adele the same day with
`qa/tools/published_check_entsoe_wind_solar_forecast.py <data_dir> [<actual.parquet>]` on the
backfill of the worktree `wp5.3` (2015 to 2026-11-17).

Few figures use the Swiss forecast alone: papers that use ENTSO-E's wind and solar forecasts as
inputs rarely publish statistics of them, and the Swiss series is small. Most published figures
about it are forecast errors, which need ENTSO-E's actual generation (A75): that series is the
dataset `entsoe_generation` (WP5.2, not in `main` on 2026-11-15). The script reads it from the
data folder when it exists; here it used the swissgrid project's download of the same series
(`swissgrid_project/data/entsoe/generation.parquet`, 2026-10-31).

`datasets/entsoe_wind_solar_forecast/checks.yaml` holds 11 checks: the completeness of the
day-ahead wind forecast in 2015 and 2018-2021, and of the day-ahead solar forecast in 2015 and
2018-2022.

## Sources

| source | what | URL |
|---|---|---|
| Zsiborács, Pintér, Vincze & Baranyai 2022, Sustainability 14(24):16446 | Table 3: completeness (%) of the DA and ID onshore wind forecasts per country and year, 2013-2021; Table A5: CH, yearly "downward" and "upward regulation need" of the DA wind forecast (% of the year's energy) | https://www.mdpi.com/2071-1050/14/24/16446 (PDF also in `predico_enlab/docs/literature_review/pdfs/zsiboracs2022wind.pdf`) |
| Kazmi & Tao 2022, Applied Energy 323:119565 | Tables 2 and 3: error of the TSO day-ahead wind and solar forecasts per country, 2017-2021, hourly (ME, MAE, WAPE, R2) | https://lirias.kuleuven.be/retrieve/672627 |
| ENTSO-E & SolarPower Europe 2015, "Solar eclipse March 2015" | p. 14: day-ahead PV forecast per TSO at 12:00 CET on 2015-03-20 | https://eepublicdownloads.entsoe.eu/clean-documents/Publications/ENTSO-E%20general%20publications/entsoe_spe_pp_solar_eclipse_2015_web.pdf |
| Zsiborács, Vincze, Pintér & Hegedűsné Baranyai 2023, IEEE Access 11 | the same analysis for PV, 2013-2022: Table 2 (p. 74959) completeness, Table 6 (p. 74965) CH regulation needs; both tables are images, read by eye at 300 dpi | https://doi.org/10.1109/ACCESS.2023.3297494 |

## Result (2026-11-15)

Zsiborács Table 3, CH day-ahead wind (60 min), share of the year with a forecast:

| year | published | adele | |
|---|---|---|---|
| 2015 | 99.2 | 99.18 | check: the three missing days (72 hours) |
| 2016 | 99.4 | 100.00 | differs, unexplained: neither the forecast nor the actual has a hole in 2016 today |
| 2017 | 99.7 | 100.00 | matches (99.74) only when the hours without an actual value also count, as in their definition: the actual misses 23 hours from 2017-10-28. Waits for entsoe_generation |
| 2018-2021 | 100 | 100.00 | checks |

Local and UTC years give the same values.

Zsiborács 2023 Table 2, CH day-ahead solar (60 min): 2015 99.5 (adele 99.45: the two missing days),
2018-2022 100: checks. 2016 99.5 (adele 99.73, the one missing day 2016-10-11) and 2017 99.7
(adele 100; 99.74 with the actual's 23 missing hours) differ as for wind; 2016 also differs for AT
in both papers (`qa/published_figures_entsoe_wind_solar_forecast_neighbours.md`), so their 2016
download probably missed a day or two.

Zsiborács 2023 Table 6, CH day-ahead solar, regulation needs (needs the actual): 2015 (9.4, 37.5),
2017 upward (16.6) and 2019 (5.3, 12.0) match to 0.05; 2016 (8.5, 20.0; adele 8.59, 19.89), 2017
downward (4.6; 4.73) and 2018 (4.6, 42.7; 4.69, 42.58) differ by 0.07 to 0.13 points. "Data error"
for 2020-2022 in the paper: the forecast covers part of the fleet then (warning in
`datapackage.yaml`).

Zsiborács Table A5, CH day-ahead wind: downward need = energy produced above the forecast,
upward need = forecast energy not produced, each as a share of the year's actual energy. The
downward need matches to 0.05 in 2015-2018 (18.9, 22.8, 17.6, 15.5); the other values differ by
0.06 to 0.2 points (upward 2015: 46.1 published, 45.9 adele; 2019 downward: 41.5, 41.7). A
plausible cause, not checked: their download (2022) held slightly different values; the Swiss
wind values are small (mean 6 to 10 MW), so a revision of a few tenths of a MW moves the share
(three such revisions in 15 days, `qa/revisions_entsoe_ch.md`).

Kazmi & Tao, CH, 2017-2021 (published wind ME 5.6, MAE 8.9, wMAPE 83, R2 0; solar ME 97, MAE
109.8, WAPE 78.3, R2 0.27): adele gives wind 6.0, 9.1, 81.4, 0.002 and solar 91.6, 104.2, 75.2,
0.272. R2 matches; ME and MAE differ by up to 6 MW, as their undescribed filter of 5-10 % of the
values ("missing" and "anomalous measurements") would allow. With the actual one hour later the
solar MAE is 109.0 and WAPE 78.7, nearer, but R2 0.249.

## Checks that read entsoe_generation (2026-11-16)

Renaud allowed checks that read another dataset (D34, 2026-11-16). Run again with adele's own
actual: the backfill of `entsoe_generation` in the worktree `wp5.2` (WP5.2, 2026-11-15), read
through links in a test catalog of the session's scratchpad. The values above are those of the
swissgrid project's copy; adele's actual gives the same matches, and one more: Table A5, 2016
upward, 36.08 against 36.1 (the swissgrid project's copy was further off). 14 checks:

| figure | published | adele |
|---|---|---|
| Zsiborács 2022 T3, wind DA 2017, with an actual value | 99.7 | 99.74 |
| Zsiborács 2023 T2, solar DA 2017, with an actual value | 99.7 | 99.74 |
| Zsiborács 2022 A5, wind downward 2015, 2016, 2017, 2018 | 18.9, 22.8, 17.6, 15.5 | 18.87, 22.79, 17.56, 15.54 |
| Zsiborács 2022 A5, wind upward 2016 | 36.1 | 36.08 |
| Zsiborács 2023 T6, solar 2015 downward, upward | 9.4, 37.5 | 9.36, 37.55 |
| Zsiborács 2023 T6, solar 2017 upward | 16.6 | 16.60 |
| Zsiborács 2023 T6, solar 2019 downward, upward | 5.3, 12.0 | 5.31, 11.97 |
| Kazmi & Tao, R2 2017-2021, wind, solar | 0, 0.27 | 0.002, 0.272 |

Still different with adele's actual: A5 upward 2015, 2017, 2018 and both values of 2019 (0.06
to 0.2 points); T6 2016, 2017 downward and 2018 (0.07 to 0.13 points). The 2015 upward value of
T6 (37.55 against 37.5) lies 0.004 inside the tolerance: a revision of a few MW would make it
fail.

These checks fail while `entsoe_generation` is not in the catalog: WP5.3 lands after WP5.2.

## Left out

- ENTSO-E & SPE 2015, p. 14: the CH row gives 0 MW for the forecast and "Cloudier than
  forecast" as its comment: not reported. adele: 84.95 MW at 11:00 UTC.
- Papers on the Swiss PV forecast of Swissgrid (PV4Balancing, ElCom reports): no figure of the
  ENTSO-E series.
