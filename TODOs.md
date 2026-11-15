# TODOs

## Renaud, now

- `datasets/entsoe_day_ahead_prices/datapackage.yaml`, the `TODO(Renaud)` items: description of
  the dataset, licenses, description of `resolution`, and the first warning (it says
  2025-10-01, but CH switched to 15 minutes on 2026-11-04 and FR on 2025-09-30). Labels: done.
  New warnings under `adele.warnings` (accepted 2026-11-13; drafts by Claude, his to rewrite):
  - coverage of 2015: DE_AT_LU and FR start on 2015-01-05, CH on 2015-01-01.
  - 2024-06-26: EPEX's auction for DE_LU, FR and four other zones was decoupled; ENTSO-E
    carries the coupled price.
  - FR, delivery day 2025-09-30: 96 quarter-hours with 4 equal values per hour (kept as
    published, answer 5a). Fits in the first warning.
  Not done yet (asked again 2026-11-14: "still TODO on my side"). When Renaud says it's done,
  Claude adds the example with RTE's definition of negative hours and sets `verified_at` on the
  March 2026 example (with `delivery_day` cast to DATE). Claude changed two lines in this file
  on Renaud's request: `adele.format_version: 1` (D19, was `format: 1`) and
  `secrets: [ENTSO_TOKEN]` (D18); keep them when saving. Once D20 is built: mark the warnings that
  every query footer must show (`{text: ..., footer: true}`); until then the footer shows none.
- SPEC.md, two texts accepted 2026-11-13:
  - Time conventions, replaces the line on resolution:
    ```
    - every table has a `delivery_start` column.
    - resolution is an ISO 8601 duration (PT15M, PT1H, P1D). When it differs between series or
      changes over time, each row carries it in a `resolution` column, and the catalog lists the
      periods of each series, computed from the data.
    ```
  - Security, replaces the "read-only" bullet (text changed 2026-11-14 with D24):
    ```
    - read-only: the server's DuckDB can read the Parquet files of the catalog and nothing else
      (no other local file, no network, no extension install, no change of settings by a query).
      DuckDB can't make an allowed folder read-only, so the server runs only what DuckDB's
      parser shows to be a read (one SELECT, with table functions from a list; no other
      statement, also no EXPLAIN), and the query process runs as a user that can only read the
      data.
    ```
- SPEC.md, five texts from D12-D18 (2026-11-13), paste-ready:
  - Catalog, extensions bullet, replaces it:
    ```
    - extensions: all adele properties go in one `adele:` block at package level
      (format_version, resolution, refresh, revisions, window, partition, expected_spacing,
      secrets, plus the computed ones). `adele.format_version` is the version of the
      descriptor format (1); the server refuses another. Fields get a free-text `unit`
      (EUR/MWh, MW, MWh).
    ```
  - Adding a dataset, replaces the list and the paragraph after it:
    ```
    A dataset is a folder in git (today `datasets/<id>/`; later one repository per dataset):

    - `datapackage.yaml`: the catalog entry (see Catalog).
    - `fetch.py`: one function `fetch(start, end)` that returns a pyarrow Table or pandas
      DataFrame with the rows whose window time falls in [start, end). The window time is the
      delivery time, unless `adele.window` names another time column (e.g. the init time of a
      forecast run). A source that only serves "everything" or "latest" may ignore the window;
      the server filters. `fetch.py` declares its own dependencies (PEP 723). The server runs
      it in a separate process that gets only the secrets listed in `adele.secrets`.
    - `checks.yaml` (optional): figures published by others that the data must reproduce. The
      server runs them after each fetch; a value outside its tolerance sets the status to
      failing.

    Each scheduled run fetches [last - lookback, now + horizon), where `last` is the time of
    the last scheduled run that succeeded (`now` for the first run). `lookback` and `horizon`
    are set in `adele.refresh`. The lookback catches revisions and late data; the horizon
    covers data published before delivery (e.g. day-ahead prices). The initial backfill calls
    `fetch` on successive windows.

    After a stop (the server was down, the source failed, a long backfill ran), the next run so
    fetches everything since the last run that succeeded, and no hole stays. A run that fails
    is tried again from the same place for one lookback. Then adele gives up on the older part,
    writes which part to the alert log, and returns to [now - lookback, now + horizon). A
    dataset can set `adele.refresh.max_window`: a longer window is fetched in pieces of that
    length, oldest first, and a piece that fails does not stop the later ones.
    ```
    (The two paragraphs on the window are in SPEC.md since 2026-11-15, D25. Keep them when
    pasting the rest of this block.)
  - Time conventions, the interval rule and coverage, replace those two bullets:
    ```
    - a timestamp marks the start of its interval; intervals are half-open: [start, start +
      resolution). A value at an instant (e.g. cloud cover at 12:00) has no interval: its table
      has `valid_at` instead of `delivery_start`, and no resolution.
    - coverage = first and last delivery interval (or instant) present, and the range of the
      window column when it isn't the delivery time.
    ```
  - Revisions, a third policy after `append-only`:
    ```
    - `none`: values never change once published (e.g. forecast runs). adele fetches only the
      parts of the window that it doesn't hold yet; a changed value is an error.
    ```
  - Storage, the partition bullet, replaces it:
    ```
    - a dataset is one or more tables; each table is stored as Parquet, partitioned by month of
      its window time (by default the delivery month), or by day when the dataset declares
      `adele.partition: day`.
    ```
