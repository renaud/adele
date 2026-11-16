# Published figures for entsoe_imbalance_volume

Searched 2026-11-15 by a research agent (12 web searches for the four datasets of WP5.2),
compared with adele the same day with `qa/tools/published_check_entsoe_imbalance_volume.py
<data_dir>` on the backfill of the worktree `wp5.2` (2015-03-25 to 2026-11-15). Renaud's own
documents: not asked yet.

**No check yet.** No figure was found that others computed from ENTSO-E's A86 for CH. The
figures found are computed on Swissgrid's control area balance (CAB), another series, and A86
reproduces none of them. `datasets/entsoe_imbalance_volume/` has no `checks.yaml`.

## Sources

| source | what | URL |
|---|---|---|
| ElCom, Bericht Regelleistung und Regelenergie 2023 and 2024; Besondere Ereignisse in der Regelzone Schweiz im Jahr 2025 (13 May 2026) | on Swissgrid's public CAB data, MW per quarter-hour, positive = long: per year 2017-2025, the quarter-hours per bin of 100 MW beyond +-500 MW, and the mean and standard deviation of a normal curve fitted to the histogram (not sample moments; ElCom prints two values for some years) | https://www.elcom.admin.ch/dam/it/sd-web/lpdgJ8PUh5mk/Bericht%20Besondere%20Ereignisse%20in%20der%20Regelzone%20Schweiz%202025.pdf (Tab. 1, Abb. 1) |
| Swissgrid, Active Balancing Meeting, 1 June 2026, slides 12-13 | monthly counts of quarter-hours beyond +-500 MW, January-June 2024-2026; the largest imbalance of January-April | https://www.swissgrid.ch/dam/jcr:185cbf2b-f46d-49ea-a3d8-9ce4efb8e21c/20260601-presentation-active-balancing-meeting-2026-en.pdf |

## Result (2026-11-15)

ElCom's counts per bin against A86 as mean power (MWh x 4), with UTC years (local years give the
same counts): no year matches. Bins from [-5000, -1000) to [1000, 5000) MW:

| year | ElCom | adele | equal bins |
|---|---|---|---|
| 2017 | 5 0 2 1 2 7 / 15 3 0 0 0 0 | 7 0 0 0 2 11 / 2 0 0 0 0 0 | 6 of 12 |
| 2019 | 1 3 2 3 10 32 / 1 2 1 0 0 0 | 1 3 2 3 9 31 / 6 6 1 0 0 0 | 8 of 12 |
| 2022 | 4 3 4 3 28 107 / 39 5 1 0 2 0 | 0 2 1 3 17 101 / 59 40 27 28 15 11 | 1 of 12 |
| 2024 | 33 24 24 67 91 212 / 68 34 10 8 1 7 | 42 28 35 70 131 279 / 98 42 17 10 6 3 | 0 of 12 |
| 2025 | 0 5 18 33 92 215 / 116 39 12 1 0 0 | 6 9 34 69 143 243 / 186 81 40 16 5 1 | 0 of 12 |

(left of the slash: short, from -1000 MW and below to [-600, -500); right: long, from [500, 600)
to 1000 MW and above. All years: `qa/tools/published_check_entsoe_imbalance_volume.py`.)

What it shows: A86 is not CAB in any year from 2017. Nearer in 2017-2021 (5 to 8 of 12 bins
equal), it has more large values from 2022 on, and many more from 2024, which fits the swissgrid project's
finding that A86 equals TSI minus the IGCC netting from 2025-02 (the netting counted twice). The
warnings of `datapackage.yaml` say so. These ElCom and Swissgrid figures are checks for the
Swissgrid control area balance (`swissgrid_balance`, in `main` since WP4, without checks yet), not for this dataset. Every value with its page: `qa/published_figures_wp52_sources.md`, section 4.

## Second search (2026-11-16, Renaud: "search harder")

A research agent (about 40 web searches, every document read, the `web-fallback` skill for the
blocked pages), then four ENTSO-E reports too large for WebFetch downloaded and read by Claude.
Again no document prints a Swiss value and says that it comes from A86. What came closest:

