# Published figures for entsoe_balancing_state

Collected 2026-11-15 by a research agent, compared with adele on 2026-11-16 by Claude. **No
check**: the figures found are computed on other data. Comparison script:
`qa/tools/published_check_wp51.py`.

## Source

ENTSO-E's LFC annual reports (2019, 2021, 2022, 2023, 2025), tables "LFC Block Performance for
Block SG": per month and year, the mean, standard deviation and percentiles of Swissgrid's FRCE
averaged over 15 minutes, and counts beyond Level 1 and Level 2. They are computed on the FRCE
that Swissgrid delivers to ENTSO-E for the LFC report, not on the B33 series of the Transparency
Platform. Sign convention and month boundaries not stated.
https://eepublicdownloads.entsoe.eu/clean-documents/SOC%20documents/LFC/ALFC_report_2025.pdf
(2024 and 2025), https://neso.energy/document/324231/download (2022 and 2023),
https://neso.energy/document/267971/download (2020 and 2021).

## Comparison (2026-11-16)

adele's 15-minute means of `control_error`, with its sign (> 0 = long), against the reports:

- 2023, month by month: the mean and the standard deviation agree in every month but one
  (February, the month of a large event: mean 0.7 and 22.3 MW against 0.7 and 23; June 10.4
  against 10). November differs: 134.6 MW against 6. So the spike of 2023-11-28 (up to 2,700 MW)
  is not in Swissgrid's FRCE: an error of the B33 publication.
- 2024: mean and every yearly percentile within 0.3 MW (p1 -17.3 against -17, p99 14.7 against
  15). July 2024 has a standard deviation of 105.2 MW in adele and 108 in the report: the spike
  of 2024-07-13 (up to 4,000 MW) is in Swissgrid's FRCE too. The report's yearly standard
  deviation (14) is inconsistent with its own July (a month at 108 MW forces at least about
  31 for the year; adele: 31.2).
- January to May 2025: percentiles within 0.6 to 1.5 MW; the wide February 2025 is reproduced
  (p1 -23.0 against -23, p99 30.0 against 30).
- 2020-2022: the lower percentiles agree within 0.4 to 2.3 MW, the upper ones are wider in adele
  (p99 about 20 against 15, p95 10.5 to 11.7 against 9). Unexplained: a different processing of
  B33 before 2023, or a difference between B33 and FRCE.

The figures follow the same quantity closely (and confirm the sign in 2022-2025), but a check
needs figures computed from the same data: none is written. The warning of the descriptor was
corrected on 2026-11-16: 2023-11-28 is an error of B33, 2024-07-13 is also in Swissgrid's FRCE.
