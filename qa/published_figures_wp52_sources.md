# Published figures for the four WP5.2 datasets (CH, ENTSO-E Transparency Platform)

Collected on 2026-11-15 by a research agent, at the request of the WP5.2 session; its report as
written, kept because it gives every value with its table or page. 12 web searches used. What
adele does with each figure: `qa/published_figures_entsoe_<id>.md`. The ElCom and Swissgrid
figures of section 4 are on Swissgrid's control area balance: candidates for the checks of
`swissgrid_balance` (WP4), not of `entsoe_imbalance_volume`.

Conventions:
- Values are copied as printed. I made two typographic changes: thousands separators (thin spaces in the PDFs, apostrophes in ElCom prose) are written as normal spaces, and minus signs are written as ASCII "-". A blank cell in a source table is written "blank". No value is rounded or converted. Conversions appear only where marked "conversion".
- "read" means I read the value in the document myself. For PDFs, I extracted the text with pdftotext and checked it against a rendered image of the page. For CSV and JSON files, the WebFetch tool quoted the lines to me. "snippet" means that I saw the value only in a search result. Every value below is "read".
- An arrow gives the direction of flow: "CH --> DE" is export from CH to DE.

## Sources

- **S1** ENTSO-E, *Statistical Factsheet* 2019, 2020, 2021, 2022, 2023, 2024, 2025. 2019-2021: `https://eepublicdownloads.entsoe.eu/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs<YEAR>_web.pdf`. 2022-2025: `https://eepublicdownloads.blob.core.windows.net/public-cdn-container/clean-documents/Publications/Statistics/Factsheet/entsoe_sfs<YEAR>_web.pdf`. Cover of every edition: "The Statistical Factsheet is based upon data reported to the ENTSO-E Central Transparency Platform, with the exception of grid statistics."
  - Editions as printed on the cover: 2019 and 2020 "Provisional values as of November 2024" (re-issued, publishing date November 2024); 2021 "as of March 2023"; 2022 "as of June 2023"; 2023 "as of April 2024"; 2024 "as of March 2025"; 2025 "as of June 2026".
  - Generation: PDF page 2, table "ENTSO-E in figures - Electricity system data of member TSOs in <YEAR>", TWh, one decimal.
  - Flows: "Physical energy flows¹" map and "Exchange Balance¹" table (2021: "Exchange Balance per area¹"). They are on PDF page 7 in 2019, 2020, 2024 and 2025, and on PDF page 8 in 2021-2023. Footnote in all seven editions: "¹ Hourly netted physical flow values meansured [sic] in GWh."
  - Time basis: the load tables of all seven editions say "All times are in UTC". No time basis is stated for the annual sums.
- **S2** BFE, *Schweizerische Elektrizitätsstatistik 2025*, https://pubdb.bfe.admin.ch/de/publication/download/12681 (52 pages, German/French). I used Tab. 6 (balance by calendar year), Tab. 7 (production by type), Tab. 28 (commercial foreign trade) and Tab. 29 (physical import and export by country). All are calendar years in GWh; the time zone is not stated.
- **S3** BFE, *Steckbrief "Physikalische Einfuhr und Ausfuhr von Elektrizität der Schweiz nach Ländern"*, https://pubdb.bfe.admin.ch/de/publication/download/12136. It gives the method behind S2 Tab. 29: "Erhebung ... bei der nationalen Netzgesellschaft Swissgrid (für die Höchstspannungsebene). Befragung bei verschiedenen Elektrizitätsunternehmen (für tiefere Spannungsebene bzw. Spezialfälle wie Grenzkraftwerke der Wasserkraft oder Bezug/Abgabe ausländische Versorgungsgebiete)." Revisions: "keine".
- **S4** Energy-Charts, yearly JSON files for CH, `https://www.energy-charts.info/charts/energy/data/ch/year_<YEAR>.json` (2020-2025 read). Fields: datasource "ENTSO-E, BFE", subtitle "Energetically corrected values", unit TWh. The 2025 file adds: "Since January 1, 2025, Swissgrid has only reported incomplete values to the ENTSO-E transparency platform."
- **S5** T. Buckley, M. Schäfer (Universität Freiburg), *Annual imports, exports and balances for European bidding zones*, DOI 10.71694/1b92fgz8, TIB LDM4Energy, created 2025-05-13. Four CSV files (`comm_flows_total_annual_sums_<YEAR>.csv`, 2021-2024). The dataset page says: "All data based on scheduled commercial exchanges as published by ENTSO-E."
- **S6** ElCom, *Bericht Regelleistung und Regelenergie 2023* (Bern, August 2024; ElCom-324-17), https://www.elcom.admin.ch/dam/de/sd-web/jTdazInBkccZ/bericht-regelleistung-regelenergie-2023.pdf, section 1.4, Tab. 1 and Tab. 2. Its 2024 figures cover 01.01.-20.06.2024 only.
- **S7** ElCom, *Bericht Regelleistung und Regelenergie 2024* (2025), https://www.elcom.admin.ch/dam/de/sd-web/xUj0k19ShdkA/Bericht%20Regelleistung%20und%20Regelenergie%202024%20(1).pdf, Tab. 1 and Tab. 2, with the full year 2024.
- **S8** ElCom, *Besondere Ereignisse in der Regelzone Schweiz im Jahr 2025* (Bern, 13 May 2026), https://www.elcom.admin.ch/dam/it/sd-web/lpdgJ8PUh5mk/Bericht%20Besondere%20Ereignisse%20in%20der%20Regelzone%20Schweiz%202025.pdf, section 2.2, Abbildung 1 and Tab. 1. Data: "die öffentlich zugänglichen Control Area Balance (CAB)-Daten von Swissgrid ... Leistung der Schweizer Regelzone in Megawatt (MW) in viertelstündlicher Auflösung ... aus Messungen im 4-Sekunden-Raster ... die mittlere Regelzonenabweichung über das jeweilige Zeitintervall".
- **S9** Swissgrid, L. Loser, *Active Balancing Meeting*, 1 June 2026, slides 12-13, https://www.swissgrid.ch/dam/jcr:185cbf2b-f46d-49ea-a3d8-9ce4efb8e21c/20260601-presentation-active-balancing-meeting-2026-en.pdf

