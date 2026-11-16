# Published figures for entsoe_wind_solar_forecast_neighbours

Collected 2026-11-15 by Claude (WP5.3), at Renaud's request ("try to find some, either in other
projects, or on the web"; he has no documents of his own with such figures). Sources: two web
searches by research agents (38 and 18 searches), the literature PDFs of `predico_enlab`
(`docs/literature_review/pdfs/`), and the PV paper of Zsiborács et al. 2023, which Renaud
downloaded (`adele/tmp/`, IEEE Xplore refused automated fetches). Compared with adele the same
day with `qa/tools/published_check_entsoe_wind_solar_forecast_neighbours.py <data_dir>` on the
backfill of the worktree `wp5.3` (2015 to 2026-11-17; 176 comparisons in the first run, 222 with
the PV paper).

`datasets/entsoe_wind_solar_forecast_neighbours/checks.yaml` holds 100 checks, written by a
one-off generator (`gen_checks_neighbours.py` in the session scratchpad); edit the file directly
from now on. A run of `adele-server check` takes about 12 s on the Mac.

## Sources

| source | what | URL |
|---|---|---|
| Ben Amor & Ziel 2026, arXiv 2512.04690v2 | Appendix, Table 7: descriptive statistics (mean, std, min, quartiles, max) of the German day-ahead wind (onshore + offshore) and PV forecasts from the Transparency Platform, hourly, 2018-10-01 to 2022-01-14 and 2022-01-15 to 2025-01-13 | https://arxiv.org/html/2512.04690 |
| ENTSO-E & SolarPower Europe 2015, "Solar eclipse March 2015" | p. 14: day-ahead PV forecast per TSO at 12:00 CET on 2015-03-20 | https://eepublicdownloads.entsoe.eu/clean-documents/Publications/ENTSO-E%20general%20publications/entsoe_spe_pp_solar_eclipse_2015_web.pdf |
| Zsiborács, Pintér, Vincze & Baranyai 2022, Sustainability 14(24):16446 | Tables 3 and 4: completeness (%) of the DA and ID onshore and offshore wind forecasts per country and year, 2013-2021 | https://www.mdpi.com/2071-1050/14/24/16446 |
| Zsiborács, Vincze, Pintér & Hegedűsné Baranyai 2023, IEEE Access 11 | Table 2 (p. 74959, an image): the same for PV, 2013-2022 | https://doi.org/10.1109/ACCESS.2023.3297494 |
| Canaydin, Mascarenhas & Kazmi, "Transparency++", EFC 2025 slides | slide 13: missing values (%) in 2024; slide 15: FR offshore forecast "Constant Value (240 MW) (Dec 30-Jan 4)" | https://efc.pwr.edu.pl/assets/EFC25/Canaydin.pdf |
| pv magazine, 2026-09-09 | Italian solar against the day-ahead forecast, June-August 2026: "83 of the 91 days that carried one" | https://www.pv-magazine.com/2026/09/09/italian-solar-redrew-the-day-but-gas-still-sets-the-price/ |

## Result (2026-11-15)

**Ben Amor & Ziel, Table 7: all 28 figures match on the sum of the four German TSO areas** (hours
as the mean of their quarter-hours, the periods read as local days with the end included, GW
although the table writes MWh). DE_LU matches the first period (it equals the four areas then)
but not the second: from 2022 it holds Luxembourg too (wind mean 15.47 against 15.4, wind max
50.45 against 50.3). So their "Germany" is the four TSO areas (the country). 24 figures are
checks; the PV minimum and first quartile (0.0) are left out.

**Eclipse 2015, at 11:00 UTC** (12:00 CET read as the start of the interval): Germany (four TSO
areas) 21,998 MW against 22,000; FR 2,324 against 2,300; AT 416 against 400. Checks, with the
tolerance of their rounding (1,000 and 100 MW). **Italy differs, and that is a finding:** the zones
give 9,650 MW, the published forecast is 7,500, and the same table gives 9,653 MW as Italy's
estimated real PV infeed at that hour. A warning in `datapackage.yaml`. Switzerland's row (0 MW,
"Cloudier than forecast") is not reported.

