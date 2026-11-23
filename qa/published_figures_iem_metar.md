# Published figures for iem_metar

Collected and compared by Claude on 2026-11-23 (skills/add-dataset, step 8). Renaud had no report of
his own with figures from METAR ("search yourself, or query a website").

## Checks (datasets/iem_metar/checks.yaml)

- MeteoSwiss, Technical Reports 277 (Zurich) and 278 (Geneva), 2021: "Aeronautical Climatological
  Information", computed from the half-hourly METAR (:20 and :50) of 1994-2020, without AUTO
  reports. Of the dated extremes, the three that fall in adele's period match: QNH 1044 hPa at
  LSZH on 2016-12-27 18:20 UTC, QNH 1041 hPa at LSGG on 2016-12-27 20:20 UTC, temperature 39 degC
  at LSGG on 2015-07-07 12:50 UTC.
- SUST (Swiss Transportation Safety Investigation Board) reports that quote METARs word for word:
  HB-WZB (LSZB 2021-03-04 13:50 UTC) and D-FLIC (LSZH and LSZR, 2022-03-30 10:20 UTC). The stored
  texts are equal to the quotes (ceiling, lowest base, visibility, dew point as 6 checks).

Not used: the other statistics of the two MeteoSwiss reports (frequency of fog, ceiling, visibility,
average pressure, wind), because they cover 1994-2020 without AUTO, and IEM holds genuine METAR text
only from 2013 on (measured 2026-11-23 on LSZH and LSGG: share of the rows that IEM rebuilt from
another archive, without cloud groups: 100 % in 1994-2002 and 2004-2009, 50 % in 2003, 94 % in 2010,
73 % in 2011, 34 % in 2012, 0 % in 2013 and 2014). They can't be reproduced from this source.

## Comparison with ogimet.com

`qa/tools/ogimet_compare_iem_metar.py` takes one day of eight years (a fixed seed), all 8 stations:
2,804 reports at both, 0 at only one of them. 2,781 texts are equal, 23 differ:

- 16: ogimet cuts a long text (RVR groups plus snow and fog, 2026-01-21) and IEM holds all of it.
- 7: the two archives hold another version of the report for the same time. Example LSZB
  2015-10-21 06:20: "19002KT ... M02/M02 Q1020 NOSIG" at IEM, "VRB03KT ... M01/M01 Q1020 TEMPO 0800
  FZFG" at ogimet. Others: LSZB 2015-10-21 06:50; LSZB 2016-08-06 03:20 (AUTO NCD at IEM, a manual
  FEW110 at ogimet); LSZG 2016-08-06 06:50 and 07:20; LSZH 2021-09-28 12:50 (AUTO at IEM, manual at
  ogimet); LSZH 2026-01-21 06:20 (BKN002 at IEM, FEW001 at ogimet). So about 0.25 % of the reports
  exist in two versions, and which one IEM keeps is not known.

The two archives probably receive the same international feed (the gaps are the same), so this tests
that IEM's text is kept as received; it does not test the feed against the aerodromes.

## Comparison with SwissMetNet

`qa/tools/crosscheck_iem_metar_smn.py`, 2026 (recent 10-minute files, `tre200s0`), 2026-01-01 to
2026-11-23, about 15,600 pairs per station (LSMP 15,080). METAR temperature (whole degrees) minus
SMN temperature, smallest standard deviation over lags of -60 to +60 min:

| aerodrome - SMN station | bias at lag 0 (degC) | sd at lag 0 (degC) | lag of the smallest sd |
|---|---|---|---|
| LSZH - KLO | +0.01 | 0.51 | 0 min |
| LSGG - GVE | +0.21 | 0.58 | 0 min |
| LSMP - PAY | +0.16 | 0.77 | -10 min (0.71) |
| LSZG - GRE | -0.03 | 0.40 | 0 min |

Rounding to whole degrees alone gives a sd of 0.29. The stamps of the four stations are UTC and right
to within 10 minutes. Not tested: the cloud data, the wind, the 4 other stations.
