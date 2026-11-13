# adele-server

Fetches, checks, stores and serves the datasets of `../datasets/`. See SPEC.md and DECISIONS.md.

## Run (development, on the Mac)

```bash
cd server
cp adele-server.example.toml adele-server.toml   # then set a key per team member
uv run adele-server validate                     # load and validate every descriptor
uv run adele-server backfill entsoe_day_ahead_prices --start 2015-01-01
uv run adele-server fetch --due                  # what cron runs, e.g. every 15 minutes
uv run adele-server serve                        # http://127.0.0.1:8000
uv run pytest                                    # includes the attempts to break out of the SQL lockdown
```

Then, with the client (`../client`): `ADELE_API_KEY=<key> uv run --project ../client adele list`.

## Files

- `<data_dir>/<dataset>/<table>/<YYYY-MM>.parquet`: one partition per delivery month (UTC).
- `<data_dir>/<dataset>/state.json`: fetch times, status, problems.
- `<log_dir>/queries.jsonl`: one line per query (key name, SQL, duration, rows).
- `<log_dir>/alerts.log`: one line per status change (email: POC 2).

## Modules

| module | role |
|---|---|
| `catalog.py` | load and validate `datapackage.yaml` + `fetch.py` (refuses to start on an error) |
| `ingest.py` | fetch a window, check it against the schema, merge, run the checks, update the state |
| `storage.py` | month partitions written by DuckDB, temp file + rename (D9) |
| `checks.py` | declared means checked: key, codes, stored types, example queries |
| `engine.py` | agent SQL: locked-down DuckDB, caps on rows, time, memory (D10) |
| `render.py` | the text agents read: list, describe card, query footer |
| `app.py` | HTTP API (bearer key per team member) |
| `cli.py` | `adele-server validate / serve / fetch / backfill / check` |