## What matters for the checks

1. **S1 flows are netted per hour.** In each hour only the net direction of the border flow counts. To reproduce S1 from A11, net the two directions per hour and sum the positive part per direction over the year (UTC, by inference from the load tables). For DE from 2021-08 the 15-minute values must first become hourly values, and S1 does not say how. Gross sums of each A11 direction will be larger than S1. They are closer to S2 Tab. 29, which is not netted (compare the 2024 rows).
2. **S1 generation for 2023 does not come from the Transparency Platform.** CH footnote ³ of the 2023 edition: "Data is taken from SFOE (Swiss Federal Office of Energy) and Pronovo. For Wind and Solar estimations based on model data have been used. Category "Hydro Water Reservoir" includes also "Hydro Pumped Storage"." Leave 2023 out of the A75 checks. The other six years carry no Swiss footnote.
3. **S2 border values measure something else than A11.** According to S3, they include lower voltage levels, border hydro plants and supply areas abroad. They can bound the A11 sums, but no exact match should be expected.
4. **S6-S8 statistics are not sample moments.** μ and σ are "Mittelwert und Standardabweichung" of a normal distribution fitted to a histogram of quarter-hour CAB values in MW. ElCom itself prints two values for μ(2024) (-30.9 in S7, -30.6 in S8) and two values for σ(2022) (141.9 in S6/S7, 138 in S8). The counts of quarter-hours per bin are integers and make sharper checks. Positive means long in S6-S9.
5. **A86 and CAB are not proven to be the same series.** If the A86 value in MWh per quarter-hour equals CAB (MW) × 0.25 h, the conversion is: ±500 MW --> ±125 MWh; 1 400 MW --> 350 MWh; μ -30.9 MW --> -7.725 MWh. I found no document that confirms this. A86 could instead be the settled imbalance.
6. **Precision of S1.** Generation is printed to 0.1 TWh and flows to 1 GWh. Printed totals sometimes differ from the sum of their parts by one unit: renewable 2020 16.4 against a sum of 16.5; 2021 15.6 against 15.5; 2025 29.6 against 29.7; 2025 total with storage 55.9 against 48.0 + 8.0; 2025 sum of imports 25 068 against a sum of 25 067 over the four borders.

## 1. Actual generation per production type (A75)

