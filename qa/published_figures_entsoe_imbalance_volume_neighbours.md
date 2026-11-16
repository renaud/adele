# Published figures for entsoe_imbalance_volume_neighbours

Collected 2026-11-15 by a research agent (about 29 web searches, then the search limit),
checked against adele on 2026-11-16 by Claude: the 3 checks of
`datasets/entsoe_imbalance_volume_neighbours/checks.yaml` pass. Renaud's own documents: not
asked yet.

## Source and result

ENTSO-E, Balancing Report 2020, section 5.19.2.3 (France), p. 70: "The average system imbalance
is + 390 MWh for an ISP with a positive imbalance and - 350 MWh for a negative imbalance. On
average, the system imbalance is 55 % of the ISP positive and 45 % negative." (2018 and 2019,
half-hour settlement periods.)
https://eepublicdownloads.entsoe.eu/clean-documents/Publications/Market%20Committee%20publications/ENTSO-E_Balancing_Report_2020.pdf

adele, FR 2018-2019 (Europe/Paris years; UTC years give the same): mean of the positive periods
386.3 MWh, of the negative ones -356.2 MWh, 53.8 % positive, 46.2 % negative. With a tolerance
from the rounding (10 MWh and 5 %), the positive mean and the two shares match; the negative mean
differs by 6.2 MWh (unexplained: the report states neither its data nor its rounding). The sign
of adele (> 0 = long) reproduces the report's asymmetry; the opposite sign would give 46 %
positive periods with a mean of 356 MWh.

## Not found

Nothing for AT, DE or IT. The research agent read the ENTSO-E Balancing Report 2020 (no figures
for DE, AT, IT), APG's page on the total imbalance (definition only: > 0 = surplus, MW, "updated
with a two-month delay to final settlement values"), netztransparenz.de (method only), BNetzA's
key findings 2024 (reserves and prices only). Not read (over 10 MB): ENTSO-E Balancing Reports
2022, 2024, 2026, BNetzA Monitoringbericht. Not tried: CRE, Terna, E-Control.
