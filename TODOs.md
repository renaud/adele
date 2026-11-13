# TODOs

## Renaud, now

- `datasets/entsoe_day_ahead_prices/datapackage.yaml`, the `TODO(Renaud)` items: description of
  the dataset, licenses, description of `resolution`, and the first warning (it says
  2025-10-01, but CH switched to 15 minutes on 2026-11-04 and FR on 2025-09-30). Labels: done.
- `qa/entsoe_day_ahead_prices.md`: accept or reject each of the 12 questions.
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
6. Linux server: one week of daily fetches, unattended. Then three faults on purpose (a renamed
   column, a duplicated row, an undeclared zone code); each must set status to failing.

Done when: the lockdown holds against the breakout list; agents answer most trap questions
correctly in most runs, and every failure has a known cause and a fix; a week of daily fetches
shows correct freshness; the three faults are caught.

POC 2: actual load (`append-only`, `as_of`, MW --> MWh at ingestion, a join with prices on the
server), `pull`, email alerts.

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