| figure | value | unit | definition | source | read or snippet |
|---|---|---|---|---|---|
| Nuclear (B14) | 2019: 25.7; 2020: 23.4; 2021: 18.7; 2022: 23.6; 2023: 23.3 (SFOE); 2024: 23.0; 2025: 18.4 | TWh | column "Nuclear", net generation, CH, year | S1 p.2 | read |
| Hydro pumped storage (B10) | 2019: 7.7; 2020: 6.9; 2021: 6.5; 2022: 5.7; 2023: blank (included in reservoir, footnote ³); 2024: 9.6; 2025: 8.0 | TWh | column "Hydro Pumped Storage" (in the non-renewable block). 2025: the table was restructured, and the value is in "Infeed Pump storage" under "Storage generation/infeed"; "Total Infeed storage units" = 8.0 | S1 p.2 | read |
| Hydro run-of-river (B11) | 2019: 1.9; 2020: 2.1; 2021: 2.1; 2022: 1.9; 2023: 17.5 (SFOE); 2024: 2.3; 2025: 14.5 | TWh | column "Hydro Run-of-river and poundage" | S1 p.2 | read |
| Hydro water reservoir (B12) | 2019: 11.9; 2020: 11.9; 2021: 10.8; 2022: 8.1; 2023: 17.9 (SFOE, includes pumped storage); 2024: 13.9; 2025: 9.8 | TWh | column "Hydro Water Reservoir" | S1 p.2 | read |
| Solar (B16) | 2019: 0.4; 2020: 2.4; 2021: 2.5; 2022: 3; 2023: 5.2 (SFOE, model estimate); 2024: 4.3; 2025: 5.2 | TWh | column "Solar" | S1 p.2 | read |
| Wind onshore (B19) | 2019: 0.1; 2020: 0.1; 2021: 0.1; 2022: 0.2; 2023: 0.2 (SFOE, model estimate); 2024: 0.1; 2025: 0.2 | TWh | column "Wind Onshore" | S1 p.2 | read |
| Fossil gas (B04) | blank in all seven editions | TWh | column "Fossil Gas" | S1 p.2 | read |
| Other CH cells, 2023 only | Waste 1.6; Biomass 1.0 | TWh | SFOE/Pronovo values; blank in the other years | S1 2023 p.2 | read |
| Non-renewable net generation | 2019: 33.4; 2020: 30.3; 2021: 25.2; 2022: 29.3; 2023: 24.9; 2024: 32.6; 2025: 18.4 | TWh | nuclear + pumped storage (2025: nuclear only, storage moved out) | S1 p.2 | read |
| Renewable net generation | 2019: 14.3; 2020: 16.4; 2021: 15.6; 2022: 13.2; 2023: 41.8; 2024: 20.6; 2025: 29.6 | TWh | wind + solar + run-of-river + reservoir (2023 also biomass) | S1 p.2 | read |
| Total net generation | 2019: 47.7; 2020: 46.7; 2021: 40.8; 2022: 42.5; 2023: 66.7; 2024: 53.2; 2025: 48.0 (exclusive storage units) and 55.9 (inclusive storage units) | TWh | column "Total net generation" | S1 p.2 | read |
| Consumption of hydro pumped storage | 2019: blank; 2020: blank; 2021: 0.0; 2022: 0; 2023: 5.4; 2024: blank; 2025: "Withdrawal Pump Storage" blank | TWh | context only (not in A75) | S1 p.2 | read |
| Net consumption | 2019: 63.4; 2020: 62.4; 2021: 63.5; 2022: 64.6; 2023: 60.3; 2024: 59.6; 2025: 62.4 (also 62.4 inclusive storage) | TWh | context only | S1 p.2 | read |
| Capacity note | "Reported hydro run-of-river and pondage aggregated installed capacity for CH includes only units with capacity ≥100 MW." | - | footnote 9 of the 2025 net generation capacity table; it is consistent with the known partial coverage of run-of-river | S1 2025 p.2-3 | read |
| BFE run-of-river (Laufkraftwerke) | 2016: 16 574; 2017: 15 946; 2018: 16 908; 2019: 17 700; 2020: 17 648; 2021: 16 962; 2022: 15 490; 2023: 17 491; 2024: 19 403; 2025: 16 326 | GWh | "Landeserzeugung", calendar year, whole fleet | S2 Tab. 7 | read |
| BFE storage hydro (Speicherkraftwerke) | 2016: 19 752; 2017: 20 720; 2018: 20 520; 2019: 22 856; 2020: 22 968; 2021: 22 538; 2022: 18 011; 2023: 23 289; 2024: 28 934; 2025: 21 159 | GWh | reservoir and pumped-storage plants together (pump consumption not deducted) | S2 Tab. 7 | read |
| BFE nuclear | 2016: 20 235; 2017: 19 499; 2018: 24 414; 2019: 25 280; 2020: 22 990; 2021: 18 530; 2022: 23 113; 2023: 23 334; 2024: 22 983; 2025: 18 379 | GWh | Kernkraftwerke, calendar year | S2 Tab. 7 | read |
| BFE thermal | 2016: 3 612; 2017: 3 506; 2018: 3 649; 2019: 3 734; 2020: 3 888; 2021: 3 819; 2022: 3 689; 2023: 3 547; 2024: 3 602; 2025: 3 549 | GWh | Thermische Kraftwerke (gas, waste, biomass and others; no split) | S2 Tab. 7 | read |
| BFE wind | 2016: 109; 2017: 133; 2018: 122; 2019: 146; 2020: 145; 2021: 145; 2022: 150; 2023: 169; 2024: 171; 2025: 161 | GWh | Windkraftanlagen | S2 Tab. 7 | read |
| BFE solar | 2016: 1 334; 2017: 1 683; 2018: 1 945; 2019: 2 178; 2020: 2 692; 2021: 2 964; 2022: 4 067; 2023: 4 914; 2024: 5 961; 2025: 7 948 | GWh | Photovoltaikanlagen, whole fleet | S2 Tab. 7 | read |
| BFE total | 2016: 61 616; 2017: 61 487; 2018: 67 558; 2019: 71 894; 2020: 70 331; 2021: 64 958; 2022: 64 520; 2023: 72 744; 2024: 81 054; 2025: 67 522 | GWh | Landeserzeugung, total | S2 Tab. 7 | read |
| BFE 2015 | hydro 39 486; nuclear 22 095; thermal 3 147; wind 110; PV 1 119; total 65 957 | GWh | calendar year 2015, without the run-of-river/storage split | S2 Tab. 6 | read |
| BFE pump consumption | 2015: 2 296; 2016: 2 922; 2017: 4 160; 2018: 3 987; 2019: 4 133; 2020: 4 459; 2021: 4 145; 2022: 5 567; 2023: 5 375; 2024: 4 817; 2025: 5 215 | GWh | "Verbrauch der Speicherpumpen" | S2 Tab. 6 | read |
| Energy-Charts pumped storage | 2020: 3.567; 2021: 3.316; 2022: 4.454; 2023: 4.3; 2024: 3.854; 2025: 4.172 | TWh | "Hydro pumped storage". It is not independent: reservoir + pumped storage = BFE Speicherkraftwerke in every year, and the other series equal BFE / 1000. Only the split is new, and its method is not stated | S4 | read |
| Energy-Charts reservoir | 2020: 19.401; 2021: 19.222; 2022: 13.557; 2023: 18.989; 2024: 25.08; 2025: 16.987 | TWh | "Hydro water reservoir", same remark | S4 | read |

