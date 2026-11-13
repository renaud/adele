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

## Values

- Power or energy? Is a value the mean over the interval (MW), an instantaneous reading, or
  the energy of the interval (MWh)? Summing MW over 15-minute rows is wrong by a factor of 4.
- Sign convention: which direction is positive for flows, imbalances, net positions?
- Currency, and whether it changed.
- Missing against zero: does the source write 0, an empty cell, or a sentinel (-999, 9999)
  when a value is missing?
- Preliminary against final values: are recent values provisional?

## Keys and codes

- Is the declared key unique in the data? Does the source deliver duplicates?
- Did codes change over time (bidding zones split or merged, production types renamed)?
- Does one name mean different things at different sources (DE, DE_LU, DE_AT_LU)?
- Does a total row sit among the detail rows (e.g. a zone "EU" next to the countries)?

## Revisions and coverage

- Does the source revise past values? Until how long after delivery?
- Gaps: periods without data, and whether the source fills them later.
- Did the definition or the method change at some date (a break in the series)?
- Does the dataset cover what its title says (all plants, or only those above a size limit)?