**Zsiborács, completeness.** Their share counts an interval only when the actual value exists too;
this dataset has no actual, so a figure matches when the actual had no hole. Germany = the bidding
zone (DE_AT_LU, then DE_LU), FR = the bidding zone, local years (Brussels). AT intraday 2018 (wind
58.2, PV 58.6: the intraday forecast starts on 2018-06-01) matches in local years only.

| | match (checks) | differ |
|---|---|---|
| AT wind | DA 2015, 2017-2021; ID 2018-2021 | DA 2016 (99.4 published, 100 adele) |
| AT PV | DA 2015, 2017-2022; ID 2018-2022 | DA 2016 (99.5, 100) |
| DE wind onshore | DA 2015-2021; ID 2015-2017 | ID 2018-2021 (98.9, 97.5, 99.4, 95.6; adele 99.6, 100, 100, 100) |
| DE wind offshore | DA 2015-2021; ID 2015, 2016, 2018-2021 | ID 2017 (99.7, 100) |
| DE PV | DA 2015-2017, 2019-2022; ID 2015-2017 | DA 2018 (99.4, 100); ID 2018-2022 (99.2, 97.5, 99.2, 95.9, 99.2; adele 100) |
| FR wind | DA 2015, 2017, 2021; ID 2018, 2019, 2021 | DA 2016, 2018-2020 (0.07 to 0.75 below adele); ID 2020 (69.8, 69.87) |
| FR PV | DA 2015, 2017, 2020; ID 2018-2021 | DA 2016, 2018, 2019, 2021, 2022 (0.05 to 0.4 below adele); ID 2022 (92.1, 92.23) |
| IT wind | DA 2020 (4.4: IT starts 2020-12-15); ID 2021 | DA 2021 (98.9, 99.7) |
| IT PV | DA 2019, 2020 | DA 2021 (92.1, 100), 2022 (99.2, 99.7) |

Every published figure that differs is below adele's, as holes in the actual (or in their
download) would make it. Two patterns: 2016 differs for AT and for CH (entsoe_wind_solar_forecast)
in both papers, so their 2016 download probably missed a day or two; the German intraday differs
in every year from 2018, in both papers, probably their country-level series (adele has the
bidding zone). Unexplained in detail; the FR and IT differences can't be tested without the actual
of those areas, which no dataset of adele holds.

**Transparency++, slide 15: matches.** The FR offshore forecast is exactly 240 MW from 2023-12-30
08:00 to 2024-01-04 03:00 UTC (116 hours), in the day-ahead, intraday and current forecasts, and
in shorter runs from 2023-12-24. Check: the most frequent value over the local days 2023-12-30 to
2024-01-04. A warning too.

## Left out

- Transparency++, slide 13 (missing values in 2024): FR 0.01 % matches (adele 0.011 %: one hour),
  DE-LU does not (solar 0.55 %, wind 0.27 %; adele 0.011 %). Their resolution, zone of the year and
  meaning of "missing" are not stated; DE-LU's gaps may have been filled since their download.
- pv magazine: 91 days of June-August 2026 with an IT day-ahead solar forecast; adele has all 92.
  The missing day was probably filled since (or the author's aggregation dropped one).
- IEA-PVPS T14-06:2016 (the eclipse in Germany), Figure 3: values per TSO read from a graph only.
- Sollami, Politecnico di Torino thesis (Italian forecasts of 2017): none of six values matches
  (one wind value is close: 5,485 against 5,488 MW); the thesis took Terna's data, not ENTSO-E's.
- Kazmi & Tao 2022 and Zsiborács (regulation needs per country), Kean et al. 2026, pv magazine
  (MAE 664 MW): forecast errors; they need the actual generation of these areas, which adele does
  not hold.
- Hirth, Mühlenpfordt & Bulkeley 2018: they assess no article 14.1.D item.
