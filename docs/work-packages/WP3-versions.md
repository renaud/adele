# WP3: versions

Draft by Claude, 2026-11-15. From `PLAN.md` (WP3), `SPEC.md` (Revisions), `TODOs.md` (POC 2, V1)
and `docs/datasets-inventory.md` (gap G3). Renaud's answers of 2026-11-15 are in: design points
1, 2, 3 and 5 accepted, the answers a to e after the review (log), point 4: layout c.

## Where WP3 stands (2026-11-15)

- Built in the worktree `wp3` (branch `wp3`, from `880da30`), with tests on synthetic data,
  layout c included. Decision D30 in `DECISIONS.md`. Lands in `main` on 2026-11-15, during
  WP1's week (Renaud relaxed the rule of the WP1 doc); WP3 reaches steacher1 only once WP1 is
  done.
- Step 4 (the first real dataset): `datasets/entsoe_load`, measured, backfilled on the Mac,
  50 published figures as checks. The backfill and 1-2 days of fetches on steacher1 wait for
  the end of WP1 (`TODOs.md`, V1).

## Goal

A dataset can declare `revisions: append-only`. adele then keeps every version of a value, not
only the latest. A query returns the latest value per key by default, and can ask what adele
knew at a given time (`as_of`). This frees 8 datasets for WP6 (6 of ENTSO-E, 2 of Pronovo), and
the Swissgrid year file for WP4.

## What is settled

- `SPEC.md`, Revisions: every row carries `fetched_at`; queries return the latest value per key;
  `as_of=<timestamp>` returns what adele knew at that time.
- `overwrite` and `none` (D15) stay as they are. An `append-only` fetch reads the same window as
  `overwrite`, [last - lookback, now + horizon): the lookback is what catches revisions.
- Design points 1, 2, 3 and 5 below, and the answers a to e: D30.
- The build runs on the Mac with synthetic data, next to WP1. It goes to steacher1 once WP1 is
  done.

## Design

1. **When a version is stored.** Decided (a): only when the key is new or a column outside the
   key differs from the latest stored version of that key, compared exactly, a null equal to a
   null. Rejected (b): every fetched row (an hourly fetch with a lookback of 3 days would store
   each unchanged value 72 times). The merge is `storage.merge_versions`, close to
   `merge_append` of D15: there a changed value is an error, here it becomes a new version.
2. **What `fetched_at` is.** Decided, with answer a: the time at which `fetch.py` returned, in
   UTC with microseconds, the same for every table of that call. A run in pieces and a backfill
   have one stamp per window. The server adds the column: the descriptor doesn't declare it,
   and the catalog refuses a field of that name. The primary key of the descriptor stays the
   key of a value; in the files, the key is the primary key plus `fetched_at`. A merge whose
   stamp is not later than the stored versions of a partition (a clock set back) fails.
3. **How queries see the versions.** Decided: the view `<id>.<table>` keeps its meaning (the
   latest version per key), so a query written for `overwrite` works unchanged. A second view,
   `<id>.<table>_versions`, holds every version with its `fetched_at` and `superseded_at`.
   `as_of` is a field of `POST /query` (`adele query --as-of`): the latest view gives the
   version that was the latest at that time, the versions view the versions fetched at or
   before it (point 4 gives the SQL). With answer c, a query with `as_of` that reads a
   dataset without versions is refused. `as_of` alone is not enough: "the forecast as known the
   day before delivery" needs a different time for each row, and only the second view can
   express it (`entsoe_load` and its table `forecast` are not written yet):
   ```sql
   SELECT * FROM entsoe_load.forecast_versions
   WHERE fetched_at < delivery_start - INTERVAL 1 DAY
     AND (superseded_at IS NULL OR superseded_at >= delivery_start - INTERVAL 1 DAY)
   ```
   It returns nothing for rows that were backfilled, nor for a value that is only known after
   delivery (the actual load).
4. **Storage.** Decided: c (Renaud, after the measure: "ok, then c is fine"). Three layouts
   were measured:
   - (a) One set of files with every version. The latest view picks the last version of each
     key with a window function, at each query. Built first, then replaced by c.
   - (b) Two folders: the latest values as today, and the versions (the files of a) next to
     them. About 2.6 times the disk of a table without versions, and two writes per fetch
     that must agree.
   - (c) As a, plus a column `superseded_at`: the merge writes the `fetched_at` of the new
     version into the version that it replaces (it rewrites the whole partition anyway, D9).
     Latest = `superseded_at IS NULL`, `as_of` = `fetched_at <= T AND (superseded_at IS NULL
     OR superseded_at > T)`. One set of files, no window function. Added after the review.

   The criterion of this draft: b only if a query on the latest view, filtered on
   `delivery_start`, is more than 2 times slower than the same query on a table without
   versions. The measure (below) gives 2.9 for a on one month of all zones, 1.35 for c.

   Both columns are on every stored row, and they cost little: Parquet stores a timestamp as an
   8-byte integer whatever its precision, keeps the distinct values of a file once, and
   compresses the runs of the same value. One fetch stamps all its rows with one value, and
   most rows have a null `superseded_at`.
