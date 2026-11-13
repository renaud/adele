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

- `datapackage.yaml`: the descriptor (Data Package v2 plus the `adele:` block).
- `fetch.py`: `fetch(start, end)` returns the rows of the window [start, end) on the window
  column. With an inline script block (PEP 723: `# /// script`, `# dependencies = [...]`), the
  server runs it with `uv run --script` in an environment built from those dependencies, so the
  server doesn't carry every source's libraries; uv must be on the PATH. Without the block, it
  is imported in a child process of the server.
- `checks.yaml` (optional): published figures that the data must reproduce. Each entry has
  `name`, `question`, `sql` (one row, one number), `expected`, `tolerance`, `source`. They run
  after each fetch; a figure outside its tolerance sets the status to failing.

## Files

- `<data_dir>/<dataset>/<table>/<YYYY-MM>.parquet`: one partition per month (UTC) of the window
  column: delivery_start, or the column that `adele.window` names (init_time for forecasts).
- `<data_dir>/<dataset>/state.json`: fetch times, status, problems.
- `<log_dir>/queries.jsonl`: one line per query (key name, SQL, duration, rows).
- `<log_dir>/alerts.log`: one line per status change (email: POC 2).

## Modules

| module | role |
|---|---|
| `catalog.py` | load and validate `datapackage.yaml`, `fetch.py`, `checks.yaml` (refuses to start on an error) |
| `ingest.py` | fetch a window (child process, or `uv run --script`), check it against the schema, merge, run the checks, update the state |
| `storage.py` | month partitions written by DuckDB, temp file + rename (D9) |
| `checks.py` | declared means checked: key, codes, stored types, example queries, published figures |
| `engine.py` | agent SQL: locked-down DuckDB, caps on rows, time, memory (D10) |
| `render.py` | the text agents read: list, describe card, query footer |
| `app.py` | HTTP API (bearer key per team member) |
| `cli.py` | `adele-server validate / serve / fetch / backfill / check` |
