# Which ENTSO-E series for CH are revised after publication

Measured 2026-11-15 (WP3). The swissgrid project saved the raw answers of its ENTSO-E downloads
on 2026-10-31 (`swissgrid_project/data/entsoe/raw_nosync/`). The same requests were sent again
on 2026-11-15 and the answers compared value by value: a value is a numeric field of a point,
identified by its time series, its time and its text fields. Tool:
`qa/tools/revisions_entsoe_ch.py` (all series except the load); the load was compared with
`measure_load_revisions.py` (WP3-versions.md). The fresh answers sit in the session scratchpad,
not kept.

"Age" is the time between the delivery of a value and the old download. "Ahead" counts values
of hours that were still to come at the old download (forecasts, day-ahead schedules): a change
there is an update before delivery. Values that only the new answers hold, for times before the
old download, are mostly the last hour or two (published a little later), not revisions.

| series (document) | values compared | changed | age of the changed values | example |
|---|---|---|---|---|
| load, actual and day-ahead forecast (A65) | 207,442 | 0 | | |
| day-ahead prices (A44) | 103,716 | 0 | | |
| imbalance prices (A85) | 754,508 | 0 | | |
| prices of activated balancing energy (A84) | 1,616,924 | 0 | | |
| installed capacity (A68) | 48 | 0 | | |
| wind and solar forecasts, day-ahead, intraday, current (A69) | 235,042, and 52 ahead | 3, none ahead | 2 to 7 days | night values of the day-ahead solar forecast, 4.9 --> 4.7 MW |
| generation per type (A75) | 608,417 | 36 | 33 under 2 days, 2 at 2 to 7 days, 1 at 3 months | 2026-10-31 07:00, 1,299 --> 1,119 MW; 2026-07-30 18:00, +105 MW |
| imbalance volume (A86) | 484,968 | 6, plus 14 removed and 32 added | one day of 2025 (2025-09-11), corrected more than a year later; one quarter-hour of 2025-09-22 added | 2025-09-11 11:00, 25.1 --> 82.1 MWh |
| physical flows on the CH borders (A11), 2025-2026 only | 352,896 | 6,398 | 6,215 at 1 to 12 months, 134 at 7 to 30 days, 49 under 2 days | DE border, August 2026, changes of 0.3 to 5 MW; DE_LU border, 2026-10-29 21:00, 2,085 --> 1,970 MW |
| scheduled exchanges (A09, day-ahead A01 and total A05), 2025-2026 only | 1,004,681, and 1,258 ahead | 302, and 541 ahead | 110 under 2 days, 94 at 2 to 7 days, 98 at 7 to 30 days | day-ahead DE_LU border on 2026-10-24 set to 800 MW (from about 700) a week later; AT border on 2026-11-01, 56 --> 1,034 MW before delivery |

Flows and schedules were compared on their two last yearly windows only (2025 and 2026): a
yearly answer of one border takes several seconds, and all years would have taken more than an
hour. Not compared: the outages (A80, A77: paged answers, and they wait for WP2), the
1-minute balancing state (A86 B33, which ended in June 2025).

## What it means

- Revised, so `append-only` keeps something that `overwrite` loses: generation per type (the
  first values of the last hours are provisional), physical flows (corrections up to months
  later), scheduled exchanges (corrections, and updates before delivery), imbalance volume
  (rarely). These are the series of WP3's (b) (Renaud, 2026-11-15: "ok, for the series that a
  shows to be revised").
- Not revised in these 15 days: load, prices (day-ahead, imbalance, activated), installed
  capacity; the wind and solar forecasts only by a few tenths of a MW. The inventory had flows
  and schedules as fitting today (`overwrite`); they are revised, so the choice of policy is
  open for them.
- One window of 15 days says nothing about rarer revisions, and the method sees only the
  latest value at each download: a value revised twice in between counts once.
