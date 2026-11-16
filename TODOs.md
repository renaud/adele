# TODOs

## Renaud, now

- SPEC.md: paste the three texts of WP2 (Catalog, Adding a dataset, Storage), in
  `docs/work-packages/WP2-table-shapes.md`, section "Text for `SPEC.md`".
- PLAN.md, row WP2 (proposal): "built and in `main` (D32): tables by calendar day, month or
  year in a zone (D26), tables without a time column (D22), an `adele:` block per table, format
  version 2. Next: the first such dataset in WP6. `docs/work-packages/WP2-table-shapes.md`"
- SPEC.md: paste the three texts of WP4 (Adding a dataset, Storage, Revisions), in
  `docs/work-packages/WP4-files-overwritten-or-revised.md`, section "Text for `SPEC.md`". Then
  confirm the three points of its section "To confirm before steacher1".
- PLAN.md, row WP4 (proposal): "built and in `main` (D33): raw answers (`adele.raw: keep`),
  `adele-server import`, `swissgrid_tsi`, `swissgrid_balance_daily`, `swissgrid_balance`; tried
  on the Mac. Next: Renaud confirms units, stamps, ids; step 6 (import and 7 days side by side
  on steacher1) after WP1. `docs/work-packages/WP4-files-overwritten-or-revised.md`"
- WP5.1 (in `main`, f7f9dbe): review the drafts of the five `datasets/entsoe_*` descriptors
  (WP7), the switch to `append-only` for the two neighbour datasets, the refresh proposals and
  finding 1 (ElCom's labels swapped for 2017-2021). "Left to do" of
  `docs/work-packages/WP5.1-entsoe.md`.
- PLAN.md, row WP5.1 (proposal): "built and in `main`: five ENTSO-E datasets (imbalance prices
  CH and neighbours, activated balancing prices, balancing state, neighbours' imbalance volume,
  installed capacity), 79 published figures as checks; backfilled on the Mac. Next: Renaud's
  review of the drafts; install on steacher1. `docs/work-packages/WP5.1-entsoe.md`"
- WP5.3 (in `main`, 2026-11-16): review the drafts of `entsoe_wind_solar_forecast` and
  `entsoe_wind_solar_forecast_neighbours` (WP7: titles, descriptions, labels, 13 warnings,
  examples). On steacher1, install WP5.2 (`entsoe_generation`) with WP5.3 or before it (D34).
- PLAN.md, row WP5.3 (proposal): "built and in `main`: ENTSO-E wind and solar forecasts (A69),
  CH and 16 neighbouring areas, `append-only`, 125 published figures as checks; backfilled on
  the Mac. `forecast_versions` not built. Next: Renaud's review of the drafts; backfill on
  steacher1. `docs/work-packages/WP5-datasets.md`"

## For other sessions: WP5.3 landed (2026-11-16)

- D34 is WP5.3; the next is D35.
- `ingest.py`: `redact(text, ds)` and `SECRET_MIN_LEN`; `_run_child` passes what `fetch.py`
  printed through `redact` before the error and the log. Secrets shorter than 8 characters are
  left as they are.
- A check can read another dataset (D34). `entsoe_wind_solar_forecast` has 14 checks that read
  `entsoe_generation.generation` (WP5.2): a change to its columns (`bidding_zone`,
  `production_type`, `delivery_start`, `generation`) or to its codes (`CH`, `solar`,
  `wind_onshore`) breaks them.

## For other sessions: WP4 landed after WP2 (2026-11-15)

A branch made before this landing may break on these points when it rebases:

- `ingest.py`: the runner (`_RUNNER_BODY`) has three modes (`fetch`, `download`, `parse`) and
  more arguments; `call_fetch` goes through `_call_runner` and takes `raw_dir`;
  `_fetch_merge` calls `_call_keeping_raw` instead of `call_fetch`. A change to the runner or to
  `call_fetch` will conflict: keep both.
- `_stage(con, t, files, windows)` and `storage.merge_versions(..., window=None, partition=None,
  fetched_at=..., resume=False)` take the window and partition of the table (D32), not of the
  dataset. Code that still passes `ds.window` or `ds.partition` runs, but is wrong for a dataset
  whose tables differ.
