# Common traps in datasets

Shared by the skills `add-dataset` and `review-dataset`. In `add-dataset`, each trap is a
question that the data analyst answers. In `review-dataset`, each trap is a check against the
data.

When a review or a QA question finds a trap that is not listed here, add it.

## Time

- Does the timestamp of the source mark the start or the end of the interval?
- Is the timestamp of the source in UTC or in local time? If local, which zone?
- Clock changes: do the days of the change have 23 and 25 hours (92 and 100 quarter hours)?
  Is the repeated hour in autumn present twice, or merged?
- Which time zone defines a "day", a "month" (e.g. the delivery day in CET/CEST)?
- Did the resolution change over the history (e.g. 60 --> 15 minutes on 2025-10-01 for
  day-ahead prices)? A plain average over such a period weighs the two parts differently.
- Did it change on the same date for every series? ENTSO-E day-ahead prices, measured
  2026-11-13: FR from delivery day 2025-09-30, DE_LU from 2025-10-01, CH from 2026-11-04.
  Then one list of periods per dataset is wrong; store the resolution per row.
- Is the published resolution the resolution of the market? FR's day-ahead prices of delivery
  day 2025-09-30 come as 96 quarter-hours, but the four quarters of every hour are equal: the
  auction was still hourly. Averages are not affected; counts of intervals are (4 per hour).

## Fetching

- Does the API cut a long request without an error? ENTSO-E does, by more than one rule: a
  one-year request of day-ahead prices (one series per day) returned 100 days, and a 90-day
  request for FR (15-minute prices) returned 73 days. Check that each response covers the
  window it was asked for; counting series is not enough.
- Does the client library reshape the data? entsoe-py's pandas client resamples day-ahead
  prices before 2025-10-01 to hourly with `.first()`, which keeps the first quarter-hour of a
  15-minute series. Measure on the raw response.
- entsoe-py's pandas client drops one hour per year (2024-12-31 00:00 CET was missing from a
  request for 2024; measured 2026-11-13) and includes the row at the requested end.
- Does the source publish several series for one key? ENTSO-E DE_LU has two day-ahead
  series (sequence 1 and 2); without a filter, each timestamp comes twice.
- Does an error message hold a secret? requests writes the URL in its errors, and ENTSO-E's
  token is in the URL (2026-11-15, `datasets/entsoe_wind_solar_forecast/fetch.py`, `_redact`).
  The server removes the declared secrets from what `fetch.py` prints (D34), but not from a
  file that `fetch.py` writes, such as the URL of a kept answer (D33): keep the token out of it.
- Does the source refuse requests when it is busy? ENTSO-E answered HTTP 599 ("Unable to access
  service within time limit") to one request in about 300 while four backfills shared one token
  (2026-11-15): retry an answer 5xx before failing the window.

## Values

- Power or energy? Is a value the mean over the interval (MW), an instantaneous reading, or
  the energy of the interval (MWh)? Summing MW over 15-minute rows is wrong by a factor of 4.
- Sign convention: which direction is positive for flows, imbalances, net positions?
- Flows per direction: gross (both directions above 0 in the same interval) or net (one of
  them 0)? ENTSO-E's physical flows on the CH-DE border are gross: both directions above 0 in
  658 of 756 quarter-hours (2026-11-08 to 2026-11-15). Keep both directions on one row, so
  that the net flow is a difference and no query adds the two.
- Currency, and whether it changed.
- Missing against zero: does the source write 0, an empty cell, or a sentinel (-999, 9999)
  when a value is missing?
- Preliminary against final values: are recent values provisional?

## Keys and codes

- Is the declared key unique in the data? Does the source deliver duplicates?
- Did codes change over time (bidding zones split or merged, production types renamed)?
- Does one name mean different things at different sources (DE, DE_LU, DE_AT_LU)?
- Does the source publish one border under two areas with different values? ENTSO-E's
  flows on the Swiss-German border for the country DE and for the bidding zone DE_LU are equal
  except in 2025, where 24,782 of 35,040 quarter-hours differ; Swissgrid's figures agree with
  DE. Asking both would also count the border twice.
- Does a total row sit among the detail rows (e.g. a zone "EU" next to the countries)?
- Is the total the sum of its parts? ENTSO-E wind and solar forecasts (measured 2026-11-15): IT
  equals the sum of its zones, but DE_LU's day-ahead solar and onshore wind exceed the sum of
  the four German TSO areas (Luxembourg; Austria in DE_AT_LU), while its intraday forecast
  equals it. A published "Germany" can be either.

## Revisions and coverage

- Does the source revise past values? Until how long after delivery?
- Gaps: periods without data, and whether the source fills them later.
- Did the definition or the method change at some date (a break in the series)?
- Is a value stuck? ENTSO-E's FR offshore wind forecast holds exactly 240 MW for five days
  (2023-12-30 to 2024-01-04): long runs of one value are often a frozen feed.
- Is a forecast really a forecast? ENTSO-E's Italian day-ahead solar "forecast" at 2015-03-20
  11:00 UTC equals the real infeed that ENTSO-E published for that hour, not the forecast it
  published (`entsoe_wind_solar_forecast_neighbours`); the Swiss load forecast is a copy of the
  actual load in 2021-2022 (`entsoe_load`).
- Does the dataset cover what its title says (all plants, or only those above a size limit)?
