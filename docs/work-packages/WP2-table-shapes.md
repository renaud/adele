# WP2: table shapes

Draft by Claude, 2026-11-15. From `PLAN.md` (WP2), D22, D26, `docs/datasets-inventory.md`
(sections 5 and 6, gaps G1 and G2a) and `TODOs.md`. Renaud accepted the 18 choices on
2026-11-15: D32.

## Where WP2 stands (2026-11-15)

- Built in the worktree `wp2` (branch `wp2`, from `dd76869`), with tests on synthetic data
  (`server/tests/test_table_shapes.py`), and landed in `main` on 2026-11-15. Nothing on
  steacher1 (it runs `32237db`), no real dataset uses it yet.
- The choices that D22 and D26 left open were made by Claude during the build (list below),
  accepted by Renaud on 2026-11-15 ("18 choices accepted"): D32.
- Open: the text for `SPEC.md` below (Renaud pastes it).
- With the code of `main`, `list`, `describe`, the merged descriptor and the footer of the
  stored datasets (entsoe_day_ahead_prices, weathernext3 in `data_nosync/`) print the same text
  as before, character for character.

## Goal

A table can be by calendar day, month or year in a zone (D26), or have no time column (D22).
A dataset can hold tables of different shapes, each with its own resolution, partition and
zone. This frees 13 datasets of the inventory for WP6 (section 3: registers, lists of
stations, tables by local day, month or year).

## What is settled

- D22: a table without a time column is one file, replaced whole at each fetch; a row that the
  source drops goes; an empty answer is an error; `list` and `describe` show its row count and
  the time of its last change.
- D26: `delivery_date`, `delivery_month`, `delivery_year`, all of type date, a month and a year
  stored as their first day; one `timezone` per table, an IANA name or `UTC`, never `CET`; no
  `resolution`; a fetch keeps a period that overlaps the window; `describe` prints the zone and
  the join with a table in UTC, with the plain filter that lets DuckDB skip files.
