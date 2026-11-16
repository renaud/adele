# Published figures for the MeteoSwiss station datasets (WP5.7)

Collected and compared by Claude on 2026-11-15 and 2026-11-16 (skills/add-dataset, step 8). The
checks of each dataset are generated from the figures that match:
`qa/tools/write_checks_meteoswiss.py` writes `datasets/<id>/checks.yaml`.

## Sources

MeteoSwiss's climate bulletins (Klimabulletin), the PDFs that the swissgrid project keeps in
`data/events/raw_nosync/` (URLs in `qa/klimabulletin_urls.csv`). MeteoSwiss computes them from the
same station data.

| figures | from | how they were read |
|---|---|---|
| 191 yearly | the tables "Jahreswerte an ausgewählten MeteoSchweiz-Messstationen" of 2015-2018, 2020, 2021, 2023, 2024: temperature (0.1 °C), sunshine (h) and precipitation (mm) at 8 stations | typed by Claude from the images of the PDFs (`qa/published_figures_meteoswiss_typed.csv`). Samedan's precipitation of 2018 is left out: the bulletin says it was replaced by Segl-Maria |
| 24 monthly | the same table for March 2025 | typed, as above |
| 640 monthly | May 2025 to September 2026: Tabelle 1 to 3 (temperature, precipitation, sunshine at 11 to 13 stations, to 0.1) | from the text of the PDFs (`qa/tools/klimabulletin_figures.py` --> `qa/published_figures_meteoswiss_text.csv`) |
| 19 monthly | record sentences of 2025-2026 ("Braunwald 45.0 mm (bisheriger Rekord ...)") | typed |
| 8 monthly | the largest fresh snow of one day (Arosa 65 cm in December 2023, Luzern 42 cm in November 2024, ...) | typed |

The yearly tables of 2019 and 2022 are not in the swissgrid project's folder. No figure was found
for meteoswiss_obs_daily (the bulletins don't count fog or snow-cover days) or for
meteoswiss_smn_stations.

## How each figure is computed

`qa/tools/published_check_meteoswiss.py <data_dir>` computes each figure in every way that could be
meant, and writes `qa/published_figures_meteoswiss_matched.csv`. A variant matches within half a
unit of the last published digit (0.05 or 0.5). A month or a year is the days whose
reference_date falls in it (MeteoSwiss's daily values, UTC dates), or the hours of the UTC period.

Matches per variant (figures that the variant could compute; 2026-11-16):

| figure | variant | months | years |
|---|---|---|---|
| temperature | daily: mean of the daily means | 231 / 231 | 64 / 64 |
| temperature | hourly: mean of the hourly means | 211 / 231 | 61 / 64 (2015-2017 included) |
| sunshine | daily: sum / 60 | 220 / 221 | 61 / 64 |
| sunshine | hourly: sum / 60 | 219 / 221 | 60 / 64 |
| sunshine | tenmin: sum / 60 (from 2023-10) | 219 / 221 | 8 / 8 |
| precipitation | daily_06utc: sum of precipitation_06utc (days of 06 to 06 UTC) | 223 / 230 | 61 / 63 |
| precipitation | daily_utc: sum of precipitation (UTC days) | 143 / 230 | 33 / 63 |
| precipitation | hourly_06utc: hours from 06 UTC of the first day to 06 UTC after the period | 220 / 230 | 58 / 63 |
| precipitation | nime: the manual network, same abbreviation | 203 / 230 | 61 / 63 |
| fresh snow, largest day | nime_max | 8 / 8 | |

So MeteoSwiss's monthly and yearly precipitation is the sum of the days of 06 to 06 UTC
(rre150d0), not of the UTC days: this is now in the description of precipitation_06utc. The
manual network's precipitation equals SwissMetNet's at the stations that are in both.

## Checks written

| dataset | checks | run time of `adele-server check` |
|---|---|---|
| meteoswiss_smn_daily | 859 | 24.5 s |
| meteoswiss_smn_hourly | 762 (figures from 2018 only: before, an hour runs from minute 40 and a year of hours doesn't start on 1 January 00:00) | 21 s |
| meteoswiss_nime_daily | 272 (264 precipitation, 8 fresh snow) | 8.6 s |
| meteoswiss_smn_tenmin | 227 | 6.4 s |

Every figure that matches the variant of a dataset is a check (the rule of step 8); the checks run
after each fetch, once a day. If that is too many, the generator can keep a subset.

## Figures that differ

Daily table and manual network (the variants that MeteoSwiss uses):

| figure | published | adele | reading |
|---|---|---|---|
| Le Moléson (MLS), precipitation December 2025 | 0.4 mm | 25.9 mm | the stored days 4 to 8 December hold 25.9 mm. The bulletin came out before MeteoSwiss's check by hand of December's precipitation (around the end of January): probably corrected after it. Unverified |
| Genève (GVE), precipitation 2023 | 1016 mm | 1024.7 mm | the manual network gives the same 1024.7 mm. Probably a correction after the bulletin. Unexplained |
| Sion (SIO), precipitation 2017 | 567 mm | 565.3 mm | same in the manual network. Unexplained |
| Genève (GVE), sunshine November 2025 | 98.6 h | 100.8 h | hourly gives 100.8 h too. Probably a correction after the bulletin. Unexplained |
| GVE 2015, GVE 2016, BAS 2017, sunshine of the year | 1996, 1821, 1844 h | 1995.4, 1820.35, 1843.45 h | 0.55 to 0.65 h. A sum of monthly values rounded to the hour gives 1996 for GVE 2015 but not the other two. Unexplained |
| Braunwald, precipitation September 2026 | 45.0 mm | | not a station of SwissMetNet or of the manual network |

Hourly table, against the same figures (not checked where it differs):

- Temperature: in 20 months the mean of the hourly means is 0.05 to 0.07 °C above the published
  monthly mean (always above; BER, GVE, SIO, DAV, BAS and others, 2025-2026), while the mean of
  the daily means matches every figure. Unexplained: MeteoSwiss's daily mean is not exactly the
  mean of its 24 hourly means.
- Precipitation and sunshine: the hourly table misses values that the daily table holds. Basel
  2024: 802.3 mm against 831; Engelberg May 2025: 163.9 mm against 213.7; Zürich/Fluntern 2021:
  1108.8 against 1127; Samedan 2020: 724.8 against 734; Locarno/Monti June 2025: 254.8 h of sun
  against 262.4 (the 10-minute table gives 254.8 h too); Zürich/Fluntern 2016: 1629.7 h against
  1642. Gaps of MeteoSwiss's hourly and 10-minute files: for totals, use the daily table (a
  warning of both datasets).
