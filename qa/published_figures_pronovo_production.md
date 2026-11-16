# Published figures against pronovo_production

Written 2026-11-15 and 2026-11-16 by Claude (WP5.5, `skills/add-dataset`, step 8), with two
research agents for the web search (30 searches). Scripts: `qa/tools/published_check_pronovo_production.py
<data_dir>` (Pronovo's sums, BFE's monthly balance) and `qa/tools/rmp_checks_pronovo_production.py
<csv>` (writes the checks of BFE's reference market prices), on the latest versions of the
backfill of 2026-11-15 (on the Mac, worktree wp5.5). The figures that match are the 168 checks
of `datasets/pronovo_production/checks.yaml`; `adele-server check pronovo_production` passes.

## Sources

| source | figures | match | in checks.yaml |
|---|---|---|---|
| BFE, reference market prices (Art. 15 EnFV), monthly volumes computed from these files: PV, wind, hydro, biomass, 2023-07 to 2026-09 | 156 | 156 (within 0.5 MWh) | 156 |
| BFE, reference market prices of PV 2018 to 2023/2 (publication of 14 September 2023), quarterly volumes | 14 quarters of 2020 to 2023/2 | 3 | 3 |
| Pronovo, `Lastgangprofile_11.2020.csv`, last row: the sum of each column over the file, kWh to 0.01 | 8 (one per technology, local month of November 2020) | 8 | 8 |
| BFE, "Elektrizitätsbilanz der Schweiz - Monatswerte, in GWh" (updated 30.10.2026), nuclear, hydro, wind, PV per month 2023-01 to 2026-08 | 3 yearly totals of nuclear, compared month by month | 2023 (within 1 %) | 1, with a tolerance of 1 % |
| Pronovo, hydro by size class (2026-08, 2026-09) | 7 types per month | 3 types to the kWh (2026-09) | 0 |

## BFE's reference market prices: volumes computed from these files

BFE's method note "Berechnung der Referenz-Marktpreise gemäss Art. 15 EnFV", section 3.3
(https://pubdb.bfe.admin.ch/de/publication/download/11467, read by Claude): BFE uses Pronovo's
"Lastgangprofile nach Technologien", the version that Pronovo re-publishes after each quarter,
and "die Nettoproduktion ... dass die Hilfsspeisung (+A) von der Bruttoproduktion (-A) abgezogen
wird". Biomass is Biogas, Übrige Biomasse, Holzenergie, Kehrichtverbrennung (erneuerbar) and
Klärgas; hydro is Abwasser-, Ausleit-, Dotierwasser-, Durchlauf- and Trinkwasserkraftwerk.

The monthly volumes, whole MWh: https://www.bfe-ogd.ch/ogd60_rmp_monatspreise.csv (39 months,
2023-07 to 2026-09, last changed 2026-10-13, the day of Pronovo's definitive file of 2026-Q3).
On adele's local months, with production_mwh - auxiliary_mwh and the same categories, all 156
figures match; the largest differences are 0.489 (PV), 0.49994 (wind), 0.495 (hydro) and 0.492
MWh (biomass). They include Sep 2024, the national PV that misses plants: BFE used the national
file as it is.

The publication of 14 September 2023 (https://pubdb.bfe.admin.ch/de/publication/download/9319)
gives the PV volume per quarter from 2018 to 2023/2, of the plants with load-profile metering,
without saying net or gross. Against adele's -A alone:

| quarter | BFE (MWh) | adele (MWh) | difference |
|---|---|---|---|
| 2020/1 | 218,425 | 219,790.2 | +0.63 % |
| 2020/2 | 519,526 | 509,482.8 | -1.93 % |
| 2020/3 | 481,904 | 465,394.1 | -3.43 % |
| 2020/4 | 138,523 | 133,846.7 | -3.38 % |
| 2021/1 | 210,771 | 204,630.1 | -2.91 % |
| 2021/2 | 618,610 | 604,249.6 | -2.32 % |
| 2021/3 | 573,427 | 563,612.6 | -1.71 % |
| 2021/4 | 171,824 | 165,124.8 | -3.90 % |
| 2022/1 | 314,619 | 309,670.3 | -1.57 % |
| 2022/2 | 730,299 | 723,725.6 | -0.90 % |
| 2022/3 | 718,445 | 718,444.9 | 0.1 MWh |
| 2022/4 | 206,335 | 204,919.9 | -0.69 % |
| 2023/1 | 288,183 | 288,182.7 | 0.3 MWh (net: -0.27 %) |
| 2023/2 | 818,110 | 818,110.4 | 0.4 MWh (net: -0.10 %) |

So the old method used -A alone, and from 2022/3 BFE had the files that adele has. For the
other quarters of 2020-2022, adele's files (the monthly CSVs of Pronovo's archive, equal to the
annual files) hold 0.7 to 3.9 % less PV than BFE computed, except 2020/1 (+0.6 %). Unexplained:
the CSVs carry the evaluation date of the first publication ("Datum der Auswertung" about two
weeks after each month), so BFE may have had another delivery from Pronovo. Not checks.

## Pronovo's own sums (November 2020)

The monthly CSV of November 2020 ends with a row without a stamp that holds the sum of each
column, in kWh with a thousands mark (`43'641'532.89`). The file runs from the local end stamp
01.11.2020 00:15 to 01.12.2020 00:00, so the sums cover the local month (Europe/Zurich). No other
file of 2020-2022 has such a row, and the zips of 2023 on have none.

| technology | published (kWh) | adele, local month (kWh) | adele, UTC month: difference (MWh) |
|---|---|---|---|
| pv | 43,641,532.89 | 43,641,532.891 | -0.021 |
| biogas | 21,661,585.33 | 21,661,585.332 | +0.650 |
| biomass_energy_crops | 3,758,469.82 | 3,758,469.819 | +0.283 |
| biomass_forest_agri_waste | 36,123,148.64 | 36,123,148.641 | -9.556 |
| waste_renewable | 74,632,833.63 | 74,632,833.633 | -24.596 |
| sewage_gas | 8,901,888.54 | 8,901,888.541 | +0.017 |
| hydro_total | 2,567,842,038.51 | 2,567,842,038.508 | -931.109 |
| wind | 9,591,835.92 | 9,591,835.918 | -4.520 |

What they test: the parse of the archive CSVs (the thousands mark, kWh to MWh), the end stamps
(stamp - 15 minutes) and the zone of the month. They are the source's own arithmetic on the same
file, so they can't test what the values mean.

## BFE's monthly balance: the same quantities from other data

BFE, "Elektrizitätsbilanz der Schweiz - Monatswerte, in GWh", sheet Tabelle1 (updated
30.10.2026, values of 2020-2025 revised), https://pubdb.bfe.admin.ch/de/publication/download/5634.
Net production per calendar month, whole GWh. The nuclear comes from the operators (it sums to
swissnuclear's 18.4 TWh net for 2025, press release of 2026-03-09,
https://swissnuclear.ch/wp-content/uploads/2026/04/20260309_MM-Produktionszahlen-2025.pdf; read by
the research agent, not again by Claude). The monthly PV and wind come
"from Pronovo AG's certificate of origin database" (BFE factsheet,
https://pubdb.bfe.admin.ch/en/publication/download/12194, p. 2), and the yearly PV is scaled to
Statistik Sonnenenergie (2025: 7,948 GWh). So none of them is computed from these files.
Compared on the local months of adele, every row (the rows marked `suspect` included).

**Nuclear.** Pronovo's nuclear is 1.000 to 1.014 times BFE's in every month from 2023-01 to
2026-08, except three:

| month | BFE (GWh) | Pronovo (GWh) | ratio | nuclear capacity in the file (MW) |
|---|---|---|---|---|
| 2024-09 | 2,067 | 1,357 | 0.657 | 1,980 |
| 2025-02 | 1,970 | 1,298 | 0.659 | 1,980 |
| 2025-03 | 2,180 | 1,440 | 0.660 | 1,980 |
| 2025-09 | 1,117 | 1,118 | 1.001 | 1,980 |
| other months | | | 1.000 to 1.014 | 3,015 |

One unit of about 1,035 MW is missing from the files of Sep 2024, Feb 2025 and Mar 2025: the
energy is two thirds of BFE's. In Sep 2025 the file lists 1,980 MW too, but its energy matches:
the missing unit produced nothing that month (Gösgen has been off since its revision began on 24
May 2025, according to the same press release, as read by the agent; BFE's nuclear falls from
about 1,900 to about 1,100 GWh a month from May 2025). This answers the open question of the swissgrid project (an outage, or a
unit missing from the file?): missing from the file. These three months are marked
`nuclear_missing_unit`. Yearly: 2023 BFE 23,334, Pronovo 23,369 (1.001), a check with a
tolerance of 1 %; 2024 22,983 against 22,296 (0.970) and 2025 18,379 against 17,002 (0.925),
left out because of the missing unit.

Pronovo calls its profiles gross production, yet its nuclear equals BFE's net production: the
register -A seems to be the energy delivered at the grid connection, the plant's own use
during production already deducted (inference).

**Hydro.** Pronovo holds 0.76 to 0.94 of BFE's hydro in a month, but 0.587 in Sep 2024, 0.676
and 0.672 in Feb and Mar 2025, and 0.623 in Sep 2025: plants are missing from those files for
hydro too. Not marked: there is no capacity per plant to say which. In the warnings.

**Wind.** Monthly 0.81 to 1.09; yearly 2023 1.002 (169 GWh against 169.3), 2024 0.943 (171 against
161.3), 2025 0.973 (161 against 156.7). The match of 2023 is within the rounding, but the other
years differ by 3 to 6 %, so it is not a check.

**PV.** 0.40 to 0.58 of BFE's in a month (about half of the fleet), lowest in the third month of
a quarter (Jun 2023 0.421, Dec 2023 0.416, Jun 2024 0.418, Sep 2025 0.395, Dec 2025 0.459):
Pronovo's set of plants drops there (warnings), BFE's monthly shape doesn't. Sep 2024: 0.286,
the national PV that misses plants (`pv_national_missing_plants`). Not a check.

## Pronovo's hydro files by size class (2026-08 and 2026-09)

Next to the zips of every technology, the current folder holds `YYYYMM_CH_Wasserkraft_Monat_prov.zip`
(from 2026-08): one xlsx per hydro type and one with all types, each type in four size classes
(+A, -A, Leistung, Anzahl, same format as the CSVs). Read from the swissgrid project's copies
(script in the session's scratchpad, not in the repo), summed over the four classes.

September 2026 (file created 2026-10-23, ten days after the definitive file of Q3), against the
definitive September in adele:

| technology | file (MWh) | adele (MWh) | difference | file: MW, plants | adele: MW, plants |
|---|---|---|---|---|---|
| hydro_wastewater | 786.985 | 786.985 | 0 | 4.07, 15 | 4.06, 14 |
| hydro_residual_flow | 16,478.332 | 16,478.332 | 0 | 73.9, 56 | 70.6, 46 |
| hydro_pumped_storage | 1,011,007.064 | 1,011,007.064 | 0 | 8,694.8, 25 | 8,030.6, 22 |
| hydro_storage | 599,552.414 | 599,558.138 | -5.7 | 4,052.3, 112 | 3,566.3, 100 |
| hydro_drinking_water | 14,364.118 | 14,363.100 | +1.0 | 61.4, 476 | 59.7, 400 |
| hydro_diversion | 353,705.163 | 351,151.170 | +2,554 (0.7 %) | 2,502.4, 465 | 1,954.9, 379 |
| hydro_run_of_river | 278,013.575 | 273,713.671 | +4,300 (1.6 %) | 1,801.3, 372 | 1,671.6, 294 |

So the size-class files break down the same meter data: three types match to the kWh. They list
more plants and more capacity in every type (the national file of the same month lists fewer),
and for diversion and run-of-river a little more energy: plants that the national file lacks,
it seems. August 2026 (file created 2026-09-09, before the definitive file): 2 to 25 % less
energy than the definitive August in adele (storage 616 GWh against 796), the size of the late
deliveries for hydro.

Not checks yet: the sums are computed here from Pronovo's quarter-hours, not published as
figures, and the files are labelled provisional. A check on the three types that match would
catch a re-issue of the definitive file of 2026-Q3.

## Searched, not usable

Searched on 2026-11-15 and 2026-11-16 by two research agents (18 and 12 web searches); read
again by Claude: BFE's monthly balance, the method note and both publications of the reference
market prices. The rest is as the agents reported it.

- BFE, Statistik der erneuerbaren Energien 2025 (https://pubdb.bfe.admin.ch, publication 12782),
  wind 2020-2025: 145.45, 144.98, 149.72, 168.53, 170.54, 160.63 GWh, source "Pronovo" from 2021.
  adele (-A): -0.8, -1.9, +0.5, +0.5, -5.4, -2.5 %. 2024 differs from BFE's own volume of the
  reference market price (160.3 GWh, which matches adele), so the statistic has another basis.
  Biogas (agriculture, industry, industrial wastewater, "Engeli, Pronovo"): 294.1, 298.1, 300.9
  GWh in 2023-2025 against adele's 330.0, 315.8, 321.6. Sewage gas, wood, waste incineration and
  hydro come from other surveys. Not checks.
- BFE, Elektrizitätsstatistik 2025 (publication 12681): wind 145 to 171 GWh per year as above;
  peak power on the third Wednesday of each month (PV 3,855 MW on 16.7.2025): national, no source
  named. Not checks.
- Pronovo-Cockpit of January 2026 (https://pronovo.ch/?wpdmdl=17681, p. 17): plants registered in
  the guarantee-of-origin system on 31.12.2025, PV 317,404 plants and 8,148 MW, wind 71 and 100,
  hydro 1,514 and 17,207, nuclear 4 and 3,015. Every registered plant, not only those with
  15-minute metering (adele: 115,601 PV plants in Dec 2025). Not checks.
- Energy-Charts names "Pronovo (1/4 hour values)" as its source for Swiss renewables; no values
  taken. Suisse Eole: 161 GWh of wind in 2025, 170 in 2024, no source named.
- No paper or thesis that prints totals from these files was found (searches in German, French
  and English). opendata.swiss: no dataset from these files.
- Not read: Pronovo's raw data of issued guarantees of origin (2024:
  https://pronovo.ch/?wpdmdl=14152&ind=0, 2025: https://pronovo.ch/?wpdmdl=16733&ind=0), larger
  than WebFetch can load; a download needs a script in the main session. Issued guarantees are
  net and count every registered plant.
- No figure computed by others from these files was found in the first search; the second found
  BFE's reference market prices (above).
- Statistik Sonnenenergie 2025 (https://pubdb.bfe.admin.ch/de/publication/download/12679, pp. 6
  and 27): a specific yield of 900 kWh/kW in 2025 and 820 in 2024, from Pronovo's plants above
  30 kVA with metering that delivered all 12 months. Another set of plants, and kW against our
  kVA: not a check. Its production (7,948 GWh in 2025) is capacity times that yield.
- ENTSO-E's Swiss PV: Pronovo times a monthly factor (`datapackage.yaml`, warnings).
- BFE energy dashboard (`stromproduktion-swissgrid`, ogd104): PV partly modelled, no Pronovo
  source.
- Pronovo's Geschäftsbericht 2025: no production or capacity figures. HKN-Cockpit 2025: issued
  guarantees of origin, net, without a split by technology in the table.
- Not read: Pronovo's raw data of issued guarantees of origin per energy source and month
  (2024: https://pronovo.ch/?wpdmdl=14152&ind=0, 2025: https://pronovo.ch/?wpdmdl=16733&ind=0),
  the closest monthly figures made by Pronovo, but for another population (net, issued).