## 2. Physical flows on the CH borders (A11)

S1 rows: "hourly netted physical flow values", GWh, year (UTC by inference). DE is the country DE. Map labels are matched to arrows. For 2019-2024 the matching is confirmed because the four borders sum exactly to the printed "Sum of imports" and "Sum of exports"; for 2025, imports differ by 1.

| figure | value | unit | definition | source | read or snippet |
|---|---|---|---|---|---|
| CH --> DE | 2019: 3 434; 2020: 5 171; 2021: 1 306; 2022: 736; 2023: 4 012; 2024: 8 317; 2025: 3 613 | GWh | hourly netted | S1 flow map | read |
| DE --> CH | 2019: 11 809; 2020: 9 760; 2021: 13 875; 2022: 16 129; 2023: 7 792; 2024: 3 854; 2025: 6 546 | GWh | hourly netted | S1 flow map | read |
| CH --> FR | 2019: 2 010; 2020: 2 315; 2021: 1 955; 2022: 3 063; 2023: 2 218; 2024: 818; 2025: 406 | GWh | hourly netted | S1 flow map | read |
| FR --> CH | 2019: 7 690; 2020: 8 066; 2021: 8 218; 2022: 6 864; 2023: 9 612; 2024: 13 193; 2025: 15 754 | GWh | hourly netted | S1 flow map | read |
| CH --> IT | 2019: 21 236; 2020: 17 886; 2021: 18 600; 2022: 19 580; 2023: 20 370; 2024: 20 864; 2025: 16 088 | GWh | hourly netted | S1 flow map | read |
| IT --> CH | 2019: 121; 2020: 861; 2021: 378; 2022: 329; 2023: 149; 2024: 470; 2025: 496 | GWh | hourly netted | S1 flow map | read |
| CH --> AT | 2019: 565; 2020: 1 044; 2021: 421; 2022: 411; 2023: 696; 2024: 1 866; 2025: 2 430 | GWh | hourly netted | S1 flow map | read |
| AT --> CH | 2019: 4 317; 2020: 3 495; 2021: 3 384; 2022: 4 313; 2023: 4 628; 2024: 2 308; 2025: 2 271 | GWh | hourly netted | S1 flow map | read |
| CH sum of imports | 2019: 23 937; 2020: 22 182; 2021: 25 855; 2022: 27 635; 2023: 22 181; 2024: 19 825; 2025: 25 068 | GWh | "Sum of imports", hourly netted, all CH borders | S1 Exchange Balance | read |
| CH sum of exports | 2019: 27 245; 2020: 26 416; 2021: 22 282; 2022: 23 790; 2023: 27 296; 2024: 31 865; 2025: 22 537 | GWh | "Sum of exports" | S1 Exchange Balance | read |
| CH balance | 2019: -3 308; 2020: -4 234; 2021: 3 573; 2022: 3 845; 2023: -5 115; 2024: -12 040; 2025: 2 531 | GWh | "Balance (imp - exp)" | S1 Exchange Balance | read |
| BFE CH --> DE | 2016: 3 160; 2017: 2 134; 2018: 4 423; 2019: 6 692; 2020: 7 839; 2021: 4 553; 2022: 3 311; 2023: 7 522; 2024: 12 477; 2025: 7 876 | GWh | physical export measured at the border metering points ("an den Grenzübergabestellen nach Zählern effektiv gemessen"), not netted, calendar year; scope as in S3 | S2 Tab. 29 | read |
| BFE DE --> CH | 2016: 17 444; 2017: 19 619; 2018: 16 524; 2019: 14 470; 2020: 12 702; 2021: 16 983; 2022: 18 488; 2023: 11 106; 2024: 7 799; 2025: 10 664 | GWh | same | S2 Tab. 29 | read |
| BFE CH --> FR | 2016: 5 342; 2017: 6 446; 2018: 4 179; 2019: 4 955; 2020: 3 688; 2021: 3 728; 2022: 4 778; 2023: 3 637; 2024: 3 112; 2025: 2 112 | GWh | same | S2 Tab. 29 | read |
| BFE FR --> CH | 2016: 8 369; 2017: 8 520; 2018: 7 699; 2019: 8 661; 2020: 8 144; 2021: 9 214; 2022: 8 482; 2023: 10 163; 2024: 13 618; 2025: 15 286 | GWh | same | S2 Tab. 29 | read |
| BFE CH --> IT | 2016: 21240; 2017: 21841; 2018: 22773; 2019: 22483; 2020: 19263; 2021: 19 753; 2022: 20 461; 2023: 21 467; 2024: 22 060; 2025: 17 478 | GWh | same (2016-2020 printed without a separator) | S2 Tab. 29 | read |
| BFE IT --> CH | 2016: 1 383; 2017: 1 330; 2018: 1 188; 2019: 1 035; 2020: 1 960; 2021: 1 321; 2022: 1 089; 2023: 1 046; 2024: 1 404; 2025: 1 705 | GWh | same | S2 Tab. 29 | read |
| BFE CH --> AT | 2016: 390; 2017: 457; 2018: 1 198; 2019: 1 608; 2020: 1 732; 2021: 1 048; 2022: 1 156; 2023: 1 212; 2024: 2 678; 2025: 3 212 | GWh | same | S2 Tab. 29 | read |
| BFE AT --> CH | 2016: 6 879; 2017: 7 017; 2018: 5 594; 2019: 5 314; 2020: 4 149; 2021: 3 984; 2022: 5 040; 2023: 5 110; 2024: 3 084; 2025: 3 010 | GWh | same | S2 Tab. 29 | read |
| BFE CH and LI | export 2016-2025: 41; 68; 34; 27; 26; 37; 28; 18; 27; 22. import: 21; 10; 15; 25; 33; 30; 18; 37; 50; 56 | GWh | Liechtenstein (outside the adele borders) | S2 Tab. 29 | read |
| BFE total export | 2016: 30 173; 2017: 30 946; 2018: 32 607; 2019: 35 765; 2020: 32 548; 2021: 29 119; 2022: 29 734; 2023: 33 856; 2024: 40 354; 2025: 30 700 | GWh | sum of the five countries | S2 Tab. 29 | read |
| BFE total import | 2016: 34 096; 2017: 36 496; 2018: 31 020; 2019: 29 505; 2020: 26 988; 2021: 31 532; 2022: 33 117; 2023: 27 462; 2024: 25 955; 2025: 30 721 | GWh | sum of the five countries | S2 Tab. 29 | read |
| BFE 2015 totals | import 34 033; export 35 068 | GWh | "Einfuhr physikalisch", "Ausfuhr physikalisch", calendar year 2015 | S2 Tab. 6 | read |
| ENTSO-E Factsheet 2018 totals | CH sum of imports 30 420; sum of exports 31 693; balance -1 274 | GWh | different basis: "Consolidated yearly values might differ from detailed flow data from the ENTSO-E database due to ex-post consolidation taking into account national statistical resources." Not a Transparency Platform figure | entsoe_sfs2018_web.pdf (same URL pattern as 2019) | read |

