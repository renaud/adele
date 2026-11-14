# adele-server

Fetches, checks, stores and serves the datasets of `../datasets/`. See SPEC.md and DECISIONS.md.

## Run (development, on the Mac)

```bash
cd server
cp adele-server.example.toml adele-server.toml   # then set a key per team member
uv run adele-server validate                     # load and validate every descriptor
uv run adele-server backfill entsoe_day_ahead_prices --start 2015-01-01
uv run adele-server backfill weathernext3 --start 2026-11-12 --end 2026-11-13 --step-hours 1
uv run adele-server fetch --due                  # what cron runs, e.g. every 15 minutes
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
  runs in a child process with the server's Python.
- `adele.revisions`: `overwrite` (the latest fetch wins on the key; each scheduled run fetches
  the whole window [now - lookback, now + horizon)) or `none` (rows never change once stored:
  the server calls fetch only on the parts of the window that hold no stored value of the window
  column, in every table, and refuses a fetched row that differs from the stored one).
- `adele.partition`: `month` (default) or `day` of the window column. After a change, run
  `adele-server repartition <id>` (fetches and checks refuse the old layout).
- `checks.yaml` (optional): published figures that the data must reproduce. Each entry has
  `name`, `question`, `sql` (one row, one number), `expected`, `tolerance`, `source`. They run
  after each fetch; a figure outside its tolerance sets the status to failing.

## Files

- `<data_dir>/<dataset>/<table>/<YYYY-MM>.parquet` or `<YYYY-MM-DD>.parquet`: one partition per
  month or day (UTC, `adele.partition`) of the window column: delivery_start, or the column that
  `adele.window` names (init_time for forecasts).
- `<data_dir>/<dataset>/state.json`: fetch times, status, problems.
- `<log_dir>/queries.jsonl`: one line per query (key name, SQL, duration, rows).
- `<log_dir>/alerts.log`: one line per status change (email: POC 2).

## Modules

| module | role |
|---|---|
| `catalog.py` | load and validate `datapackage.yaml`, `fetch.py`, `checks.yaml` (refuses to start on an error) |
| `ingest.py` | fetch a window (child process, or `uv run --script`), check it against the schema, merge, run the checks, update the state |
| `storage.py` | month or day partitions written by DuckDB, temp file + rename (D9); merge per revision policy; repartition |
| `checks.py` | declared means checked: key, codes, stored types, example queries, published figures |
| `engine.py` | agent SQL: locked-down DuckDB, caps on rows, time, memory (D10) |
| `render.py` | the text agents read: list, describe card, query footer |
| `app.py` | HTTP API (bearer key per team member) |
| `cli.py` | `adele-server validate / serve / fetch / backfill / check / repartition` |