- SPEC.md, one text from D22 and D26 (2026-11-15), paste-ready. Time conventions, replaces
  "every table has a `delivery_start` column" of the text above and the rule on local time:
    ```
    - a table has one time column, or none:
      - `delivery_start`: the start of an interval of fixed duration, in UTC.
      - `valid_at`: an instant, in UTC.
      - `delivery_date`, `delivery_month` or `delivery_year`: a calendar day, month or year in
        the time zone that the table declares (`timezone`, e.g. Europe/Zurich), stored as a
        date. A month and a year are stored as their first day. `describe` prints the
        expression that joins such a table with a table in UTC.
      - none (a register of plants, a list of stations): each fetch replaces the whole table.
    - all timestamps are stored in UTC. A calendar period is stored as a date, never as a
      timestamp: a local day lasts 23 to 25 hours.
    ```
- SPEC.md, one sentence from D27 (2026-11-15), paste-ready. Adding a dataset, at the end of the
  paragraph on `max_window`:
    ```
    It can also set `adele.refresh.timeout`, the time limit of one call of `fetch.py`.
    ```
- SPEC.md, two texts from D20-D21 (2026-11-14), paste-ready:
  - Keys or prose, the traps bullet, replaces it:
    ```
    - traps --> prose. A trap about one field goes in the `description` of that field. A trap
      about the dataset goes in `adele.warnings`, a list of short sentences. A warning that
      matters for every query is marked `{text: ..., footer: true}`: the query footer shows it.
    ```
  - Agent access, step 3, the footer sentence, replaces it:
    ```
    Every result ends with a short footer for the datasets that the query read: resolution,
    units, the warnings marked for the footer, freshness. An agent that skipped `describe`
    still gets the main warnings next to the numbers.
    ```
  - Time conventions, after the freshness bullet:
    ```
    - expected spacing: a dataset can declare how often its window values appear (e.g. one
      forecast run per hour), in periods like resolution. Each expected value that is missing
      between the first period and the last stored value sets status to failing.
    ```
- `datasets/weathernext3/datapackage.yaml`: definitions accepted 2026-11-14. Check the licence
  notice "Copyright 2024-6 Google LLC" (copied from the swissgrid notes) against Google's terms.

## V0

POC, planned 2026-11-13: a thin vertical slice. One dataset (ENTSO-E day-ahead prices, zones
CH, DE, FR, from 2015), every layer with as little code as possible. Not in the POC:
`append-only` and `as_of`, `pull`, email alerts (status changes go to the log), a scheduler
inside the server (cron instead), `stale`, backups, column profiles, `search`.

1. Spike: the DuckDB lockdown (security item below), and frictionless-py on the descriptor
   sketch of SPEC.md (`unit`, `categories`, `adele:`).
   Done 2026-11-13: D10, `server/tests/test_engine.py`. frictionless-py 5.21 ignores
   `categories` (the server checks the Table Schema v2 shape itself) and requires `path` (the
   server fills it).
2. Dataset 1 without a server: run the draft skill `add-dataset` (Renaud writes the
   definitions), write `fetch.py`, backfill into month partitions in `data_nosync/` (D7).
   Done 2026-11-13: `fetch.py`, backfill 2014-12-31 to now (372k rows), profile clean (no gap,
   23/25-hour days complete). December 2025 averages match EPEX's monthly report to the cent
   (CH 114.09, DE-LU 93.47, FR 68.73). `resolution` column accepted. `skills/add-dataset`
   revised from what happened. Open: Renaud's definitions (top of this file).
