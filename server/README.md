# adele-server

Fetches, checks, stores and serves the datasets of `../datasets/`. See SPEC.md and DECISIONS.md.

## Run (development, on the Mac)

```bash
cd server
cp adele-server.example.toml adele-server.toml   # then set a key per team member
uv run adele-server validate                     # load and validate every descriptor
uv run adele-server backfill entsoe_day_ahead_prices --start 2015-01-01
uv run adele-server backfill weathernext3 --start 2026-11-12 --end 2026-11-13 --step-hours 1
uv run adele-server fetch --due                  # every dataset that is due, one after the other (the Mac)
uv run adele-server fetch weathernext3 --if-due  # one dataset, if it is due (the server: a timer per dataset)
uv run adele-server serve                        # http://127.0.0.1:8000
uv run pytest                                    # includes the attempts to break out of the SQL lockdown
```

Then, with the client (`../client`): `ADELE_API_KEY=<key> uv run --project ../client adele list`.

## A dataset folder

The config lists the folders to read in `datasets_dirs` (a single `datasets_dir` still works): an
entry that holds a `datapackage.yaml` is one dataset (e.g. the checkout of a dataset's own
repository, whose folder name is free), any other entry is a folder of dataset folders (each
named like its dataset). Two datasets with the same id are an error.

- `datapackage.yaml`: the descriptor (Data Package v2 plus the `adele:` block). `adele.format_version: 1`
  is required: the server refuses a missing or unknown version.
- Every table has one time field: `delivery_start` (the start of the interval that a value covers,
  with a resolution) or `valid_at` (the instant that a value refers to, e.g. cloud cover at 12:00;
  no resolution). Coverage uses that field.
- `adele.secrets: [NAME, ...]`: the environment variables (source credentials) that fetch() gets.
  The child process gets nothing else from the server's environment except what uv and Python
  need (`PATH`, `HOME`, locale, certificates, proxies, `UV_*`, `PYTHON*`, `XDG_*`).
- `fetch.py`: `fetch(start, end)` returns the rows of the window [start, end) on the window
  column. With an inline script block (PEP 723: `# /// script`, `# dependencies = [...]`), the
  server runs it with `uv run --script` in an environment built from those dependencies, so the
  server doesn't carry every source's libraries; uv must be on the PATH. Without the block, it
  runs in a child process with the server's Python. uv keeps one environment per path of a
  script, so the script that the server hands to uv has the same path at every fetch:
  `<cache>/runners/<dataset>/_runner.py` (see Files). In a new temporary folder each time, uv
  built the environment again at each fetch (8.7 s, against 0.3 s).
- `adele.refresh`: `every`, `lookback`, `horizon`, and optionally `max_window` and `timeout`
  (ISO 8601 durations). Any other key is refused, so that a misspelt key is not ignored.
  A scheduled run (`fetch --due`, `fetch <id> --if-due`, or `fetch <id>` without `--start` / `--end`) fetches
  [last - lookback, now + horizon). last is the time of the last scheduled run that succeeded
  (`last_scheduled_at` in `state.json`), or now on the first run. So after a stop longer than
  the lookback (server down, a long backfill), the next run also fetches the time of the stop.
  A run that fails keeps `last_scheduled_at`: the next run fetches the same stretch again. A
  fetch with `--start` or `--end` never moves it.
- Giving up: a stretch that fails is retried for one lookback, not for ever. `failing_since` in
  `state.json` is the time of the first scheduled run that failed since the last one that
  succeeded. A run that starts more than one lookback after it fetches [now - lookback, now +
  horizon) again, whatever `last_scheduled_at` says, until a run succeeds. The first such run
  writes the stretch that it leaves out, [`last_scheduled_at` - lookback, now - lookback), to
  the log and to `alerts.log`, once. To fetch that stretch later, run a backfill over it.
- `adele.refresh.max_window`: a scheduled window longer than it is fetched in pieces of that
  length, oldest first, each one merged before the next starts. Each piece has its own time limit
  (`fetch_timeout_s`). A piece that fails does not stop the run: every piece is attempted, and
  the run counts as failed when at least one failed. So a part that can't be fetched keeps out
  only its own piece. Without the key, a window is one fetch, whatever its length: it fails as
  a whole, and a long catch-up may exceed the time limit until the server gives up on it.
  `backfill` uses `max_window` as its step when no `--step-days` / `--step-hours` is given
  (else 365 days).
- `adele.refresh.timeout`: the time limit of one call of `fetch.py` for this dataset. The limit
  that applies is the smaller of it and the server's `fetch_timeout_s`. With `max_window`, each
  piece has that limit.
- A backfill whose end is not before the time at which it started counts as a scheduled run made
  at that time: `last_scheduled_at` moves there and `failing_since` is cleared. Also when some
  windows failed (the command lists them; the scheduled runs fetch again only from that time
  minus the lookback). Not when every window failed, not when the backfill starts after
  `last_scheduled_at` - lookback (the time before its start is still to fetch), and never
  backwards.
- `adele.revisions`: `overwrite` (the latest fetch wins on the key; each scheduled run fetches
  the whole window), `none` (rows never change once stored: the server calls fetch only on
  the parts of the window that hold no stored value of the window column, in every table, and
  refuses a fetched row that differs from the stored one) or `append-only` (D30: every version
  of a row is kept with `fetched_at`, and `superseded_at`, the `fetched_at` of the next version;
  `<id>.<table>` is the latest version, `<id>.<table>_versions` every version; `POST /query`
  takes `as_of`). The policy of a stored dataset can't change.
