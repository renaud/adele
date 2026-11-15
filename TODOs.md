# TODOs

## Renaud, now

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
  WP2 is decided (D22, D26) and frees 13 datasets; WP4 frees 8 and has three open questions
  (raw answers G4, whole files G6, who takes over from the poller), and the Swissgrid poller
  keeps every version meanwhile. During WP1's week: WP5 on the Mac (27 datasets that fit
  today, ENTSO-E first), installed on steacher1 after 2026-11-22.
- `PLAN.md`, the table "Order and state" is out of date (Renaud edits it): WP1 steps 0-5
  done, the week runs until 2026-11-22, step 6 waits for the port; WP3 built on the branch
  `wp3` (D30), lands after WP1's week, then 1-2 days of fetches on steacher1.
- `main` holds code that steacher1 doesn't run since 72f2b1a (D31). A WP1 fix now comes from
  a branch made at 32237db (`WP1-server-on-steacher1.md`). `wp3` will conflict with `main` in
  `DECISIONS.md` (D30 and D31 both at the end): keep both, D30 first.

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

- WP3 on steacher1, once WP1 is done (WP3 lands in `main` on 2026-11-15: Renaud relaxed the
  rule "after the week" of the WP1 doc): pull the code onto steacher1 (`/opt/adele`), install
  `datasets/entsoe_load` with its timer, backfill it from 2015, let it fetch for 1-2 days
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