## 3. Scheduled commercial exchanges on the CH borders (A09)

I found no published yearly figure per CH border and direction (see "Not found"). Two near substitutes:

| figure | value | unit | definition | source | read or snippet |
|---|---|---|---|---|---|
| CH Imports | 2021: 33.28380761499999; 2022: 33.7710441725; 2023: 31.89447822; 2024: 27.457757230749998 | not stated (magnitude: TWh) | "Aggregated ingoing scheduled commercial flows total", zone CH, all borders together. Day-ahead (A01) or total (A05)? The page links to the TP view "Scheduled Commercial Exchanges (Day Ahead)", but the files are named "comm_flows_total_annual_sums" and the fields say "total". Time basis not stated | S5 CSV row CH | read |
| CH Exports | 2021: 29.345362665; 2022: 28.847504344999997; 2023: 37.26577813; 2024: 41.56687815825 | same | "Aggregated outgoing scheduled commercial flows total" | S5 | read |
| CH Imports Netted | 2021: 26.377398267500002; 2022: 26.438840155; 2023: 25.46236054; 2024: 22.6323983995 | same | hourly netted ingoing scheduled commercial flows | S5 | read |
| CH Exports Netted | 2021: 22.4389533175; 2022: 21.5153003275; 2023: 30.83366045; 2024: 36.741519327 | same | hourly netted outgoing | S5 | read |
| CH Balance | 2021: -3.9384449499999956; 2022: -4.923539827500001; 2023: 5.371299910000004; 2024: 14.109120927499998 | same | The page says "difference between imports and exports", but the numbers equal Exports - Imports | S5 | read |
| BFE export to DE | 2016: 4 384; 2017: 3 062; 2018: 5 694; 2019: 8 210; 2020: 9 188; 2021: 7 071; 2022: 4 505; 2023: 9 348; 2024: 13 162; 2025: 9 542 | GWh | commercial foreign trade by partner country ("kommerzieller Stromaussenhandel"); from 2017 compiled by BAZG (customs, swissimpex). This is trade by country, not TSO schedules by border. Footnote 1: "Inbegriffen Austauschenergie; ab 2017 ohne Austauschenergie und Liechtenstein"; 2016: footnote 2 "Netto"; 2025: footnote 3 "Quelle: BAZG (swissimpex) [Stand: 1.4.2026]" | S2 Tab. 28 | read |
| BFE import from DE | 2016: 12 001; 2017: 11 617; 2018: 9 880; 2019: 7 583; 2020: 7 833; 2021: 8 860; 2022: 10 727; 2023: 7 974; 2024: 6 204; 2025: 8 595 | GWh | same | S2 Tab. 28 | read |
| BFE export to FR | 2016: 7 292; 2017: 6 158; 2018: 5 674; 2019: 5 007; 2020: 5 086; 2021: 5 214; 2022: 5 627; 2023: 4 241; 2024: 3 293; 2025: 1 386 | GWh | same | S2 Tab. 28 | read |
| BFE import from FR | 2016: 17 508; 2017: 16 599; 2018: 16 527; 2019: 17 886; 2020: 18 238; 2021: 20 705; 2022: 17 821; 2023: 20 799; 2024: 19 911; 2025: 21 677 | GWh | same | S2 Tab. 28 | read |
| BFE export to IT | 2016: 21 844; 2017: 20 140; 2018: 21 288; 2019: 20 992; 2020: 20 983; 2021: 19 098; 2022: 19 641; 2023: 23 937; 2024: 23 358; 2025: 20 834 | GWh | same | S2 Tab. 28 | read |
| BFE import from IT | 2016: 2 534; 2017: 1 552; 2018: 724; 2019: 565; 2020: 1 833; 2021: 1 732; 2022: 1 636; 2023: 805; 2024: 843; 2025: 2 006 | GWh | same | S2 Tab. 28 | read |
| BFE export to AT | 2016: 441; 2017: 228; 2018: 1 069; 2019: 2 282; 2020: 2 735; 2021: 1 351; 2022: 1 779; 2023: 2 660; 2024: 5 424; 2025: 4 060 | GWh | same | S2 Tab. 28 | read |
| BFE import from AT | 2016: 5 878; 2017: 5 893; 2018: 5 326; 2019: 4 315; 2020: 4 881; 2021: 4 067; 2022: 5 468; 2023: 4 984; 2024: 3 870; 2025: 4 617 | GWh | same | S2 Tab. 28 | read |
| BFE total export / import | export 2016-2025: 34 096; 29 588; 33 725; 36 491; 37 992; 32 734; 31 552; 40 186; 45 237; 35 822. import: 38 019; 35 661; 32 457; 30 349; 32 785; 35 364; 35 652; 34 562; 30 828; 36 895 | GWh | same; LI only in 2016 (export 135, import 98) | S2 Tab. 28 | read |