- SPEC.md, Time conventions, already says both (Renaud's text).

## Choices made during the build (accepted by Renaud, 2026-11-15)

1. **`adele.format_version: 2`** for the new shapes: an `adele:` block per table, a date column,
   a table without a time column. A descriptor of version 1 loads as before. Why: steacher1 runs
   `32237db`; a server that reads only version 1 refuses a descriptor of version 2. Without the
   bump it would load a table block and ignore it (a resolution lost without an error).
   `docs/datasets-inventory.md` (section 5) already said that these keys make version 2.
2. **The `adele:` block of a table** holds `resolution`, `partition` and `timezone`; any other key
   is refused (a misspelt key must not be ignored). `window` stays per dataset: it says what the
   `start` and `end` of `fetch()` mean, and there is one call per dataset.
3. **The package-level `resolution` and `partition` stay**, as the default of every table that
   sets none. The package-level `resolution` applies to the tables with `delivery_start` only (a
   date column gives its own period; an instant has none). So the three descriptors stay valid
   without a change. weathernext3 could move its `resolution` (commented "of
   solar_radiation") into the block of `solar_radiation`; not done, the file is Renaud's.
4. **The window of a table**: `adele.window` when the dataset declares it (each table with a
   time column must then have it, a datetime in its primary key, as before), else the table's own
   time field, which must be in its primary key. Before, the default was `delivery_start` for
   every table, so a table of `valid_at` needed an explicit window. A table by calendar period
   is partitioned by the month (or day) of its date.
5. **The zone**: `UTC`, or a name with a `/` that DuckDB knows (`pg_timezone_names()`). DuckDB
   knows `CET`, `EST` and the like, so the rule "an IANA name" is checked by the `/`. A
   `timezone` at package level is refused with a pointer to the table block.
6. **The overlap** is computed in DuckDB: the period starts at `timezone(zone, date::TIMESTAMP)`
   and ends at the same of the next period. Tested at the edge: the window [2026-03-31 21:00,
   22:00) UTC keeps March and 2026-03-31; [22:00, 23:00) keeps April and 2026-04-01.
7. **A month or a year not on its first day**: the fetch fails and writes nothing (for the rows
   of the window), and the checks after each fetch count such rows in the stored data.
8. **Timestamps returned for a date column**: the schema check fails with a hint ("return
   `datetime.date` values, e.g. with pandas `.dt.date`"). Not converted: a timestamp at 00:00 UTC
   or at local midnight would give different dates.
9. **The file of a table without a time column** is `<table>/table.parquet`, written only when
   the table changed. So its time of change is the time at which the file was written: no new
   field in `state.json` (D23). `rows_changed` counts the new or changed rows plus the rows that
   went.
10. **Such a table in a fetch of several windows** (the gaps of `revisions: none` are fetched in
    one child process): the answer of the last window is the table.
11. **Such a table with `revisions: none`**: left out of the gaps. It is refreshed when a fetch
    runs; a run with no gap calls no `fetch()` and leaves it as it is.
12. **Such a table with `revisions: append-only`**: refused for now. D22 wants a dropped row to go,
    and D30 has no mark for a withdrawn version (`TODOs.md`, V2). It waits for the first dataset
    that needs it.
13. **`revisions: none` with a date column as window**: refused. `none` fetches the values of the
    window column that aren't stored, so every table with a time column must share one window
    column of type datetime (as today, where it is `delivery_start` or `adele.window`).
14. **No partition `year`.** A table by year gets one small file per year (named `<year>-01`, the
    month of its date), a table by month one per month. Cheap to add when a table needs it.
15. **What agents read.** `list`: the resolution column says `calendar month (Europe/Zurich)`
    or `no time column`, the coverage gives one range per window column (a date range with its
    zone), and a dataset of tables without a time column shows `no time column, 3 rows`.
    `describe`: per table by period `coverage` (2026-03 .. 2026-04), `resolution` ("none: one
    row per calendar month in Europe/Zurich"), `timezone` and `join`; per table without a time
    column `coverage: no time column ...; last changed <time>` and no `resolution` line; two
    sentences more in `conventions` when such tables exist. Footer: `calendar month in
    Europe/Zurich (delivery_month)`, `no time column`. The merged descriptor keeps
    `resolution_periods` on every table (empty when there is none), and gives `last_changed_at`
    in place of `coverage` for a table without a time column.
16. **The join printed by `describe`** for a table by day: `date_trunc('day', u AT TIME ZONE
    'Europe/Zurich') = delivery_date`, with the plain filter `u >= '2026-03-28' AND u <
    '2026-03-31'` for 2026-03-29. Tested: it joins 92 quarter-hours to 2026-03-29.
17. **`repartition`** leaves a table without a time column as it is.
18. **Skills.** `skills/adele/SKILL.md`: two rules (a table by calendar period has no resolution
    and its join is in the card, so `epoch(resolution)` doesn't apply; a table without a time
    column holds what the source delivers now). `skills/add-dataset/SKILL.md`: the shapes, the
    zone to ask for, dates as `datetime.date`, a table without a time column returned whole.

## The decision

D32 in `DECISIONS.md`, written 2026-11-15 after Renaud accepted the 18 choices.

## Text for `SPEC.md` (Renaud edits it)

1. Catalog, "extensions", replace the first sentence:

   > all adele properties go in one `adele:` block at package level (format_version,
   > resolution, refresh, revisions, window, partition, expected_spacing, secrets, plus the
   > computed ones). A table can have its own `adele:` block for `resolution`, `partition` and
   > `timezone` (the zone of a table by calendar period); it overrides the package-level key.

2. Adding a dataset, `fetch.py`, after "with the rows whose window time falls in [start, end)":

   > A table by calendar period returns the periods that overlap [start, end). A table without
   > a time column returns the whole table at each call.

3. Storage, the second item:

   > a dataset is one or more tables; each table is stored as Parquet, partitioned by month of
   > its window time (by default its time column), or by day when the dataset or the table
   > declares `partition: day`. A table without a time column is one file.

## Not in WP2

- A period with its own end (ENTSO-E outages, Swissgrid's reserve auctions) and a state at a
  date (the BFE Energie Reporter): D26, Limits. They wait for the first dataset that needs them.
- A table without a time column in an `append-only` dataset (choice 12).
- The datasets themselves: WP6 (13 datasets wait for WP2).
- `pull` and a local copy: the join of the card names its zone, so it gives the same answer
  on a laptop whatever the zone of the machine.

## Done when

- The descriptors of format 1 load and answer as before (the 317 tests of before pass; the
  output of the stored datasets is unchanged).
- A synthetic dataset with a table by quarter-hour, by local day, by local month and without a
  time column fetches, stores, checks and describes itself (`test_table_shapes.py`).
- Renaud has accepted or changed the choices above. Done 2026-11-15: all 18 accepted (D32).
- The first real dataset of WP6 with such a table runs (on the Mac, then on steacher1 after
  WP1).

## Log

### 2026-11-15, build (worktree `wp2`)

- Before: 317 tests pass on `dd76869`. After: the 317 unchanged (one test now names version 3
  as unknown) plus 34 in `test_table_shapes.py`.
- The real descriptors validate (`adele-server validate`). `list`, `describe`, the merged
  descriptor and the footer of the stored datasets are identical with `main`'s code and with
  this branch (the first run showed one difference, the merged descriptor dropped the empty
  `resolution_periods` of `weathernext3.weather`; fixed, choice 15).
- Checked in DuckDB 2.0.0 before the build: `timezone('Europe/Zurich', DATE '2026-03-29'::TIMESTAMP)`
  is 2026-03-28 23:00 UTC and the next day starts at 2026-03-29 22:00 UTC (23 hours);
  `pg_timezone_names()` holds `CET` and `EST`; pandas columns of `datetime.date` reach DuckDB as
  DATE, `pd.to_datetime` as TIMESTAMP.

### 2026-11-15, accepted and landed

- Renaud accepted the 18 choices ("18 choices accepted. go"): D32 in `DECISIONS.md`. Then
  "land": the branch `wp2`, rebased on `main`, merged with `--ff-only`.