5. **Versions before the first fetch.** Decided, with answer b: `versions_since` is the time at
   which `last_scheduled_at` is first set (a scheduled run that succeeded, or the end of a
   backfill that reached the present), written once in `state.json`. An `as_of` before it is
   refused. `describe` prints it, and so does the footer of every query with `as_of` or on a
   `_versions` view.

## The measure of point 4 (2026-11-15)

Synthetic table of the size of neighbours `ws_forecast`: 16 zones, 6 series, 15 minutes, from
2019-05-01 to 2025-12-31: 22,459,392 keys. A second version for 30 % of the keys, a third for
10 %: 31,443,905 stored rows, 1.4 per key. One file per month, zstd, sorted as adele writes.
DuckDB 2.0.0 on the Mac (10 cores), with the settings of a query on the server (4 threads,
2 GB). Files in the cache of the OS; each figure is the median of 5 runs after one warm-up. The
spread between runs was not measured: differences of a few milliseconds mean nothing. Script:
`server/bench/wp3_versions_storage.py`.

| | without versions | a | c |
|---|---|---|---|
| disk | 93 MB | 153 MB (1.64) | 168 MB (1.80) |
| one zone, one week | 4 ms | 7 ms (1.5) | 6 ms (1.35) |
| all zones, one month | 5 ms | 14 ms (2.9) | 6 ms (1.35) |
| all rows, average per zone | 78 ms | 1,409 ms (18) | 156 ms (2.0) |
| count, min, max (`describe`) | 9 ms | 491 ms (56) | 40 ms (4.5) |
| `as_of`, all zones, one month | | 9 ms | 7 ms |
| merge of a 3-day fetch into a month | 30 ms | 45 ms | 35 ms |

Layout b answers the latest view from the files without versions (first column), with
93 + 153 = 246 MB on disk. The count of the first column is fast because Parquet stores the
number of rows of each file. steacher1 has 4 slower cores: the absolute times there will be
higher, the ratios are what the criterion uses.

The merge of c was timed after c was built, in a second run of the script; c's view there is
`storage.select_sql`. That run gave the same picture within a few milliseconds (c: 1.44 on
the month, 2.2 on the whole table, 37 ms for the count).

The disk figures overstate the cost of the two columns: the script stamps each quarter hour
with its own `fetched_at`, where a real fetch stamps all its rows with one value. With the
stamps rounded down to the hour (one stamp per hourly fetch), the columns of c take:

| column | one stamp per quarter hour (the script) | one stamp per hourly fetch |
|---|---|---|
| `value` | 120.3 MB | 120.3 MB |
| `fetched_at` | 20.8 MB | 12.8 MB (0.4 bytes per row) |
| `superseded_at` | 13.9 MB | 8.9 MB |
| all of c | 167.5 MB | 152.5 MB |

Reading: a fails the criterion on the month query (2.9), and an aggregate over the whole table
costs 18 times more (1.4 s on the Mac). c stays within 2 times on every query except the
count (40 ms), with one set of files and one write per fetch. c costs a column and a few lines
in the merge; switching from a to c now costs only code, because no real dataset is stored yet.

## Steps

1. **Measure** point 4 on synthetic data. Done (above).
2. **Decide.** Points 1 to 5 and the answers a to e: D30.
3. **Build**, with tests on synthetic data. Done in the worktree `wp3`:
   - `catalog.py`: accepts `append-only`; refuses a field named `fetched_at` or `superseded_at`
     and a table named `<x>_versions` next to a table `<x>` (in every dataset).
   - `storage.py`: `merge_versions` (point 1, and `superseded_at` of point 4); `select_sql`
     gives the latest version, `versions_sql` every version, both with `as_of`;
     `check_columns` refuses files whose columns don't match the policy; `repartition` keeps
     both columns.
   - `ingest.py`: the merge is chosen per policy, an unknown one fails; the stamp after
     `fetch.py`; `versions_since`; a new version counts as a change (`last_changed_at`).
   - `engine.py`, `app.py`, the client: the two views, `as_of`, the refusals of point 3 and 5;
     a view that can't be created fails only the queries that read it.
   - `checks.py`: the checks run on every stored version, with `fetched_at` in the key, and
     verify that each `superseded_at` is the `fetched_at` of the next version; the published
     figures and the examples run on the latest view.
   - `render.py`: the revisions line of `describe`, `versions_since`, the count of versions;
     the footer.
   - `skills/adele/SKILL.md`: when to use the versions view and when `as_of`.
     `skills/add-dataset/SKILL.md`: an `append-only` `fetch.py` returns no stamp of its own.
   - Tests: `server/tests/test_versions.py`, and one in `test_e2e.py` for `--as-of` through HTTP.
