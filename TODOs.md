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
  - Security, replaces the "read-only" bullet:
    ```
    - read-only: the server's DuckDB can read the Parquet files of the catalog and nothing else
      (no other local file, no network, no extension install, no change of settings by a query).
      DuckDB can't make an allowed folder read-only, so the server also runs only SELECT and
      EXPLAIN statements, and the query process runs as a user that can only read the data.
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

    Each scheduled run fetches [now - lookback, now + horizon), both set in `adele.refresh`.
    The lookback catches revisions and late data; the horizon covers data published before
    delivery (e.g. day-ahead prices). The initial backfill calls `fetch` on successive windows.
    ```
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
(Renaud checks), the few-days backfill on steacher1 (it also reads the 7 sample runs again, all
12 fields, to add their clouds).

Packaging: one repository per dataset (decided 2026-11-13; reasons: owners without access to
the server code, sharing outside the team, a tidy server repo). Prepare now: `adele.format_version`,
`adele.secrets` per dataset, `datasets_dirs` in the server config. Split after POC step 6, once
the descriptor format has held for a week: `git subtree split` per dataset, a template
repository, `adele-server sync` with pinned tags that only the admin moves.

POC 2: actual load (`append-only`, `as_of`, MW --> MWh at ingestion, a join with prices on the
server), `pull`, email alerts.

Next for Claude (decided 2026-11-14, not built):

- D20, warnings in the footer: a warning is a string or `{text, footer}`; `describe` shows all,
  the footer only `footer: true`. Server: catalog (accept both shapes), render (footer), the
  describe card, a test. The entsoe footer then shows no warning until Renaud marks one.
- D21, `adele.expected_spacing` in periods `{from, value}` like `resolution`: missing window
  values between the first `from` and the last stored value --> problems, status failing, count
  and ranges in `describe`. Declare it for weathernext3 (first period at 2026-11-12 for the
  sample; PT3H from 2024-01-01 and PT1H from 2026-01-01 after the steacher1 backfill). Open:
  how to accept a run that Google never publishes.

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