- `adele.partition`: `month` (default) or `day` of the window column. After a change, run
  `adele-server repartition <id>` (fetches and checks refuse the old layout).
- `checks.yaml` (optional): published figures that the data must reproduce. Each entry has
  `name`, `question`, `sql` (one row, one number), `expected`, `tolerance`, `source`. They run
  after each fetch; a figure outside its tolerance sets the status to failing.

## Files

- `<data_dir>/<dataset>/<table>/<YYYY-MM>.parquet` or `<YYYY-MM-DD>.parquet`: one partition per
  month or day (UTC, `adele.partition`) of the window column: delivery_start, or the column that
  `adele.window` names (init_time for forecasts).
- `<data_dir>/<dataset>/state.json`: fetch times, status, problems. `last_scheduled_at` is the
  time of the last scheduled run that succeeded: the next scheduled window starts at that time
  minus the lookback. `failing_since` and `given_up` (the stretch that was left out) exist only
  while the scheduled runs fail.
- `<cache>/runners/<dataset>/_runner.py`: the script that uv runs for a `fetch.py` with a script
  block. `<cache>` is `cache_dir` of the config, else `$CACHE_DIRECTORY` (systemd sets it for a
  unit with `CacheDirectory=adele`), else `~/.cache/adele`. It is not in the data folder.
  `runners` and the folder of the dataset must belong to the user of the server, with mode 0700
  (the server makes them so): Python imports from the folder of the script first. If they are
  not, the server warns and uses a temporary folder (the fetch works, uv is slow).
- `<log_dir>/queries.jsonl`: one line per query (key name, SQL, duration, rows).
- `<log_dir>/alerts.log`: one line per status change, and one per stretch that the scheduled
  runs gave up on (email: POC 2).

Agent SQL reads only the folders of the tables (`<data_dir>/<dataset>/<table>/`). It can't read
`state.json`, the logs or any other file of the data folder (`engine.py`, tested in
`tests/test_engine.py`). It can't write a file either: a query is one SELECT, without COPY,
INSERT, UPDATE or DELETE inside a `WITH`, and with table functions from a list
(`TABLE_FUNCTIONS` in `engine.py`). No other statement runs, also no `EXPLAIN` (D29). The same
holds for the SQL of `adele.examples` and `checks.yaml`.

## Scheduling

- When a dataset is due: when now lies in a later period of `adele.refresh.every` than the last
  attempt (`last_attempt_at` in `state.json`). The periods are counted on the clock in UTC:
  `PT1H` starts on the hour, `P1D` at midnight, `P1W` on Monday. So a tick at 13:00:00 runs
  also when the attempt before was stamped 12:00:01. A dataset without an attempt is due, and
  so is one whose last attempt is later than now (a clock that was set back).
- `fetch <id> --if-due`: for one timer per dataset that ticks every minute. Not due: exit code 0,
  no output, no fetch. The command then reads only `state.json` and the descriptor of that
  dataset (0.04 s of CPU, against 0.36 s when the catalog is loaded). Due: a scheduled run,
  as `fetch <id>`.
- `fetch --due`: every dataset that is due, one after the other, with the same rule.
- An invalid descriptor does not stop `fetch`: each one gives one line on stderr ("invalid, not
  loaded: ...") and the valid datasets are fetched. `fetch --due` then ends with exit code 2,
  and so does `fetch <id>` when the descriptor of `<id>` is the invalid one. `validate`,
  `serve`, `backfill`, `check` and `repartition` refuse a catalog with an error.
- One lock per dataset. A fetch that meets it is skipped ("skip <id>: another fetch of <id> is
  running", exit code 0) and writes nothing, so the dataset stays due. A backfill holds the
  lock from before its first window until after its checks: a second backfill or a `check`
  meanwhile ends with that message and exit code 1.
- After a backfill, the first tick in a later period than its start runs. The windows of a
  backfill stamp `last_attempt_at`, but at its end the field is set to the time at which the
  backfill started (when it counts as a scheduled run, see above), else to its value of before.
- SIGTERM and SIGINT during `fetch` or `backfill`: the server kills `fetch.py` (the whole
  process group, so uv and its python), records the attempt as failed ("last fetch failed:
  interrupted by SIGTERM: ...") in `state.json` and `alerts.log`, releases the lock and ends
  with exit code 143 (SIGTERM) or 130 (SIGINT). No further piece, window or dataset starts,
  and no check runs. `last_scheduled_at` stays, and `failing_since` is not set: the next run
  fetches the same stretch, however long the server was down. A second signal ends the
  command at once.

## Modules

| module | role |
|---|---|
| `catalog.py` | load and validate `datapackage.yaml`, `fetch.py`, `checks.yaml` (refuses to start on an error) |
| `ingest.py` | fetch a window (child process, or `uv run --script`), check it against the schema, merge, run the checks, update the state; the scheduled window and its pieces |
| `storage.py` | month or day partitions written by DuckDB, temp file + rename (D9); merge per revision policy; repartition |
| `checks.py` | declared means checked: key, codes, stored types, example queries, published figures |
| `engine.py` | agent SQL: locked-down DuckDB, caps on rows, time, memory (D10) |
| `render.py` | the text agents read: list, describe card, query footer |
| `app.py` | HTTP API (bearer key per team member) |
| `state.py` | `state.json` per dataset; when a dataset is due (periods of `every` on the clock) |
| `cli.py` | `adele-server validate / serve / fetch / backfill / check / repartition`; the cheap answer of `fetch <id> --if-due` |