4. **First real dataset.** Decided (Renaud, 2026-11-15): ENTSO-E actual load and day-ahead
   forecast for CH (A65), the dataset planned for POC 2. Its descriptor and `fetch.py` belong
   to WP6, done here for this one dataset. Backfill from 2015 on steacher1, then 1-2 days of
   fetches (Renaud: "we won't wait a week, just 1-2 days"). Whether a revision happens in that
   time depends on ENTSO-E: none was seen in 15 days (below).
   - Done in the worktree (2026-11-15): `datasets/entsoe_load/` (`datapackage.yaml`,
     `fetch.py`), `server/tests/test_entsoe_load_fetch.py`, the measure below, a backfill from
     2015 on the Mac (checks ok). The definitions are drafts by Claude, at Renaud's request;
     Renaud confirmed the unit (MW) and the one-hour move.
   - QA (2026-11-15, instead of Renaud checking the examples): `checks.yaml` with 50 published
     figures, all reproduced (ENTSO-E Statistical Factsheets 2019-2025, Kazmi & Tao 2022,
     Tzortzis et al. 2023); the figures left out and why: `qa/published_figures_entsoe_load.md`.
   - To do once WP1 is done: the backfill and 1-2 days of fetches on steacher1 (`TODOs.md`, V1).
   - Landing in `main`: Renaud relaxed the rule of the WP1 doc ("WP3 lands in `main` after the
     week") on 2026-11-15; WP3 still reaches steacher1 only once WP1 is done.

## How late ENTSO-E corrects the load (2026-11-15)

The inventory (`docs/datasets-inventory.md`) says that the actual load "is corrected days
later". No measure backs it: POC 2 was planned, not built, so it left no data. What exists:

- The swissgrid project compared two of its downloads, two days apart (2026-10-29 and
  2026-10-31), on the hours up to 2026-10-15: 17,135 hours of actual load and 17,135 of
  forecast, 0 revised.
- Its collector of forecast versions (two runs, 2026-10-28 and 2026-11-01) saw one version of
  each of the 122 hours of the load forecast.
- New, by Claude: the raw answers of 2026-10-31 (every year from 2015) against fresh answers
  for the same windows, both parsed by `datasets/entsoe_load/fetch.py`. Actual load: 103,714
  hours in both, 0 different, also for the hours that were less than a day old on 2026-10-31.
  Forecast: 103,728 hours, 0 different. Script and output:
  `measure_load_revisions.py` and `measure_load_revisions.txt` in the scratchpad of this
  session, not kept; the fresh answers are kept there too, for a later comparison.

So in 15 days ENTSO-E corrected no value of the Swiss load, old or recent. A later correction
(months) can't be ruled out, but no month changed between 2026-10-31 and 2026-11-15, the
turn of a month included. The lookback can't be set from the corrections; it is P14D, which
costs two small requests per hour. The 1-2 days on steacher1 will most likely store no
second version of a real value: the tests on synthetic data stand for that part. Some recent
hours look wrong (the actual load at night on 2026-11-03, 11-10 and 11-14 is about half of
the forecast, `fetch.py`); if ENTSO-E corrects them, adele will store the versions.

## Text for `SPEC.md`, Revisions

Proposed to replace the bullet `append-only`; Renaud put it in `SPEC.md` on 2026-11-15:

> - `append-only`: adele keeps every version of a row. A fetch stores a row when its key is new
>   or one of its values changed, with `fetched_at`, the time at which adele got it.
>   `<id>.<table>` returns the latest version of each row, `<id>.<table>_versions` every
>   version. `as_of=<timestamp>` returns what adele held at that time. Versions start with the
>   first scheduled fetch (`versions_since`): rows backfilled before carry the time of the
>   backfill, so an earlier `as_of` is refused. `fetched_at` is not the time at which the source
>   published a value: a value may look later than it was, never earlier.

The list of `SPEC.md` also lacks `none` (D15).

## Done when

- `validate` accepts `revisions: append-only`. The tests cover: a fetch without changes adds no
  version, a revised value adds one, A --> B --> A, a value that becomes null, a row that the
  source no longer sends, a backfill run twice, a clock set back, `repartition`, the checks with
  two versions, the latest view and `as_of` return the right value, an `as_of` before
  `versions_since` and an `as_of` over a dataset without versions are refused. Done.
- The measure of point 4 is in this file. Done.
- Point 4 decided, and built if it is not a. Done: c.
- The first dataset was fetched for 1-2 days on steacher1. If ENTSO-E revised a value in that
  time, a query with an `as_of` before the revision returns the old value; if not, the tests on
  synthetic data stand for it.
- `describe` and the skill explain how to read the versions. Done.

## Not in WP3

- The 7 other datasets that wait for versions (WP6).
- The Swissgrid files, which also need raw answers kept and whole files compared (WP4).
- The history of a table without a time column (D22), which needs WP2 first.
- `pull` and versions in a local copy (`TODOs.md`, V1).
- `adele.available_after`: a delay declared per dataset (weathernext3: a run is readable about
  7 h after its start), for `as_of`.
- Converting a stored dataset from `overwrite` to `append-only`.
- A change of `fetch.py` (MW --> MWh) or of the schema of a dataset that has versions (answer
  d: "probably not anytime soon. we first need a V1 running and we'll see then").
- Rows that the source stops sending: kept for now (answer e, `TODOs.md`, V2).
- From POC 2: MW --> MWh at ingestion belongs to the descriptor of the load (WP6). A join of the
  load with the prices works on the server today, but not with `as_of` (answer c).

## Open questions

None. The two questions on the stamps of `entsoe_load` were decided on 2026-11-15 (Renaud:
"Okay with your defaults but compare first"; evidence in `qa/published_figures_entsoe_load.md`,
"the timing of the forecast"):

1. The forecast is not moved in 2015-2018, although its error is lowest with a move of one
   hour in those years: one criterion, and a forecast may lag for other reasons. A warning says
   so.
2. The actual load keeps the move of one hour in January-August 2023, one rule for the whole
   time before 2025. The comparison with Swissgrid's Energy Statistic (hourly changes, by
   month) can't decide it: the actual load matches the statistic one hour later in July-December
   2022 and January-March 2024 (correlation 0.99 to 1.00, levels within 31 MW) and in
   September-December 2023 (0.82 to 0.94), but at no offset in January-August 2023
   (correlation 0.25 or less, levels 380 to 590 MW apart): it is not the measured load then.
   The forecast never matches the statistic well (0.12 to 0.32 from 2023), so it can't decide
   either.

