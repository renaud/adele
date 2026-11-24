# TODOs

## Renaud, now

- SPEC.md: paste the three texts of WP2 (Catalog, Adding a dataset, Storage), in
  `docs/work-packages/WP2-table-shapes.md`, section "Text for `SPEC.md`".
- PLAN.md, row WP1 (proposal): "done 2026-11-16: adele runs on the server, entsoe and
  weathernext3 backfilled (figures equal to the Mac's), then 17 hours of unattended fetches:
  every status ok, no hole. HTTPS (step 6) and the faults on purpose (step 8) moved to
  `TODOs.md`, V1. `docs/work-packages/WP1-server.md`"
- PLAN.md, row WP2 (proposal): "built and in `main` (D32): tables by calendar day, month or
  year in a zone (D26), tables without a time column (D22), an `adele:` block per table, format
  version 2. Next: the first such dataset in WP6. `docs/work-packages/WP2-table-shapes.md`"
- SPEC.md: paste the three texts of WP4 (Adding a dataset, Storage, Revisions), in
  `docs/work-packages/WP4-files-overwritten-or-revised.md`, section "Text for `SPEC.md`". (The
  three points of "To confirm before the server": confirmed 2026-11-17, imports started the same day.)
- PLAN.md, row WP4 (proposal): "built and in `main` (D33): raw answers (`adele.raw: keep`),
  `adele-server import`, `swissgrid_tsi`, `swissgrid_balance_daily`, `swissgrid_balance`; tried
  on the Mac. Next: Renaud confirms units, stamps, ids; step 6 (import and 7 days side by side
  on the server) after WP1. `docs/work-packages/WP4-files-overwritten-or-revised.md`"
- WP5.1 (in `main`, f7f9dbe): review the drafts of the five `datasets/entsoe_*` descriptors
  (WP7), the switch to `append-only` for the two neighbour datasets, the refresh proposals and
  finding 1 (ElCom's labels swapped for 2017-2021). "Left to do" of
  `docs/work-packages/WP5.1-entsoe.md`.
- PLAN.md, row WP5.1 (proposal): "built and in `main`: five ENTSO-E datasets (imbalance prices
  CH and neighbours, activated balancing prices, balancing state, neighbours' imbalance volume,
  installed capacity), 79 published figures as checks; backfilled on the Mac. Next: Renaud's
  review of the drafts; install on the server. `docs/work-packages/WP5.1-entsoe.md`"
- WP5.3 (in `main`, 2026-11-16): review the drafts of `entsoe_wind_solar_forecast` and
  `entsoe_wind_solar_forecast_neighbours` (WP7: titles, descriptions, labels, 13 warnings,
  examples). On the server, install WP5.2 (`entsoe_generation`) with WP5.3 or before it (D34).
- PLAN.md, row WP5.3 (proposal): "built and in `main`: ENTSO-E wind and solar forecasts (A69),
  CH and 16 neighbouring areas, `append-only`, 125 published figures as checks; backfilled on
  the Mac. `forecast_versions` not built. Next: Renaud's review of the drafts; backfill on
  the server. `docs/work-packages/WP5-datasets.md`"
- WP5.5 (in `main`, 53fc780): review the drafts of `pronovo_production` (WP7: titles,
  descriptions, labels, 9 warnings, 3 examples without `verified_at`) and the choices 1, 3, 4
  and 7 of `docs/work-packages/WP5.5-pronovo.md`; send any report of yours with figures from
  Pronovo (they become checks).
- PLAN.md, row WP5.5 (proposal): "built and in `main`: `pronovo_production` (production per
  technology and PV per canton at 15 minutes, capacity per month), `append-only`, 168 published
  figures as checks (156 of them BFE's reference market prices, computed from the same files);
  backfilled on the Mac. Next: Renaud's review of the drafts; backfill on the server.
  `docs/work-packages/WP5.5-pronovo.md`"
- WP5.7 (in `main`, 00ca540): review the drafts of the six `datasets/meteoswiss_*` descriptors
  (WP7: titles, descriptions, warnings, examples), the zone of `meteoswiss_obs_daily`'s days
  (Europe/Zurich, assumed), and whether 2,120 checks are too many (the generator can keep a
  subset). The 9 choices and what is open: `docs/work-packages/WP5.7-meteoswiss-stations.md`.
  Backfill on the server: the commands are in that file (the 10-minute decade files took 30
  minutes at 3.3 MB/s on the Mac: `fetch_timeout_s` 7,200 there).
- PLAN.md, row WP5.7 (proposal): "built and in `main`: six MeteoSwiss station datasets
  (SwissMetNet hourly, 10 minutes, daily and its reference lists; manual network; visual
  observations), 2,120 published figures from the climate bulletins as checks; backfilled on the
  Mac. Next: Renaud's review of the drafts; backfill on the server.
  `docs/work-packages/WP5.7-meteoswiss-stations.md`"
- `skills/review-dataset` (proposal by Claude, 2026-11-16): for a dataset with reference lists,
  check that every station and parameter code of the data is in them, and the inventory dates
  against the first and last values. In WP5.7 this found a station in no list (MLJ) and confirmed
  the time shift (`qa/tools/crosscheck_meteoswiss.py`).
- Landing (Claude, 2026-11-16, measured from the session transcripts): a landing takes 10-17
  minutes, and the three runs of the full suite in `land` (before the rebase, after it, in
  `main`) take about 15 of them. A landing costs $1-5 at list price, 5-15 % of a WP ($20-37);
  $3-4 of it when the session was idle more than an hour (the cache lasts 1 h, so 480k tokens of
  context are written again). To decide (proposals, no file changed): (1) `land` tests only
  after the rebase; step 1 only when that fails; step 6 checks that `main` is the tested commit;
  (2) land at once when a WP is done, or from a fresh session, or with a `land.sh` that calls
  Claude only on a conflict or a failure; (3) a faster suite (V0 below); (4) `merge=union` in
  `.gitattributes` for `TODOs.md` and `skills/common-traps.md`, decisions numbered at landing;
  (5) 3-4 WPs open at once instead of 10.
- Students' visit on 2026-11-25 (Claude, 2026-11-23): pick a conversation in
  `docs/showcase-conversations.md`. The cleaned page with the excerpts is not made.
- SPEC.md:164 (proposal by Claude, 2026-11-23): "ENTSO-E corrects actual load days later" is not
  what WP3 measured (CH, 0 of 103,714 hours changed between 2026-10-31 and 2026-11-15). Text:
  "Sources revise past values (e.g. ENTSO-E corrects the physical flows on the Swiss borders up
  to a year after delivery)." Source: `qa/revisions_entsoe_ch.md`.