S2 section 6.1 adds a warning: from 2013, major balance-group transactions with Germany were removed, which "reduziert das Volumen der Exporte und Importe deutlich".

## 4. Total imbalance volume of the Swiss control area (A86)

All values in this table are Swissgrid control area balance (CAB) data in MW per quarter-hour, positive = long, as analysed by ElCom (S6-S8) or Swissgrid (S9). See the "What matters" points 4 and 5 before comparing them with A86 in MWh.

| figure | value | unit | definition | source | read or snippet |
|---|---|---|---|---|---|
| Mean μ by year | 2017: 7.4; 2018: -11.3; 2019: -0.3; 2020: 2.4; 2021: -15.7; 2022: 5.6; 2023: 7.9; 2024 (01.01.-20.06.): -21.1 | MW | "Mittelwert (μ)" of the normal distribution fitted to the quarter-hour CAB values, calendar year | S6 Tab. 1 | read |
| Std σ by year | 2017: 120.7; 2018: 115.3; 2019: 110.2; 2020: 116.9; 2021: 139.6; 2022: 141.9; 2023: 161.9; 2024 (01.01.-20.06.): 187.1 | MW | "Std. Abw. (σ)" of the fitted normal | S6 Tab. 1 | read |
| μ and σ 2024, full year | μ -30.9; σ 175.5 (2017-2023 identical to S6) | MW | same | S7 Tab. 1 | read |
| μ 2024 and 2025 (text) | "µ(2024) = -30.6 MW"; "µ(2025) = -28.2 MW" | MW | same method, newer fit | S8 section 2.2.2 | read |
| μ and σ in the figure | 2025: μ -28, σ 162; 2024: -31, 176; 2023: 8, 162; 2022: 6, 138; 2021: -16, 140; 2020: 2, 117; 2019: -0, 110; 2018: -11, 115; 2017: 7, 121 | MW | labels in Abbildung 1 (rounded). σ(2022) = 138 here against 141.9 in S6/S7 | S8 Abb. 1 | read |
| Count of quarter-hours per bin, 2025 | 0 / 5 / 18 / 33 / 92 / 215 ... 116 / 39 / 12 / 1 / 0 / 0 | quarter-hours | Bins in this order: [-5000,-1000] [-1000,-900] [-900,-800] [-800,-700] [-700,-600] [-600,-500] ... [500,600] [600,700] [700,800] [800,900] [900,1000] [1000,5000] MW. Positions between -500 and +500 MW are not shown; inclusion of the bin edges is not stated | S8 Tab. 1 | read |
| same, 2024 | 33 / 24 / 24 / 67 / 91 / 212 ... 68 / 34 / 10 / 8 / 1 / 7 | quarter-hours | same bins; identical in S7 Tab. 2 | S8 Tab. 1, S7 Tab. 2 | read |
| same, 2024 H1 (01.01.-20.06.) | 17 / 11 / 13 / 36 / 65 / 120 ... 53 / 18 / 4 / 2 / 0 / 3 | quarter-hours | same bins | S6 Tab. 2 | read |
| same, 2023 | 1 / 11 / 17 / 17 / 46 / 87 ... 93 / 28 / 22 / 4 / 0 / 3 | quarter-hours | same bins | S8 Tab. 1 (= S6, S7) | read |
| same, 2022 | 4 / 3 / 4 / 3 / 28 / 107 ... 39 / 5 / 1 / 0 / 2 / 0 | quarter-hours | same bins | S8 Tab. 1 | read |
| same, 2021 | 1 / 0 / 2 / 2 / 12 / 73 ... 16 / 3 / 1 / 4 / 0 / 0 | quarter-hours | same bins | S8 Tab. 1 | read |
| same, 2020 | 2 / 0 / 2 / 2 / 1 / 19 ... 10 / 0 / 1 / 0 / 0 / 0 | quarter-hours | same bins | S8 Tab. 1 | read |
| same, 2019 | 1 / 3 / 2 / 3 / 10 / 32 ... 1 / 2 / 1 / 0 / 0 / 0 | quarter-hours | same bins | S8 Tab. 1 | read |
| same, 2018 | 1 / 0 / 0 / 0 / 9 / 38 ... 11 / 5 / 1 / 2 / 4 / 0 | quarter-hours | same bins | S8 Tab. 1 | read |
| same, 2017 | 5 / 0 / 2 / 1 / 2 / 7 ... 15 / 3 / 0 / 0 / 0 / 0 | quarter-hours | same bins | S8 Tab. 1 | read |
| Short beyond -500 MW (text) | 149 (2022); 179 (2023); 451 (2024, "davon 35 am 22.04") | quarter-hours | "mehr als -500 MW short" | S7 section 1.4 | read |
| Long beyond +500 MW (text) | 47 (2022); 150 (2023); 128 (2024, "davon 7 am Ostersonntag") | quarter-hours | "mehr als +500 MW long" | S7 section 1.4 | read |
| 22 April 2024 | "Unausgeglichenheit der Schweizer Regelzone von bis zu 1'400 MW" (short) | MW | single-day event | S6, S7 section 1.4 | read |
| Max absolute imbalance, Jan-Apr | 2024: 1400; 2025: 838; 2026: 595 | not printed (MW by context) | "Maximum \|control area imbalance\| in the first four months" | S9 slide 13 | read |
| Monthly count above 500 MW in absolute value | 2024: Jan 6, Feb 18, Mar 79, Apr 128, May 56, Jun 94. 2025: Jan 25, Feb 33, Mar 82, Apr 61, May 77, Jun 50. 2026: Jan 2, Feb 0, Mar 3, Apr 5, May 1, Jun 10 | "Count" (unit not stated, probably quarter-hours) | chart "Total System Imbalance above \|500\| MW". The June 2026 bar appears on a deck dated 1 June 2026, so treat it with suspicion | S9 slide 13 bar labels | read |
| Cumulative absolute imbalance, 1 Jan - 29 Apr | printed: "Savings of approx. 40%", "150 GWh" (2026 against earlier years) | GWh | chart "Cumulative Absolute Imbalance by Year" | S9 slide 12 | read |
| same, read from the chart | 2024 about 400; 2025 about 368; 2026 about 225 at 04-29 (my reading of the curves, approximate; dashed reference lines at about 382 and 227) | GWh | sum of the absolute imbalance from 1 January | S9 slide 12 | read (chart reading, not a printed number) |

