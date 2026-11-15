# WP3: versions

Draft by Claude, 2026-11-15, not accepted. From `PLAN.md` (WP3), `SPEC.md` (Revisions),
`TODOs.md` (POC 2, V1) and `docs/datasets-inventory.md` (gap G3).

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
- A row that the source no longer sends is kept, as with `overwrite`.
- The build runs on the Mac with synthetic data, next to WP1. It goes to steacher1 once WP1 is
  done.

## Design

Each point has Claude's recommendation. Renaud decides.

1. **When a version is stored.** (a) Only when the key is new or a value differs from the latest
   stored version of that key. (b) Every fetched row: an hourly fetch with a lookback of 3 days
   would then store each unchanged value 72 times. Recommended: a. The merge is close to
   `merge_append` of D15: there a changed value is an error, here it becomes a new version.
2. **What `fetched_at` is.** The start of the fetch run, in UTC, the same for every row and every
   table of that run. The server adds the column: the descriptor doesn't declare it, and the
   catalog refuses a field of that name. The primary key of the descriptor stays the key of a
   value; in the files, the key is the primary key plus `fetched_at`.
3. **How queries see the versions.** The view `<id>.<table>` keeps its meaning (the latest
   version per key), so a query written for `overwrite` works unchanged. A second view,
   `<id>.<table>_versions`, holds every version with its `fetched_at`. `as_of` alone is not
   enough: "the forecast as known the day before delivery" needs a different time for each row,
   and only the second view can express it (`entsoe_load` is not written yet):
   ```sql
   SELECT * FROM entsoe_load.load_versions
   WHERE fetched_at < delivery_start - INTERVAL 1 DAY
   QUALIFY row_number() OVER (PARTITION BY zone, delivery_start ORDER BY fetched_at DESC) = 1
   ```
   Recommended: both views, and `as_of` as a field of `POST /query` (`adele query --as-of`). The
   server builds the views for each query already (`engine.connect`), so with `as_of` it adds
   `fetched_at <= as_of` to both, and the SQL of the agent stays the same.
4. **Storage.** (a) One set of files with every version. The latest view picks the last version
   of each key with a window function, at each query. (b) Two folders: the latest values as
   today, and the versions next to them. (a) costs time at each query. (b) costs about twice the
   disk, and two writes per fetch that must agree. Recommended: a, after a measure on synthetic
   data of the size of the largest planned table (neighbours `ws_forecast`, 22.4 million rows).
   Then b only if a query on the latest view, filtered on `delivery_start`, is more than 2 times
   slower than the same query on a table without versions.
5. **Versions before the first fetch.** Backfilled rows all carry the date of the backfill as
   `fetched_at`, so an `as_of` before that date says nothing about what the source had published
   (`TODOs.md`, V1). Recommended: `describe` prints "versions since <first fetch>", and an
   `as_of` before it is an error. Claude proposes a sentence for `SPEC.md`, Revisions.

## Steps

1. **Measure** point 4 on synthetic data. The numbers go into this file.
2. **Decide.** Renaud answers points 1 to 5. Claude writes the decision at the end of
   `DECISIONS.md` and the text for `SPEC.md`.
3. **Build**, with tests on synthetic data:
   - `catalog.py`: accept `append-only`; refuse a field named `fetched_at`, and a table named
     `<x>_versions` next to a table `<x>`.
   - `storage.py`: the merge of point 1; the two views; a check that refuses files whose columns
     don't match the policy, as `check_layout` refuses files of another partition size.
   - `ingest.py`: choose the merge (now at line 498); a new version counts as a change
     (`last_changed_at`).
   - `engine.py`, `app.py`, the client: the views, `as_of`.
   - `render.py`: the revisions line of `describe`, the versions view, "versions since".
   - `skills/adele/SKILL.md`: when to use the versions view and when `as_of`, with the example
     of point 3.
   - The checks of published figures run on the latest view.
4. **First real dataset.** Proposed: ENTSO-E actual load for CH (A65). Its actual load is
   corrected days later, and it was the dataset of POC 2. Its descriptor and `fetch.py` belong to
   WP6, done here for this one dataset. Backfill from 2015 on steacher1, then a week of fetches.

## Done when

- `validate` accepts `revisions: append-only`. The tests cover: a fetch without changes adds no
  version, a revised value adds one, the latest view and `as_of` return the right value, an
  `as_of` before the first fetch is an error.
- The measure of point 4 is in this file.
- The first dataset was fetched for a week on steacher1 with at least one revision stored, and a
  query with an `as_of` before that revision returns the old value.
- `describe` and the skill explain how to read the versions.

## Not in WP3

The 7 other datasets that wait for versions (WP6). The Swissgrid files, which also need raw
answers kept and whole files compared (WP4). The history of a table without a time column
(D22), which needs WP2 first. `pull` and versions in a local copy (`TODOs.md`, V1).
`adele.available_after`, the time when the source published a value. Converting a stored
dataset from `overwrite` to `append-only`.

## Open questions

1. Design points 1 to 5: the recommendation, or another way?
2. The first dataset: ENTSO-E actual load for CH?

## Log

(empty)