## Log

### 2026-11-15, review by Fable before the build

Ten findings. Claude checked each claim about the code against the source: all hold. The main
one: step 3 missed the code that reads the files through the declared columns
(`storage.select_sql`): the checks after a fetch, `repartition`, `describe`, the footer of a
query. Five findings needed Renaud (his answers):

- a. `fetched_at` = when `fetch.py` returned, not the start of the run: "a ok".
- b. `versions_since` defined as above, with a line in the footer: "b ok".
- c. `as_of` over a dataset without versions: "c refuse, try to keep it as simple as possible
  for now".
- d. A changed `fetch.py` or schema creates versions of every row: "d yes, not in WP3, and
  probably not anytime soon".
- e. Rows that the source stops sending: "e defer this usecase to later, put in TODO.md".

The others were decided by Claude and built: one function per view for every reader; the
filter of `as_of` before the choice of the latest version; `as_of` parsed by the server into a
timestamp before it enters SQL; the wording of `describe`; more tests; the wording fixes of
this file. Option c of point 4 comes from this review.

### 2026-11-15, build (worktree `wp3`)

- Decided by Claude during the build:
  1. The stamp has microseconds: two fetches in the same second must not get the same stamp.
  2. The clock check compares with the latest version of each partition that the merge
     writes, not of each key: simpler, and as strict.
  3. A query with `as_of` that reads no dataset (`SELECT 1`, or only `read_parquet`) is
     refused: `as_of` would do nothing.
  4. The reserved names (`fetched_at`, `<x>_versions`) are refused in every dataset, not only
     in `append-only` ones: a dataset can't then become `append-only` with a name that clashes.
  5. A view that can't be created (files that don't match the descriptor) becomes a view with
     the same columns that fails when read. Before, such a view stopped every query of every
     dataset; a policy changed by mistake in a descriptor would now cause that.
  6. The latest view shows the declared columns only, not `fetched_at`: `SELECT *` gives the
     same columns as with `overwrite`.
  7. `describe` gives the count of versions next to the count of rows.
  8. `versions_since` is written only for `append-only` datasets.