## Not found, blocked, not used

- **Scheduled commercial exchanges per CH border and year:** no published figure from ENTSO-E, Swissgrid, ElCom or ACER. ElCom's *Grenzkapazitäten im Handel: Entwicklung 2018-2021* (February 2022) covers auctioned capacities and prices, not scheduled volumes. The S1 factsheets give no commercial exchanges.
- **CH imbalance volume from ENTSO-E or ACER:** the *ENTSO-E Electricity Balancing Cost Report 2025* names Swissgrid only in the cost tables. I did not open the ENTSO-E Balancing Reports in detail. The ENTSO-E ALFC report (FRCE) measures the error left after control, not the total imbalance, so I left it out.
- **Blocked:** the Swissgrid *TSO report on balancing V2020* (HTTP 404), the CSEM paper "From solar generation to balancing" on yoda.csem.ch (HTTP 403), the Energy-Charts yearly cross-border JSON at a guessed path (404), and electricityineurope.entsoe.eu (host not found). Following the brief, I moved on and did not try the web-fallback skill.
- **Energy-Charts:** the yearly generation JSON (S4) mirrors BFE, as shown in table 1. I did not find a yearly table of CH cross-border flows that is readable without JavaScript.
- **Factsheets before 2019:** the 2018 edition has a different basis ("All values are calculated to represent 100 % of the monthly national values"; flows consolidated with national statistics). I used it only for the one context row in table 2. I did not fetch 2015-2017.
- **The 2019 and 2020 factsheets were re-issued in November 2024.** I did not compare them with the original editions.
