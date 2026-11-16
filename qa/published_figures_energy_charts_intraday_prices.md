# Published figures for energy_charts_intraday_prices

Collected 2026-11-15 by Claude (WP5.4), checked the same day with
`qa/tools/published_check_energy_charts_intraday_prices.py <data_dir>` on the backfill of the worktree `wp5.4`
(2015-01-01 to 2026-11-14). Renaud's own documents were not asked for yet.

`datasets/energy_charts_intraday_prices/checks.yaml` holds 12 checks, from two monthly reports of EPEX SPOT.
Generator: `gen_checks_wp54.py` in the session scratchpad (one-off); edit checks.yaml directly from now on.

## Sources

| source | what | URL |
|---|---|---|
| EPEX SPOT, Power Trading Results 12-2025 (2026-01-06) | p. 6: intraday auctions, base / peak (CH IDA1, IDA2); p. 8: intraday continuous indices ID Full, ID3, ID1 for 60-minute contracts (CH, DE) | local copy `swissgrid_project/papers/EPEX_2026_Power_Trading_Results_2025-12.pdf` |
| EPEX SPOT, Power Trading Results 09-2025 (2025-10-02) | p. 5: intraday auctions (CH IDA1, IDA2); p. 7: ID3 only | https://www.epexspot.com/sites/default/files/download_center_files/2025-10-02_EPEX%20SPOT_Power%20Trading%20Results%2009-2025_0.pdf |

Base = every hour of the local month; peak = "Peak excl. weekend", Monday to Friday 08:00-20:00 local (this reading
reproduces EPEX's peak figures to the cent).

**EPEX's download center refuses scripts.** 24 more monthly reports of 2020-2025 were found by web search; each URL
answered HTTP 403 to a script (one answered 200), and the web-fetch agent got 403 on EPEX's HTML news pages too.
SED had noted the same (`notes/swiss_intraday.md`, section 7). To add them: PinchTab with `epexspot.com` in its
allowed domains, or a download by hand. URLs: the search of 2026-11-15 in the WP5.4 log.

## Result (2026-11-15)

12 of 13 figures match to the cent (tolerance 0.015):

- DE_LU 2025-12: ID Full 92.39 (adele 92.397), ID3 92.16 (92.158), ID1 92.13 (92.129). Energy-Charts' DE series
  are EPEX's indices, as swissgrid_project found for the same month.
- CH 2025-12: IDA1 base 187.33 and peak 125.90, IDA2 base 127.93 and peak 124.20. IDA2 auctions only some hours
  (null in the others): the mean over the non-null hours is EPEX's figure.
- 2025-09: DE ID3 86.12; CH IDA1 93.46 / 101.89, IDA2 556.97 / 596.67. The source has no IDA1 on 2025-09-09, and
  EPEX's mean matches without that day: no auction result that day at EPEX either.

## Differences

| figure | EPEX | adele | reason |
|---|---|---|---|
| CH ID Full, 2025-12 | 112.89 | 112.906 | probably a definition: EPEX's ID Full takes the day-ahead price in an hour with less than 10 MW traded; Energy-Charts' CH average keeps the traded price (SED, `notes/swiss_intraday.md` section 6: the average equals the day-ahead price in 171 of 61,837 hours). Not proven: every hour of December 2025 has trades and a range (low < high), so the thin hours can't be told from the data. Left out of the checks |