- Rotate the ENTSO-E token (Claude, 2026-11-23): printed again in a local session.
- The skill `adele` is installed on the Mac (Claude, 2026-11-23: `~/.claude/skills/adele` is a
  symlink to `skills/adele` of the main checkout). Left to do: `export ADELE_URL` and
  `ADELE_API_KEY` in `~/.bash_profile` (in neither profile file; `adele list` fails without them).

## The server: what may still be open (Claude, 2026-11-23; tick what is done)

- `iem_metar` (Claude, 2026-11-24): on the server since 2026-11-23 (12 windows, 0 failed), first
  scheduled fetch ok on 2026-11-24 at 00:00 UTC, slot 02:15 UTC set that morning. Open:
  - [ ] The first fetch in its slot, on 2026-11-25 at 02:15 UTC: not seen yet.
  - [ ] Renaud: review the drafts in `datapackage.yaml` (the 6 warnings and the labels of
    `cloud_report` first), confirm the 2 unverified examples.
  - [ ] Later: an hourly refresh (`adele.refresh.every: PT1H`) for a live signal; its line then
    goes out of `SLOTS` in `deploy/spread-fetches.sh`.

Read on the server on 2026-11-23, 09:00 UTC: it runs 89ebc25, 32 of 32 timers on, the lanes
entsoe, files, swissgrid and ens done, 30 statuses ok (failing: `meteoswiss_smn_tenmin`,
`openmeteo_previous_runs`), 18 GB free, no freeze since the memory guard of 2026-11-18. Items
described elsewhere are named, not repeated.

Running:

- [ ] The Open-Meteo backfill, until about 2026-12-17 to 12-22 ("The update of the server", below).
- [ ] `backfill.sh report`, then compare the rows, first and last times with the Mac's (output of 2026-11-23
  20:48 UTC in `deploy/backfill-report.txt`, made while the lane metar ran; not compared yet).
  Count the rows per run too (`ecmwf_ifs_ens` 133,036, weathernext3 139,776): the freeze and the
  kills below may have left a run in part, and a run stored in part counts as stored
  (`revisions: none`, below).

Found on 2026-11-23:

- [ ] CPU alerts of the machine's monitoring (> 85 % for 5 minutes). Every day since 2026-11-19 the
  first 10 minutes after 00:00 UTC are about 57 % busy on average (`sar`), no other 10 minutes
  above 50 %. 30 of the 32 datasets are due at 00:00 UTC (all but weathernext3 and
  `openmeteo_stations`, which is due on Mondays): 1,125 CPU s on 2026-11-23, almost all in 6
  minutes (4 cores: 1,440 s), the most from `meteoswiss_smn_daily` (222) and `_hourly` (195). Fix deployed on 2026-11-23 at
  10:18 UTC (`deploy/spread-fetches.sh`): the 13 daily datasets have slots from 00:08 to 02:08 UTC
  (timer drop-ins; Renaud: over 2 hours), all fetches together at most 2.5 of 4 cores. Not in it:
  the 17 others due at 00:00, of which 7 run every 3 or 6 hours. `next_fetch_eta` in `describe`
  still says 00:00.
- [ ] Check how `spread-fetches.sh` worked, from 2026-11-24 02:30 UTC on, and again after a few
  nights (Renaud, 2026-11-23). Before --> what to look for:
  - CPU: 00:00-00:10 UTC 57 % busy every day from 2026-11-19 to 11-23 --> every 10 minutes
    of 00:00-02:20 below 40 % (`sar -u -f /var/log/sysstat/sa24`); no new alert (Renaud's mail).
  - Kills: 21 at 2026-11-23 10:19 (`oom_kill` in `memory.events` of the slice; a reboot resets
    it) --> still 21, or which datasets (`journalctl -k --grep "Killed process"`, a narrow window).
  - Each daily dataset fetched once, in its slot: one line per day in its journal, between 00:08
    and about 02:15. `meteoswiss_smn_tenmin` (failing since 2026-11-23 00:02) is ok after 01:38.
  - The CPU limit does no harm: `throttled_usec` in `cpu.stat` of the slice (2.6 s at 10:19, a
    minute after it was set); no `swissgrid_tsi` fetch over its 50 s; weathernext3 ok at minute 30.
  - Then decide: the 7 datasets that run every 3 or 6 hours on minutes of their own, or not.
- [ ] The memory cap kills: 21 processes from 2026-11-18 18:16 to 2026-11-23 09:00 (`oom_kill` of the
  slice). Failed fetches with exit code 137: `entsoe_imbalance_prices`, `entsoe_physical_flows`,
  `meteoswiss_smn_tenmin` (2026-11-23 00:02) and weathernext3 (2026-11-21 18:30, 19:30). At
  2026-11-23 00:02 the kernel also killed an `adele-server` process itself (`ecmwf_ifs_ens`,
  2.3 GB): nothing then records the failure. To do: what takes 2.3 GB in that process, the kills
  per dataset, and whether a kill during a write can leave a run in part. Spreading the daily
  datasets (above) also helps here. Not measured: the peak of weathernext3 at minute 30.
- [ ] A failed fetch waits for the next period of `every`, not for the next tick (`state.is_due`
  counts attempts): `meteoswiss_smn_tenmin`, killed at 00:02, stays failing until 00:00 the next
  day. Renaud decides: an earlier retry for long periods, or leave it.
- [ ] `entsoe_physical_flows`: 9 failed runs from 2026-11-19 to 2026-11-22, 3 of 3 read were `fetch.py`
  errors on an A11 request (`fetch.py:117`), not kills. It is ok now. Read the whole error.
- [ ] `entsoe_load` and `entsoe_scheduled_exchanges` failed at 2026-11-23 10:00 UTC (`entsoe_load`: an
  HTTP error of ENTSO-E; 18 minutes before `spread-fetches.sh`). Are they ok again? If it repeats
  at minute 0: the ENTSO-E datasets all start together there, with one token.
  It repeated at 12:00 (read at 12:33; 24 minutes before the deployment of WP9 at 12:24): HTTP 599 from
  ENTSO-E for `entsoe_day_ahead_prices`, `entsoe_load`, `entsoe_physical_flows` and
  `entsoe_scheduled_exchanges`. Again at 13:00 for `entsoe_scheduled_exchanges` (599, read at 13:17). At
  14:00 it, the prices and the load were ok. `entsoe_physical_flows` (every
  PT3H) was still failing at 14:13: its next run is at 15:00.
- [ ] HTTP 599 of ENTSO-E (Renaud, 2026-11-23): an outage, or too many requests at minute 0 with one
  token? To decide: the minutes and the number of the 599 over some days (journal of the 13 ENTSO-E
  units, narrow windows). If they come at minute 0 only: spread the ENTSO-E fetches over the hour,
  as `deploy/spread-fetches.sh` does for the daily datasets. A fetch that fails is tried again at the
  next run and no hole stays (SPEC.md, Adding a dataset).
- [ ] `openmeteo_previous_runs` is ok after its fetch at 00:00 UTC and failing later in the day.
  Probably the window backfill, whose refused window (budget spent) counts as a failed fetch. Not
  verified.
- [x] `list` had no memory limit: 2.6 GB and 21.9 s for the first one on the server (2026-11-23, cap 3 GB),
  and at 13:06 UTC two at once had the query server killed, four times in 75 s. Deployed at 13:39
  (D37): 211 MB and 32.7 s for the first `list` after a restart, then 0.05 s.
- [x] The resolution periods filled the footer of every query and the card (603,268 and 1,482,518
  characters for `entsoe_activated_balancing_prices`). Deployed on 2026-11-23 at 14:10 UTC (D38):
  on the server, a whole answer with its footer has 1,383 bytes, the card 5,910.
- [ ] Reading the journal costs a whole core for minutes (the audit messages fill it). Agents: a
  narrow `--since`/`--until`, `timeout 40` before `journalctl` (a stopped `sc-run` leaves the
  process running on the server), and `sar` for the CPU.

Checks, now possible:

- [ ] WP3: `describe entsoe_load`, a query with `--as-of` (V1, "WP3 on the server"). Its timer has
  been on since 2026-11-18 18:53 UTC.
- [ ] WP4: 7 days side by side with the poller, until 2026-11-25 18:22 UTC (`swissgrid_balance_daily`
  since 2026-11-18 18:22; `swissgrid_tsi` since 2026-11-17 16:57, with the freeze of 17:00 to
  17:32). Then the comparison script (to write), then Renaud takes the three files out of the
  poller's `SOURCES` (the WP4 doc, step 6).
- [ ] WP5.4: the 34 checks of 2026 on the TSI of `swissgrid_balance` (below; backfilled 2026-11-18).
- [ ] WP1 leftovers: the faults on purpose (V1, "From WP1"). HTTPS: done 2026-11-23 (D35).
- [ ] WP9: first key for a user outside the team (`deploy/add-key.sh`). Deployed
  on 2026-11-23 at 13:39 UTC: D36 (`/health` without a key says only that adele is up, no
  `/openapi.json`), and a key for the user `claude` of the server, so that agents read the statuses.
- [ ] WP5.6, WP5.8, WP5.9: uncommitted in their worktrees. Replace the host name (it is also in their
  copies of `TODOs.md` and `WP5-datasets.md`), land, then one lane each.

Small:

- [ ] `deploy/backfill.sh`, `check_phase_a`: it says "run deploy/update-main.sh first" when only the
  unit needs `install` and `daemon-reload`. And the hint after `start` (below).
- [ ] The git history holds the host name, the address and the name of a key (`SERVER.md`). A rewrite
  is not decided.
- [x] The commits since 89ebc25: pushed, and 6881d54 runs on the server (2026-11-23, 12:24 UTC).
- [ ] The PLAN.md rows proposed above still say "Next: ... on the server": the backfills are done
  (2026-11-18).

Open elsewhere in this file: the SPEC.md texts, PLAN.md rows and draft reviews ("Renaud, now"),
`entsoe_day_ahead_prices` one hour late in 2017 and 2015 (WP5.4), `checks.yaml` of
`entsoe_imbalance_volume`, the ENTSO-E token printed once (WP5.3, point 3), the landing and
`review-dataset` proposals.

## For other sessions: the server has no name in git (2026-11-17)

- The repository is public. Renaud: everything about the machine goes into `SERVER.md` at the
  root of the main checkout (not in git: read it there): its address, accounts, paths outside
  adele, the other services. Tracked files say "the server", never its host name.
  The WP1 doc is now `docs/work-packages/WP1-server.md`, and the systemd test's result is
  `deploy/scheduling-poc/result-server.txt`. Before landing,
  replace the host name in your new text: wp5.6 (`datasets/bfe_pv_forecast/fetch.py`, its WP
  doc), wp5.8 (2 lines, its WP doc), wp5.9 (1 line, `datasets/dwd_gwl_hess_brezowsky/fetch.py`,
  its WP doc).

## For other sessions: landing wp5.10 (2026-11-16)

- `wp5.10` branched from 6d213e9 (WP4), before every WP5 landing: on 2026-11-16 it was 14
  commits behind `main`, with 15 uncommitted files, `TODOs.md` among them. Read the three
  "For other sessions" sections below before its rebase.

## For other sessions: an empty table by day or month no longer fails the fetch (2026-11-16)

- `ingest._window_filter` casts a date column to DATE before it adds the interval. Before, a
  fetch that returned no row for a table by day or month failed: pandas gives an empty column
  of dates as objects, DuckDB reads it as type NULL, and `NULL + INTERVAL 1 MONTH` has no
  single meaning (found by WP5.5 on the backfill of 2020-2022). A `fetch.py` that works around
  it (an Arrow date type, a dummy row) can drop the workaround. Test:
  `test_an_answer_without_periods_stores_nothing_and_succeeds` in `server/tests/test_table_shapes.py`.

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
6. Linux server (decided 2026-11-13): one week of daily fetches, unattended. Then
   three faults on purpose (a renamed column, a duplicated row, an undeclared zone code); each
   must set status to failing. Access: HTTPS through Caddy (decided 2026-11-13,
   `deploy/README.md`); ask IT before opening ports 80 and 443.

Done when: the lockdown holds against the breakout list; the published figures match after
every fetch; agents answer the regression questions correctly; a week of daily fetches shows
correct freshness; the three faults are caught.

WeatherNext 3, the next dataset (2026-11-13: CH only, all 24 runs per day, a sample of a few
days now, more on the server): notes in `docs/weathernext3.md`. Decided 2026-11-13: window on
init_time (D14), defaults of the sample plus runs of 2024-2025, `revisions: none` (fetch
only runs not stored yet), partitions by day, a `checkpoint` column, ssrd and cloud cover
(total, low) for now, clouds in their own table with `valid_at`; no temperature or wind yet.
History of the clouds later. Done 2026-11-13: the sample (9 solar runs, clouds of 2 runs),
definitions accepted 2026-11-14. Open: whether the pass-1 pull of 2026-10-28 ran on the server
(Renaud checks). Done 2026-11-15: the backfill on the server (the 2024-2025 runs, every run from
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

- ~~A real fetch of both datasets with the code of D25 and D27~~ done on the server (WP1,
  2026-11-15): the first scheduled weathernext3 fetch caught up `[00:24, 17:11)` in 17 pieces,
  then 17 hours of hourly fetches without a hole.
- The work packages are in `PLAN.md`, which Renaud edits himself. Claude's proposal for the
  order of the three server builds: WP3 (versions), then WP4 (the Swissgrid files, which need
  WP3), then WP2 (table shapes). `append-only` can be built during the week of unattended
  fetches on the server. Revised proposal (Claude, 2026-11-15, not decided): WP2 before WP4.
  WP2 is decided (D22, D26) and frees 13 datasets (9 by D22 and D26 alone: the other 4 need a
  period with its own end, a state at a date, or are derived; `docs/work-packages/WP5-datasets.md`,
  open question 2); WP4 frees 8 and has three open questions
  (raw answers G4, whole files G6, who takes over from the poller), and the Swissgrid poller
  keeps every version meanwhile. During WP1's week: WP5 on the Mac (27 datasets that fit
  today, ENTSO-E first), installed on the server after 2026-11-22.
- The ENTSO-E series that are revised (`qa/revisions_entsoe_ch.md`, measured 2026-11-15):
  generation per type (A75), physical flows (A11), scheduled exchanges (A09), imbalance volume
  (A86). Renaud agreed to build their datasets ("b: ok, for the series that a shows to be
  revised"), and chose `append-only` for flows and schedules too (2026-11-15). Built the same
  day in the worktree `wp5.2` (WP5.2), on the Mac: `entsoe_generation`, `entsoe_physical_flows`,
  `entsoe_scheduled_exchanges`, `entsoe_imbalance_volume`, backfilled from 2015, 68 published
  figures as checks (none found for the imbalance). The 12 choices of the build and what is
  open: `docs/work-packages/WP5.2-entsoe-revised-series.md`. On the server after WP1. Found on the
  way, for WP4's `swissgrid_balance` (no checks yet): ElCom's yearly counts of quarter-hours per
  bin of 100 MW beyond +-500 MW of Swissgrid's control area balance, 2017-2025, and Swissgrid's
  monthly counts of 2024-2026 (`qa/published_figures_wp52_sources.md`, section 4).
- WP5.10 built (Claude, 2026-11-16, worktree `wp5.10`): six datasets of weather forecasts at the
  79 stations of the swissgrid project (`docs/work-packages/WP5.10-weather-forecasts.md`). For
  Renaud: the definitions (drafts), checks for the forecasts (options given on 2026-11-16), and
  the swissgrid project's Open-Meteo backfill, stuck since 2026-11-06 (`fetch_openmeteo.py:179`).
  The backfill on the server (all rows, about 220,000 Open-Meteo calls, about 30 days, and ENS
  about 140 GB read) is one root script, `deploy/wp5.10-backfill.sh`, after land and push. The
  openmeteo_* fetches keep their call budget themselves, in a file shared on the machine.
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
  2. Checks that read another dataset: yes (D34). WP5.2 is in `main` since 2026-11-16
     (5e46433): the 25 CH checks pass with `main`'s descriptors on the two backfills (Claude,
     and the WP5.2 session at its landing). A catalog without `entsoe_generation` still fails
     the 14: on the server, install WP5.2 with WP5.3 or before it.
  3. The server removes the declared secrets from what `fetch.py` prints (D34,
     `ingest.redact`). The token was printed once in Claude's session of 2026-11-15: rotate it
     if that matters.
  ~~Next: the backfill on the server~~ done 2026-11-17 and 2026-11-18.
- `entsoe_imbalance_volume`: write its `checks.yaml` (Renaud, 2026-11-16). Two searches found
  no published figure computed from A86 for CH (`qa/published_figures_entsoe_imbalance_volume.md`:
  ElCom and DNV use Swissgrid's data, ENTSO-E and Compass Lexecon draw CH only in charts). Ways:
  (a) Renaud's or the team's documents with figures computed from A86; (b) since
  `swissgrid_balance` is in `main` (WP4) and a check can read another dataset (D34), a check
  that joins the two datasets: A86 equals TSI minus the IGCC netting from 2025-02-14 (in the
  swissgrid project 96 to 99 % of the quarter-hours of each month agreed within 1 MW), e.g. the
  share of quarter-hours within 1 MW per month. It would test the sign, the stamps and the unit
  at once.
- `server/tests/test_window_and_runner.py::test_script_fetch_is_stopped_at_the_time_limit`
  failed once in the full suite (WP5.2's landing, 2026-11-16, load average 49.7 from other
  sessions' backfills) and passed alone and in the next full run: a timing test that fails under
  load. Rerun it alone before looking for a bug.
- The full suite grew from 147 tests in under a minute to 486 tests in 5 minutes (2026-11-16);
  474 tests took 173 s alone and 325 s while other worktrees ran theirs. Not profiled yet: run
  `uv run pytest --durations=20` when no landing runs. Suspects: the `time.sleep(60)` and
  `time.sleep(120)` of fake fetch scripts (`server/tests/conftest.py:49`,
  `test_fetch_command.py:34`, `test_raw.py:61`, `test_window_and_runner.py:65`) if a test waits
  for a real timeout. Then `pytest-xdist` (tests that share a folder and the timing test above
  may fail in parallel).
- What WP4 needs before a build (Claude, 2026-11-15, asked "what prevents us from doing WP4
  first"): nothing is missing in the server (WP3 is in `main`, G5 was built with D27), but no
  WP4 doc exists. Its design points: where raw answers are kept (G4: place, retention, one copy
  per sha256, size: the poller kept 1,797 versions of the daily file and 2,160 of the TSI file
  in three weeks); the year file (G6: a lookback over the whole file; its own dataset or the
  same table as the daily file, possible now with `append-only`); when adele takes over from
  the poller and how long both run. Also: the checks run after every fetch, changed rows or not
  (`server/src/adele_server/ingest.py`, `_settle`): 1,440 runs a day for a dataset fetched every
  minute. Measures on the poller's files use the copies in `swiss_energy_data` (WP1: nothing
  runs on the server during the week). Production waits for WP1; the poller keeps every version
  meanwhile. Proposed way: a WP4 doc with these points, a critic, Renaud's answers, as for WP3.
- WP4 (2026-11-15): the doc `docs/work-packages/WP4-files-overwritten-or-revised.md`, Renaud's
  "all points 1-8 ok", built and in `main` (D33, 6d213e9): `adele.raw: keep` with
  `download`/`parse`, the archive `_raw/`, `adele-server import`, the datasets `swissgrid_tsi`,
  `swissgrid_balance_daily`, `swissgrid_balance`; tried on the Mac. Before the server, Renaud
  confirms the prices in EUR/MWh, the 5-minute stamps as starts, the three ids (the doc, "To
  confirm before the server"). Then step 6 of the doc after WP1: copy of the poller's archive,
  import, timers, 7 days side by side, a comparison script, the files out of the poller.
- `PLAN.md`, the table "Order and state" (out of date since 2026-11-16: the rows proposed under
  "Renaud, now" replace it): updated on 2026-11-15 by Claude at Renaud's request
  (WP1 steps 0-5 done, the week runs until 2026-11-22, step 6 waits for the port; WP3 in
  `main`, then 1-2 days of fetches on the server once WP1 is done, V1 below).
- ~~`main` holds code that the server doesn't run since 72f2b1a~~ the server runs `main` since
  2026-11-17 (89ebc25 on 2026-11-23).
- WP1 closed on 2026-11-16 after 17 hours of fetches, not a week (Renaud). What waited for
  "after WP1" or "after 2026-11-22" can start: WP3 on the server (V1), WP4 step 6, WP5 on
  the server. WP1's steps 6 and 8 are in V1.
- The update of the server to `main` (Claude, 2026-11-17, at Renaud's request: "let's move
  forward even if that breaks a few things"): ran on 2026-11-17 (below). Phase A,
  `deploy/update-main.sh` (code, units, secrets, the two running timers); phase B,
  `deploy/backfill.sh` (lanes entsoe, files, ens, openmeteo, then swissgrid once Renaud has
  confirmed WP4's three points and named the poller's folder; each timer after its backfill).
  It brings the 30 datasets in `main`; WP5.6, WP5.8 and WP5.9 come later, each as one more lane.
  Replaces the steps on the server of the WP3, WP4 (step 6), WP5.1 to WP5.7 and WP5.10 docs, and
  `deploy/wp5.10-backfill.sh`. After it: `describe entsoe_load` after 1-2 days (V1), WP4's 7 days
  side by side, the WP1 leftovers (V1), the CPU of about 32 ticks a minute and the memory at the
  top of the hour.
  Ran on 2026-11-17: phase A at 16:45 UTC (f934845, 32 descriptors valid), phase B at 16:46 with
  four lanes, then the Swissgrid lane at 16:52 (`swissgrid_tsi`: 5,556 answers imported). At
  17:00:38 the server froze (the other site on it too) and was rebooted at 17:32: five lanes beside
  the hourly fetches, most likely out of memory without swap (no message of the OOM killer; the
  details are in `SERVER.md`, Incidents). The cap of 4.5 GiB per fetch unit limits each fetch,
  not their sum. On before 17:00: 14 timers (the two old ones, 12 new ones,
  5 of them Open-Meteo's, whose backfill had only started). Stopped midway: `entsoe_wind_solar_forecast_neighbours`,
  the third window of `meteoswiss_smn_hourly`, `ecmwf_ifs_ens`, the Open-Meteo windows, the
  `swissgrid_balance_daily` import. Fix (2026-11-18): `deploy/memory-guard.sh` (swap, a cap on
  all adele fetches together, weathernext3 at minute 30), then the lanes one at a time
  (`backfill.sh chain`), beside at most `openmeteo`.
  Status 2026-11-20 13:40 UTC: lanes entsoe, files, swissgrid and ens done, 32 of 32 timers on,
  no freeze since the memory guard. ens failed first (2026-11-19 06:14: 33 of 962 runs,
  2024-10-11 to 2024-11-12, connect timeouts to dynamical.org's S3 from 22:01 to 00:13 UTC, no
  error in the other fetch units then); `backfill.sh start ens` again on 2026-11-20 skipped the
  stored runs (about 6 s each, `revisions: none`), fetched the 33 and the days since, ok at
  12:07 (`deploy/backfill-ens.txt`). Open-Meteo still runs: 26 of 80 windows of its first step
  (`openmeteo_previous_runs` from 2024-01-18), 11 windows a day in about 1 h each evening
  (18:20-19:30 UTC) when the 24 h budget frees; at the plan's 220,000 calls, the end comes
  between 2026-12-17 and 12-22 (the call ledger is not readable by Claude, so the calls per
  window are the plan's estimate). Next: follow it (`journalctl -u adele-fetch@openmeteo-backfill`).
- `deploy/backfill.sh:233`: the hint after `start` always says
  `journalctl -u adele-backfill-entsoe -f`, whatever lane started (seen with ens on 2026-11-20).
  Name the lanes started instead.
- WP5.1: ~~install and backfill on the server~~ done 2026-11-18, the five timers on, every status
  ok on 2026-11-23. As written on 2026-11-16: five ENTSO-E datasets in `main` (f7f9dbe),
  backfilled on the Mac only (in
  the `data_nosync/` of the worktree `.claude/worktrees/wp5.1`). For the server, another agent
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
  sample; PT3H from 2024-01-01 and PT1H from 2026-01-01 after the backfill on the server). Open:
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
  Met again on the server (2026-11-19): `ecmwf_ifs_ens` with 33 runs missing, `/health` ok.
  For a `revisions: none` dataset, a second backfill skips the stored runs (`windows_to_fetch`),
  so it fills the holes cheaply; the sentence above holds for `overwrite` and `append-only`.
  Met in WP5.2 (2026-11-15): one window of the schedules failed, status ok. To fetch it again,
  take its bounds from the log: windows of 365 days from the start drift by one day per leap
  year (from 2015-01-01 the 12th window starts on 2024-12-29, not 2024-12-30).
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
  Renaud, are D32 (`docs/work-packages/WP2-table-shapes.md`). Not on the server, no real dataset
  uses it yet (WP6).
- ~~`skills/adele/SKILL.md:38` weights by `epoch(resolution)`: 720 hours for any month~~ done in
  `wp2`: a rule says that a table by calendar period has no resolution.
- ~~Queries could read the query log and write a file inside the folder of a table~~ fixed
  2026-11-14 (D24, `engine.py`). Since 2026-11-15 a query is one SELECT and nothing else: no
  EXPLAIN at all (D29, which supersedes D28). Also refused: the table functions `query`,
  `query_table` and `histogram`. Left over from that work:
  - a query over the row cap that ends with `;` or with a `--` comment fails (older defect: the
    server counts with `SELECT count(*) FROM (<query>)`).
  - ~~`deploy/adele-server.service` sets no working directory~~ fixed in WP1 step 2: both units
    have `WorkingDirectory=/tmp` (private per unit, `PrivateTmp=yes`).
  - scalar functions are on no list (814; none found that writes).

Fetch scheduling (G5), investigated 2026-11-15 by a subagent. Decided and built the same day
(D27): one systemd timer and one service per dataset, `fetch <id> --if-due`, "due" in whole
periods of `every`, `adele.refresh.timeout`, a backfill that holds the lock. 317 tests pass. Files
in `deploy/scheduling-poc/`: draft units, a test script for a Linux server, the prototypes and
their numbers. The claims about systemd were tested in a Docker container on the Mac (systemd
255 under emulation, 27 checks passed: `deploy/scheduling-poc/container-test/`), then on
the server (WP1 step 3, 27 of 27: `deploy/scheduling-poc/result-server.txt`). One claim was
wrong: `KillMode=mixed` does not wait for the children. Running on the server since 2026-11-15
(WP1).

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

- From WP1 (closed 2026-11-16, `docs/work-packages/WP1-server.md`):
  - ~~HTTPS on another port (WP1 step 6, way b, Caddy's `tls internal`)~~ done 2026-11-23 (D35,
    `deploy/access.sh`): port 8443, root certificate in the client (`adele-ca.pem`, valid until
    2036-10-01), `adele list` from a phone's network (Renaud).
  - Faults on purpose (WP1 step 8), on the code of the next deployment, each on a copy under
    another id: a renamed column, a duplicated row, an undeclared zone code, a fetch over its
    memory limit (status failing each time); the timers stopped for two hours, then the hole
    fetched (D25).
  - ~~Two checks that WP1's 17 hours could not make~~ seen on 2026-11-23: new delivery days of
    entsoe stored unattended (96 rows at a time on 2026-11-22), and `oom_score_adj` 1000 on
    the Python process of a fetch (kernel log, 2026-11-23 00:02).
- WP3 on the server (the code, the timer and the backfill of `entsoe_load` are there since
  2026-11-18; only the checks are left), once WP1 is done (done 2026-11-16; WP3 lands in `main` on 2026-11-15:
  Renaud relaxed the rule "after the week" of the WP1 doc): pull the code onto the server
  (`/opt/adele`), install `datasets/entsoe_load` with its timer, backfill it from 2015, let it fetch for 1-2 days
  (Renaud: "we won't wait a week, just 1-2 days"), then check `describe` (`versions_since`, the
  count of versions), the 50 checks, and a query with `--as-of` before the last fetch. If
  ENTSO-E revised a value in those days, the old value must come back with that `--as-of`
  (`docs/work-packages/WP3-versions.md`, step 4).
- `describe`: distinct values of categorical columns (column profiles), and `adele search`
  to resolve names to codes (zones, production types). See docs/agentic-data-layers.md.
- QA: 20 to 40 questions with known answers, rerun when a descriptor or the skill changes.
- `qa/tools/run.sh` keeps the home folder (2026-11-23): with `~/.claude/skills/adele` installed,
  a personal skill probably takes precedence over the project skill of the same name (from
  knowledge of Claude Code, not tested), so a QA run from a worktree tests the `SKILL.md` of
  main. Until it is settled: `rm ~/.claude/skills/adele` before such a run. Possible fix: stop
  when that path exists.
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