3. Server: `adele-server fetch <id>`, run by cron: fetch --> normalize --> schema check -->
   merge into month partitions (temp file, then rename) --> checks --> `state.json`
   (last_fetched_at, last_changed_at, status, last error). HTTP: list, describe, query. The
   server renders the describe card and the query footer as text. Coverage, row counts and
   `duckdb_type` are computed from the Parquet files on each request. For the footer, DuckDB's
   `json_serialize_sql(sql)` gives the tables that a query reads (CTE names included, so filter
   them against the catalog). `get_table_names()` returns nothing when the tables are views
   (tested with duckdb 2.0.0).
   Done 2026-11-13 (`server/`, 57 tests, with a time limit per fetch). Systemd units drafted in
   `deploy/` (not tried).
4. Client (`list`, `describe`, `query`; D5, D6) and the consumer SKILL.md.
   Done 2026-11-13: `client/`, `skills/adele/SKILL.md` (draft, after reading PUDL's skills).
5. QA: 10 to 15 questions, half aimed at a trap, answers accepted by Renaud. Each runs 3 times
   in a fresh headless session that has only the skill and the CLI. Read every transcript (did
   the agent call `describe`? why did it fail?). Fix each failure by normalization at
   ingestion, else a warning, else an example query. Then run `review-dataset`.
   Pilot 2026-11-13 (one run per question, before Renaud accepted the questions): results in
   `qa/entsoe_day_ahead_prices.md`.
   Changed 2026-11-13 (Renaud: "the figures ARE the QA"): the 79 published figures that match
   (`qa/published_figures.md`) become checks that the server runs after each fetch
   (`datasets/<id>/checks.yaml`; a drift sets the status to failing). No 3-run agent QA. The
   20 agent questions (20 of 20 right, one run each) stay as a regression set: rerun once when
   the skill or the describe card changes (about 4 USD).
6. Linux server (steacher1, decided 2026-11-13): one week of daily fetches, unattended. Then
   three faults on purpose (a renamed column, a duplicated row, an undeclared zone code); each
   must set status to failing. Access: HTTPS through Caddy (decided 2026-11-13,
   `deploy/README.md`); ask IT before opening ports 80 and 443.

Done when: the lockdown holds against the breakout list; the published figures match after
every fetch; agents answer the regression questions correctly; a week of daily fetches shows
correct freshness; the three faults are caught.

WeatherNext 3, the next dataset (2026-11-13: CH only, all 24 runs per day, a sample of a few
days now, more on steacher1): notes in `docs/weathernext3.md`. Decided 2026-11-13: window on
init_time (D14), defaults of the sample plus runs of 2024-2025, `revisions: none` (fetch
only runs not stored yet), partitions by day, a `checkpoint` column, ssrd and cloud cover
(total, low) for now, clouds in their own table with `valid_at`; no temperature or wind yet.
History of the clouds later. Done 2026-11-13: the sample (9 solar runs, clouds of 2 runs),
definitions accepted 2026-11-14. Open: whether the pass-1 pull of 2026-10-28 ran on steacher1
(Renaud checks). Done 2026-11-15: the backfill on steacher1 (the 2024-2025 runs, every run from
2026-11-12 00 UTC), with the clouds of all 9 sample runs (WP1 log).

Packaging: one repository per dataset (decided 2026-11-13; reasons: owners without access to
the server code, sharing outside the team, a tidy server repo). Prepare now: `adele.format_version`,
`adele.secrets` per dataset, `datasets_dirs` in the server config. Split after POC step 6, once
the descriptor format has held for a week: `git subtree split` per dataset, a template
repository, `adele-server sync` with pinned tags that only the admin moves.

POC 2: actual load (`append-only`, `as_of`, MW --> MWh at ingestion, a join with prices on the
server), `pull`, email alerts.

Swissgrid, when its datasets are written (decided 2026-11-15): the 5-minute TSI file
(`total-system-imbalance.csv`: one quarter-hour as three 5-minute values, replaced every 15
minutes) and the daily balance file (`control-area-balance-daily.csv`: one row per quarter-hour,
the last 24 hours) are two datasets, each with its own `fetch.py`, refresh and time limit. The
daily one guarantees that no quarter-hour of TSI is lost (a margin of 24 hours); the 5-minute
one adds the detail inside the quarter-hour and about 17 minutes of advance. The 5-minute
dataset is fetched every minute (`every: PT1M`, Renaud, 2026-11-15), with a short `timeout`.
Open: whether the year file (`control-area-balance-<year>.csv`, the same values revised) is a
third dataset or the same table as the daily file (that needs `append-only`).
Before adele: one poller script for all Swissgrid files, with a poll interval per file; in
swiss_energy_data the two files were entries without a table (`tables: []`), kept as raw
versions only.

Next, state at the end of 2026-11-15:

- A real fetch of both datasets with the code of D25 and D27 (Renaud: "very soon"). Until then
  the new window, the pieces of weathernext3 and the fixed runner path are tested on synthetic
  data only.
- The work packages are in `PLAN.md`, which Renaud edits himself. Claude's proposal for the
  order of the three server builds: WP3 (versions), then WP4 (the Swissgrid files, which need
  WP3), then WP2 (table shapes). `append-only` can be built during the week of unattended
  fetches on steacher1.

Next for Claude (decided 2026-11-14, not built):

- D20, warnings in the footer: a warning is a string or `{text, footer}`; `describe` shows all,
  the footer only `footer: true`. Server: catalog (accept both shapes), render (footer), the
  describe card, a test. The entsoe footer then shows no warning until Renaud marks one.
- D21, `adele.expected_spacing` in periods `{from, value}` like `resolution`: missing window
  values between the first `from` and the last stored value --> problems, status failing, count
  and ranges in `describe`. Declare it for weathernext3 (first period at 2026-11-12 for the
  sample; PT3H from 2024-01-01 and PT1H from 2026-01-01 after the steacher1 backfill). Open:
  how to accept a run that Google never publishes.
- D22, tables without a time column: catalog (accept a table with neither `delivery_start` nor
  `valid_at`; no window check for it), staging without the filter on the window, a merge that
  replaces the one file (an empty fetch is an error), row count and last change in `list` and
  `describe`, tests. The text for SPEC.md (Time conventions, Storage) comes with the one for
  the date column, once its details are settled (docs/datasets-inventory.md, section 6).

Found on 2026-11-14 by subagents (docs/datasets-inventory.md, sections 4 and 5), not fixed:

- ~~A hole older than the lookback is never fetched again~~ fixed 2026-11-15 (D25): the
  scheduled window starts at the last scheduled run that succeeded, `adele.refresh.max_window`
  for pieces, giving up after one lookback of failures. 233 tests pass. Left over: an unknown
  key under `adele.refresh` is not refused (a misspelt `max_window` is ignored); the cost of the
  14 pieces of a usual weathernext3 run is not measured; no real fetch was run with it.
- A backfill doesn't resume: `--start` is required (`cli.py`) and a second run fetches every
  window again. A window that fails in the middle leaves a hole; the command prints it and
  returns 1, but `state.json` ends with status ok. D21 (`expected_spacing`) would report the
  hole, once built and declared.
- `revisions: none`: a run that is stored in part counts as stored (`windows_to_fetch`) and is
  never completed. Tested by the subagent: 2 rows of 4 stayed after a second backfill.
- Date column (decided 2026-11-15, D26; the build comes after D22). To change: the `adele:` block per
  table (`resolution`, `window`, `partition` are per dataset in `catalog.py`, so a dataset with a
  table by quarter-hour and a table by month can't load); `Table.time_field` (falls back to
  `valid_at`); the window filter in `_stage` (a period is kept when it overlaps the window);
  `windows_to_fetch` (TypeError on a date); `ts()` in `render.py` (fails on a date, so `list`
  and `describe` fail); the hint when `fetch.py` returns timestamps for a date column
  (`pd.to_datetime` gives TIMESTAMP); `describe` prints the zone and the join expression.
- `skills/adele/SKILL.md:38` weights by `epoch(resolution)`: 720 hours for any month. Fix when
  the first table by month comes.
- ~~Queries could read the query log and write a file inside the folder of a table~~ fixed
  2026-11-14 (D24, `engine.py`). Since 2026-11-15 a query is one SELECT and nothing else: no
  EXPLAIN at all (D29, which supersedes D28). Also refused: the table functions `query`,
  `query_table` and `histogram`. Left over from that work:
  - a query over the row cap that ends with `;` or with a `--` comment fails (older defect: the
    server counts with `SELECT count(*) FROM (<query>)`).
  - `deploy/adele-server.service` sets no working directory, so DuckDB's `.tmp` would be `/.tmp`,
    which is read-only there: a query that needs temporary files would fail (not tried).
  - scalar functions are on no list (814; none found that writes).

Fetch scheduling (G5), investigated 2026-11-15 by a subagent. Decided and built the same day
(D27): one systemd timer and one service per dataset, `fetch <id> --if-due`, "due" in whole
periods of `every`, `adele.refresh.timeout`, a backfill that holds the lock. 317 tests pass. Not
done: nothing ran on steacher1, and no real fetch ran with this code. Files in
`deploy/scheduling-poc/`: draft units, a test script for a Linux server, the prototypes and
their numbers. The claims about systemd were tested once in a Docker container on the Mac
(systemd 255 under emulation, 27 checks passed: `deploy/scheduling-poc/container-test/`), not
on steacher1. One claim was wrong: `KillMode=mixed` does not wait for the children.

- Candidates: one timer and one service per dataset (`adele-fetch@<id>`, the subagent's
  recommendation and Claude's since then), a scheduler that stays running (best numbers, but a
  restart stops every fetch in progress and all datasets share one journal), a tick that starts
  one unit per due dataset (needs a polkit rule or one line that runs as root), two lanes.
- Measured on the Mac, 14 minutes per run, one run each: with the timer and the service of
  today, the dataset due every minute was fetched in 4 of 14 minutes (longest gap 360 s). With
  each candidate: 14 of 14, about 0.7 s after the tick, no double fetch.
- Defects found on the way, fixed 2026-11-15:
  - a `fetch.py` with a script block cost 8.7 s per fetch on the Mac, because its runner was
    written to a new temporary path each time and uv built a new environment. The runner now
    has one path per dataset (`<cache_dir>/runners/<id>/`): 0.3 s from the second fetch on.
  - SIGTERM to `adele-server fetch` left `fetch.py` running without a limit. Now the child is
    stopped, the attempt is recorded, and the exit code is 143 (130 for Ctrl-C).
  - one invalid descriptor made the fetch of every other dataset exit with 2.
- Still open:
  - `load_catalog` imports every `fetch.py` that has no script block (`catalog.py`,
    `_load_fetch`), also in the query process. Both datasets have a script block today.
- The subagent's remark on the requirement: a fetch of TSI covers the last 15 minutes, so what
  matters is "never 15 minutes without a success", not "every minute". A hang under the time
  limit of 1,800 s then loses data whatever the scheduler: the time limit per dataset matters
  more than the choice of the scheduler.

Other V0 items:

- ~~investigate what projects exist for agentic data layer~~ done 2026-11-13: docs/prior-art.md
  (energy) and docs/agentic-data-layers.md (general). PUDL's two agent skills read
  2026-11-13 (github.com/catalyst-cooperative/agent-skills).
- first dataset: ENTSO-E day-ahead prices, then actual load (why: docs/agentic-data-layers.md,
  Discussion). ENTSO-E API token: in `.env` since 2026-11-13. Check that `categories` exists in
  Data Package v2 (used in the sketch of SPEC.md, Keys or prose).
- ~~answer the open questions at the top of DECISIONS.md (repo layout, library API)~~ done
  2026-11-13: D5, D6, D8 (table names), D9 (no dlt).
- security: check by experiment that DuckDB can be locked down as SPEC.md "Security" says:
  read-only, access limited to the Parquet files of the catalog (`allowed_directories`,
  `enable_external_access=false`, `lock_configuration=true`), and a time limit per query
  (DuckDB has none built in). Try to break out with SQL (`read_csv('/etc/passwd')`, `ATTACH`,
  `INSTALL`, `SET`, `COPY ... TO`).
- status `stale`: define it in SPEC.md (Time conventions), with `adele.max_staleness` in the
  datapackage, and alert on any status change (Architecture still alerts on ok --> failing and
  back only).
- ~~time limit per fetch, set by the server~~ done 2026-11-13 (`fetch_timeout_s`, child
  process). Why: on 2026-11-13 a request without a timeout hung for
  28 minutes. While a fetch hangs it holds the dataset's lock, every cron run skips, and the
  status stays ok: the data goes stale silently. Run `fetch` in a subprocess with a time limit
  (a hung thread can't be stopped). `stale` would also make it visible.


## V1

- `describe`: distinct values of categorical columns (column profiles), and `adele search`
  to resolve names to codes (zones, production types). See docs/agentic-data-layers.md.
- QA: 20 to 40 questions with known answers, rerun when a descriptor or the skill changes.
-  pull and revisions. Does a local copy hold every revision or only the latest values?
   I recommend every revision, so that as_of also works locally.
- `as_of` before adele's first fetch of a dataset is meaningless: backfilled rows all carry the
  backfill date as `fetched_at`. Say so in SPEC.md, Revisions?
- copy by default: beyond a quick look, the skill tells the agent to `pull` and query locally
  (the data is a few GB). Then add it to SPEC.md, Agent access.

- skills `add-dataset` and `review-dataset` are drafts written before any code: run both on
  the first dataset (ENTSO-E day-ahead prices) and rewrite them from what happened.

## V2

- token gate on `query` (hash printed by `describe`), only if the QA questions show that agents
  skip `describe`.
