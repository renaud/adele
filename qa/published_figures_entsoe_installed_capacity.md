# Published figures for entsoe_installed_capacity

Collected 2026-11-15 by a research agent, checked against adele on 2026-11-16 by Claude: the 16
checks of `datasets/entsoe_installed_capacity/checks.yaml` all pass. Renaud's own documents: not
asked yet.

## Sources and result

ENTSO-E's Statistical Factsheets, table "Net Generation Capacity" (p. 3), "based upon data
reported to the ENTSO-E Central Transparency Platform", capacity "as of 1st of January" of the
year, whole MW. Read in the agent's text extracts: 2019, 2020, 2022, 2024. In each, CH's four
values are A68's rounded to the MW (2019: nuclear 3,373, pumped storage 6,641, run-of-river 635,
reservoir 5,419); the columns "non renewable" (nuclear + pumped storage) and "renewable"
(run-of-river + reservoir) add up. URLs: `entsoe_sfs<year>_web.pdf` under
https://eepublicdownloads.entsoe.eu/clean-documents/Publications/Statistics/Factsheet/ (2019-2022)
and https://eepublicdownloads.blob.core.windows.net/public-cdn-container/clean-documents/Publications/Statistics/Factsheet/
(2023-2025).

## Left out

- 2021 and 2025: the agent reports matching values (2021: 2,970 / 6,681 / 605 / 5,588; 2025:
  2,983 / 6,697 / 635 / 5,777) but they are not in its saved extracts; not checked by hand.
  The 2025 factsheet notes that CH's run-of-river covers only units of 100 MW or more.
- 2023: the factsheet takes CH from the Swiss Federal Office of Energy (nuclear 2,979, pumped
  storage 4,152, ...), not from the platform.
- 2015-2018: the factsheets of those years use national statistics (e.g. nuclear 3,333 MW).
- ENTSO-E Power Statistics `net_generation_capacity_<year>.csv` (decimals, e.g. 6640.70): seen
  only through WebFetch's summary; to download before use.
- BFE, Schweizerische Elektrizitätsstatistik 2022, Tab. 32: nuclear 2,960 MW ("maximal mögliche
  Leistung ab Generator"): another definition than A68's 2,970.