| document | what it has for CH | compared with A86 |
|---|---|---|
| DNV for BFE, "Untersuchung des Regelenergiebedarfs der Schweiz im Internationalen Vergleich" (13.04.2026), Tabelle 2, p. 24, https://pubdb.bfe.admin.ch/de/publication/download/12594 | balancing energy short and long as a share of the annual consumption, 2018-2024 (e.g. 2019: 0.59 % and -0.59 %) | **not A86.** Its data are "die viertelstündlichen Ausgleichsenergiesalden aller BGV" (the balance groups' settlement). The consumption implied by A86 and DNV's two columns disagrees by up to 25 % in the same year (2022: 58.1 TWh from the deficits, 73.0 TWh from the surpluses), far more than the rounding of a two-decimal percentage |
| ENTSO-E Balancing Report 2026, Figures 119 and 120 (p. 148-149; the caption of 120 says "positive" but it shows the deficit), https://eepublicdownloads.blob.core.windows.net/public-cdn-container/clean-documents/Reports/2026/260629_ENTSO-E_Balancing_Report.pdf | share of quarter-hours with a surplus and with a deficit, 2025, drawn as bars without values | read off the chart: about 42 % and 58 %; A86 (local year 2025): 42.2 % and 57.8 %. Consistent |
| ENTSO-E Market Report 2025, p. 147-148, https://eepublicdownloads.blob.core.windows.net/strapi-test-assets/strapi-assets/entso-e_Market_report_2025.pdf | the same shares for 2024, bars without values | read off the chart: about 26 % deficit and 15 % surplus, which add up to 41 %; A86: 57.9 % and 42.1 %. Not consistent: another definition or part of the year, not stated |
| Compass Lexecon for ENTSO-E, ISHM assessment, Annex 7.1 (25.06.2026), Figure 4, p. 25; the only document that names A86 ("Imbalance Prices & Total Imbalance Volumes", 17.1.G, 17.1.H) as its source | an "imbalance ratio" (mean over the quarter-hours of abs(imbalance) / total load), CH 2022, 2023, January-July 2024, as unlabelled points | read off the chart: about 1.5-1.7 % (2022, 2023) and 2.0 % (2024); A86 with `entsoe_load`'s actual load: 1.46 %, 1.68 %, 1.91 %. Consistent |
| ElCom, communication of 2 July 2024, https://www.elcom.admin.ch/dam/fr/sd-web/us4uYSDhAxQW/regelzonen-ausgeglichenheit.pdf | up to 1,400 MW on 2024-04-22; 342 quarter-hours above 500 MW from 1 January to 20 June 2024 | no data source stated: Swissgrid's own data, as in ElCom's reports above |
| ENTSO-E Balancing Reports 2020, 2022, 2024 | the 2024 KPI on the shares of quarter-hours has no Swissgrid row; 2020 and 2022 have no Swiss imbalance volume | nothing to compare |

Values read off a chart are not published figures (skills/add-dataset, step 8), and the two
ENTSO-E years disagree with each other against A86: no check from them. Not readable: the CSEM
paper "From solar generation to balancing" (yoda.csem.ch, HTTP 403 also through its API) and
Swissgrid's "TSO report on balancing" V2020 (HTTP 404 under every path; it would be Swissgrid's
own data anyway). arXiv:2504.06729 (ETH) says that Swiss imbalance data are "unavailable or
sparsely reported" and uses aFRR activations instead.

The agent's full report, with the searches that found nothing:
`scratch_nosync/published_figures_imbalance_search.md` in the worktree `wp5.2` (outside git).

## Candidates for a first check

- Renaud's documents: any report of the swissgrid project or of the team that computed figures
  from A86 (yearly counts of large imbalances, sums of the absolute volume). The swissgrid
  project's README holds such figures (standard deviation per year, counts of |A86| >= 500 MW),
  but they were computed by an agent, not published: to use only if Renaud agrees.
- Papers that use the platform's A86 for CH: none found in two searches.
- A check against another dataset instead of a published figure: once Swissgrid's control area
  balance is in adele (WP4), A86 must equal TSI minus the IGCC netting from 2025-02-14 (the
  swissgrid project found 96 to 99 % of the quarter-hours of each month within 1 MW). It tests
  the sign, the stamps and the unit at once, which no figure found so far does.