- 22 new tests; 301 pass. `validate` passes on the two real descriptors.

### 2026-11-15, point 4: layout c (303 tests pass)

Renaud asked whether `fetched_at` and `superseded_at` sit on every row, and whether a stamp
with microseconds is costly. Both are on every stored row; the precision doesn't change the
size (the measure above, with one stamp per hourly fetch). His answer: "ok, then c is fine".
Built in the worktree, replacing a. Decided by Claude:

1. `superseded_at` shows in the versions view: with it, an agent can write "the version valid
   at a time per row" as a filter, without a window function.
2. With `as_of`, the versions view shows a `superseded_at` later than `as_of` as null: as
   adele held it then, that version was still the latest.
3. The checks after a fetch verify that each `superseded_at` is the `fetched_at` of the next
   version of its key (null on the latest): a broken chain would make the latest view show
   two rows for a key, or none.
4. Files written in layout a fail the column check like a changed policy. Only the tests of
   this worktree wrote such files.
5. D30 is amended rather than followed by a new entry: it was never committed.

### 2026-11-15, step 4: entsoe_load

Renaud: "1 done" (the text for `SPEC.md`), "2 sure, go ahead" (commit on `wp3`: 86a4afa),
"3 yes" (ENTSO-E load for CH as the first dataset), "we won't wait a week, just 1-2 days".
Decided by Claude:

1. Two tables, `actual` (A16) and `forecast` (A01), each with key (`bidding_zone`,
   `delivery_start`): the two series have their own versions, and a forecast "as known the day
   before" is a query on `forecast_versions` alone. `bidding_zone` as in
   `entsoe_day_ahead_prices`, so that the two join; only CH for now.
2. The value stays in MW, the mean power of the hour, as served. POC 2 planned MW --> MWh at
   ingestion; MW keeps the value independent of the resolution. Renaud decides before the
   backfill on steacher1 (a later change of unit can't convert stored versions, answer d).
3. The actual load before 2024-12-31 23:00 UTC moves back one hour (end stamps), as in the
   swissgrid project, whose evidence is cited in `fetch.py`. Also to confirm before the
   backfill on steacher1, for the same reason.
4. `fetch.py` parses the XML itself (curve types A01 and A03) and uses entsoe-py only for the
   requests; it refuses another unit, curve type or resolution.
5. Lookback P14D (above), horizon P2D, every PT1H.
6. The holes and the low stretches of the actual load are kept as served, and listed as draft
   warnings for Renaud.
7. A test of `fetch.py` on synthetic answers, with entsoe-py stubbed: the first test of a
   dataset's `fetch.py`.

Renaud, after the step: "confirm choice 2 and 3. go ahead with defs. commit all on wp3, too".
Claude wrote the definitions as drafts (title, description, the description of each table and
field, four warnings, two examples) and ran the examples on the backfill of the Mac. The
warnings come from the measures in `fetch.py` and from the swissgrid project's comparison with
the Energy Statistic (QA 5 c7). The licence stays a TODO, as in `entsoe_day_ahead_prices`.

### 2026-11-15, which ENTSO-E series are revised

Renaud: "a: do it, b: ok, for the series that a shows to be revised". Every Swiss ENTSO-E series
that the swissgrid project saved on 2026-10-31 was asked again and compared value by value
(`qa/revisions_entsoe_ch.md`). Revised: generation per type, physical flows, scheduled
exchanges, imbalance volume (rarely). Not revised in 15 days: load, the three price series,
installed capacity; the wind and solar forecasts by a few tenths of a MW only. Next, (b): the
datasets of the revised series, `append-only`.

### 2026-11-15, QA from published figures

Renaud: "Instead of me checking the two examples, can you forage for publications where there
are some numbers and use them as QA, like we did in the other ENTSO-E dataset?" A research
agent found 15 documents; 50 figures went into `checks.yaml`, all reproduced. Found on the way:

- The forecast is a copy of the actual load (as served) from September 2021 to December 2022:
  a warning in `datapackage.yaml`.
- The timing of the forecast is not settled (open questions 1 and 2).
- The ENTSO-E factsheets use the stamps as served; their hours match adele's plus one hour
  before 2025, which fits the move of `fetch.py`.

Decided by Claude: checks on UTC years (the factsheets give UTC hours); MW to 0.5 and TWh to
0.05 (their rounding); for Kazmi & Tao, MAE and ME only, with tolerances for their undescribed
filter, on ENTSO-E's stamps (the alignment they used); the 2023 and 2025 totals left out.