- `catalog.py`: `fetch.py` is checked for its shape. With `adele.raw: keep` it must define
  `download(start, end)` and `parse(answers)` and no `fetch`; without the key it must define
  `fetch(start, end)` (a helper named `parse` beside it is fine).
- A dataset's data folder may hold `_raw/` (raw answers, D33) next to its table folders and
  `state.json`. Code that lists `<data_dir>/<id>/*` as tables must skip names that start with
  `_`. `state.json` may hold `imported`.
- Decisions: D32 is WP2, D33 is WP4; the next is D34.

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
  fetches on steacher1. Revised proposal (Claude, 2026-11-15, not decided): WP2 before WP4.
  WP2 is decided (D22, D26) and frees 13 datasets (9 by D22 and D26 alone: the other 4 need a
  period with its own end, a state at a date, or are derived; `docs/work-packages/WP5-datasets.md`,
  open question 2); WP4 frees 8 and has three open questions
  (raw answers G4, whole files G6, who takes over from the poller), and the Swissgrid poller
  keeps every version meanwhile. During WP1's week: WP5 on the Mac (27 datasets that fit
  today, ENTSO-E first), installed on steacher1 after 2026-11-22.
- The ENTSO-E series that are revised (`qa/revisions_entsoe_ch.md`, measured 2026-11-15):
  generation per type (A75), physical flows (A11), scheduled exchanges (A09), imbalance volume
  (A86). Renaud agreed to build their datasets ("b: ok, for the series that a shows to be
  revised"). Claude's proposal, not decided: all four in WP6 as `append-only`, so flows and
  schedules leave WP5 (schedules change before delivery: 541 of 1,258 hours ahead changed;
  flows are corrected up to months later). Until Renaud decides, a session that does WP5
  leaves A11 and A09 out, so that they aren't built twice with two policies.
- WP5 split into datasets (Claude, 2026-11-15, at Renaud's request; a proposal, not decided):
  `docs/work-packages/WP5-datasets.md`. With WP1 to WP3 done: 44 datasets (26 with no build, 9
  need WP3, 9 need WP2), in 10 sub-packages WP5.1 to WP5.10 grouped by what their fetch shares,
  and 15 left out (8 for WP4). Six open questions for Renaud there (flows and schedules, WP2
  frees 9, neighbours' A86, `pv_plants` versions, one dataset or several, `forecast_versions`). `PLAN.md`
  still puts the 18 WP2/WP3 datasets in WP6: Renaud's edit. The Claude Doc "adele: WP5 by
  dataset" (https://claude.ai/artifact/Jg2jVRVd4AW9URE7iJtsBY) has the same list without the
  sub-packages; the file is the one to keep up to date.
- WP5.3, ENTSO-E wind and solar forecasts (A69), built 2026-11-15 in the worktree `wp5.3`, in
  `main` since 2026-11-16:
  `entsoe_wind_solar_forecast` (CH, 236,584 rows) and `entsoe_wind_solar_forecast_neighbours`
  (16 areas, 22.6 million rows), `append-only`, backfilled on the Mac; 11 and 100 published
  figures as checks (`qa/published_figures_entsoe_wind_solar_forecast*.md`), and 14 more for
  CH that read `entsoe_generation` (D34). Definitions are drafts by Claude (WP7). Renaud's
  answers of 2026-11-16:
  1. `forecast_versions` (WP5 open question 6): no dataset. Its collector saw one version of
     each hour; its 438 A69 values equal adele's except 3 (the older values of three revised
     night values of 2026-10-26/27); the rest is in `entsoe_load` and `entsoe_generation`.
     Written in `docs/work-packages/WP5-datasets.md` (open question 6).
  2. Checks that read another dataset: yes (D34). WP5.3 landed before WP5.2 (Renaud,
     2026-11-16): where the forecast data exists without `entsoe_generation`, the 14 checks fail
     and the CH forecast is `failing`. On steacher1, install WP5.2 with WP5.3 or before it.
  3. The server removes the declared secrets from what `fetch.py` prints (D34,
     `ingest.redact`). The token was printed once in Claude's session of 2026-11-15: rotate it
     if that matters.
  Next: the backfill on steacher1 after WP1 (the neighbours: 12 windows of about 5 min).
- What WP4 needs before a build (Claude, 2026-11-15, asked "what prevents us from doing WP4
  first"): nothing is missing in the server (WP3 is in `main`, G5 was built with D27), but no
  WP4 doc exists. Its design points: where raw answers are kept (G4: place, retention, one copy
  per sha256, size: the poller kept 1,797 versions of the daily file and 2,160 of the TSI file
  in three weeks); the year file (G6: a lookback over the whole file; its own dataset or the
  same table as the daily file, possible now with `append-only`); when adele takes over from
  the poller and how long both run. Also: the checks run after every fetch, changed rows or not
  (`server/src/adele_server/ingest.py`, `_settle`): 1,440 runs a day for a dataset fetched every
  minute. Measures on the poller's files use the copies in `swiss_energy_data` (WP1: nothing
  runs on steacher1 during the week). Production waits for WP1; the poller keeps every version
  meanwhile. Proposed way: a WP4 doc with these points, a critic, Renaud's answers, as for WP3.
- WP4 (2026-11-15): the doc `docs/work-packages/WP4-files-overwritten-or-revised.md`, Renaud's
  "all points 1-8 ok", built and in `main` (D33, 6d213e9): `adele.raw: keep` with
  `download`/`parse`, the archive `_raw/`, `adele-server import`, the datasets `swissgrid_tsi`,
  `swissgrid_balance_daily`, `swissgrid_balance`; tried on the Mac. Before steacher1, Renaud
  confirms the prices in EUR/MWh, the 5-minute stamps as starts, the three ids (the doc, "To
  confirm before steacher1"). Then step 6 of the doc after WP1: copy of the poller's archive,
  import, timers, 7 days side by side, a comparison script, the files out of the poller.
- `PLAN.md`, the table "Order and state": updated on 2026-11-15 by Claude at Renaud's request
  (WP1 steps 0-5 done, the week runs until 2026-11-22, step 6 waits for the port; WP3 in
  `main`, then 1-2 days of fetches on steacher1 once WP1 is done, V1 below).
- `main` holds code that steacher1 doesn't run since 72f2b1a (D31), and WP3 (D30) since its
  landing on 2026-11-15 (Renaud relaxed "after the week"). A WP1 fix now comes from a branch
  made at 32237db (`WP1-server-on-steacher1.md`).
- WP1 closed on 2026-11-16 after 17 hours of fetches, not a week (Renaud). What waited for
  "after WP1" or "after 2026-11-22" can start: WP3 on steacher1 (V1), WP4 step 6, WP5 on
  steacher1. WP1's steps 6 and 8 are in V1.
- WP5.1 (2026-11-16): five ENTSO-E datasets in `main` (f7f9dbe), backfilled on the Mac only (in
  the `data_nosync/` of the worktree `.claude/worktrees/wp5.1`). For steacher1, another agent
  (Renaud): install `entsoe_imbalance_prices`, `entsoe_activated_balancing_prices`,
  `entsoe_balancing_state`, `entsoe_imbalance_volume_neighbours`, `entsoe_installed_capacity`
  with their timers, backfill from 2014-12-31 (the first local hour of 2015), then
  `adele-server check` on the three with `checks.yaml`. Open question 3 of WP5-datasets.md is
  answered there: the neighbours' A86 and A85 are revised, so both are `append-only`
  (proposal). Renaud has no reports of his own for these series; copying the findings into
  WP5-datasets.md is not needed for now (Renaud).
- WP5.4 (2026-11-16, in `main`, 5833d88), found while building `energy_charts_intraday_prices`:
  ENTSO-E's CH day-ahead price in `entsoe_day_ahead_prices` is one hour late from 2017-04-27
  22:00 to 2017-10-29 01:00 UTC (4,140 hours) and on about ten days of summer 2015 (277 hours).
  There, Energy-Charts' CH price at t equals ENTSO-E's at t + 1 h; per month of 2017, ENTSO-E's CH
  follows the hourly changes of DE_AT_LU at a lag of one hour from May to October, Energy-Charts'
  CH at lag 0 (`docs/work-packages/WP5.4-prices-outside-entsoe.md`, Findings). The checks don't
  see it: they are means and counts. To do: Renaud decides between moving those stretches back
  one hour in `datasets/entsoe_day_ahead_prices/fetch.py` (with a warning) and keeping them as
  served (with a warning).
- WP5.4: the 34 checks of 2026 in `datasets/swissgrid_imbalance_prices/checks.yaml` (17 weeks)
  split the quarter-hours by the single price against the CH day-ahead price, a stand-in for
  ElCom's split by the state of the control area (TSI < 0 short, > 0 long). `swissgrid_balance`
  (WP4) carries the TSI: once it holds 2026 on the server, switch these checks to it and add the
  8 weeks left out (`qa/published_figures_swissgrid_imbalance_prices.md`, Differences).

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
  Built 2026-11-15 (WP2, D32), with the date column below. Time conventions in SPEC.md already
  has the text; the proposals for Catalog, Adding a dataset and Storage are in
  `docs/work-packages/WP2-table-shapes.md` (Renaud, now).

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
  Built 2026-11-15 with D22 (WP2), in `main`: the 18 choices made during the build, accepted by
  Renaud, are D32 (`docs/work-packages/WP2-table-shapes.md`). Not on steacher1, no real dataset
  uses it yet (WP6).
- ~~`skills/adele/SKILL.md:38` weights by `epoch(resolution)`: 720 hours for any month~~ done in
  `wp2`: a rule says that a table by calendar period has no resolution.
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

- From WP1 (closed 2026-11-16, `docs/work-packages/WP1-server-on-steacher1.md`):
  - HTTPS on another port (WP1 step 6, way b, Caddy's `tls internal`), once Renaud opens the
    port in Infomaniak's panel: `deploy/Caddyfile` with port 8443, `tls internal` and no
    listener on :80; `ADELE_CA_FILE` in `client/src/adele/_api.py`; a query from a laptop.
  - Faults on purpose (WP1 step 8), on the code of the next deployment, each on a copy under
    another id: a renamed column, a duplicated row, an undeclared zone code, a fetch over its
    memory limit (status failing each time); the timers stopped for two hours, then the hole
    fetched (D25).
  - Two checks that WP1's 17 hours could not make: the first new delivery day of entsoe
    fetched unattended (no auction fell in them), and `oom_score_adj` 1000 on `fetch.py`
    during a fetch.
- WP3 on steacher1, once WP1 is done (done 2026-11-16; WP3 lands in `main` on 2026-11-15:
  Renaud relaxed the rule "after the week" of the WP1 doc): pull the code onto steacher1
  (`/opt/adele`), install `datasets/entsoe_load` with its timer, backfill it from 2015, let it fetch for 1-2 days
  (Renaud: "we won't wait a week, just 1-2 days"), then check `describe` (`versions_since`, the
  count of versions), the 50 checks, and a query with `--as-of` before the last fetch. If
  ENTSO-E revised a value in those days, the old value must come back with that `--as-of`
  (`docs/work-packages/WP3-versions.md`, step 4).
- `describe`: distinct values of categorical columns (column profiles), and `adele search`
  to resolve names to codes (zones, production types). See docs/agentic-data-layers.md.
- QA: 20 to 40 questions with known answers, rerun when a descriptor or the skill changes.
-  pull and revisions. Does a local copy hold every revision or only the latest values?
   I recommend every revision, so that as_of also works locally.
- ~~`as_of` before adele's first fetch of a dataset is meaningless: backfilled rows all carry the
  backfill date as `fetched_at`. Say so in SPEC.md, Revisions?~~ done in WP3 (D30): an `as_of`
  before `versions_since` is refused; Renaud put the sentence into SPEC.md (proposed in
  `docs/work-packages/WP3-versions.md`).
- copy by default: beyond a quick look, the skill tells the agent to `pull` and query locally
  (the data is a few GB). Then add it to SPEC.md, Agent access.

- skills `add-dataset` and `review-dataset` are drafts written before any code: run both on
  the first dataset (ENTSO-E day-ahead prices) and rewrite them from what happened.

## V2

- token gate on `query` (hash printed by `describe`), only if the QA questions show that agents
  skip `describe`.
- `append-only`: rows that the source stops sending (deferred from WP3 by Renaud, 2026-11-15).
  Today they are kept, as with `overwrite` (D30), so `as_of` can't show a withdrawal, and a key
  that a corrected `fetch.py` no longer produces (A65: "stamped 1 h late before 2025") stays in
  the latest view. A fix: a deletion mark (a version with a `deleted` flag, or a null row as the
  earlier project did, `docs/from-swiss-energy-data.md`). Needed anyway for the tables without a
  time column (D22, WP2).
