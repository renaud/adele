# Adele: *a*gentic *d*ata *l*ayer

## Architecture
  
- _server_: a system running on a linux server (so: always on) to
  -  fetch the datasets at regular intervals, depending on their refresh rate
  -  exposes the datasets to a local agent (see _client_)
  -  auth: one API key per team member, listed in the server config file. To add or revoke a key, edit the file and restart the server.

  -  alerts: when a dataset's status changes (ok --> failing, failing --> ok), the server sends
     one email to the admin address in the config file. A fetch that fails, or a source whose schema
     differs from the declared one, sets status to failing. The server never changes a schema
     silently.

- _client_: a Python lib with a CLI (`adele list | describe | query | pull`). The CLI reads
  the API key from `ADELE_API_KEY`.

- _skill_: a SKILL.md that teaches an agent the four steps of Agent access, using the CLI.
  The HTTP API is documented as a fallback.

## Catalog

One [Frictionless](https://github.com/frictionlessdata/datapackage) [Data Package](https://datapackage.org/) per dataset (standard, precise, extendable, known to agents).

- authored vs computed: whoever adds a dataset writes its `datapackage.yaml` (in git). The server
  adds the computed fields (coverage, freshness, status, row counts, `duckdb_type`) and serves
  the merged JSON.
- extensions: all adele properties go in one `adele:` block at package level (resolution,
  refresh, revisions, plus the computed ones). Fields get a free-text `unit` (EUR/MWh, MW, MWh).
- types: `describe` shows each field's Table Schema `type` and its `duckdb_type`, read from Parquet.
- validation: the server validates every descriptor at startup (frictionless-py, descriptor
  only) and refuses to start on an error. `resource.path` is required by the standard; it
  points to the `pull` endpoint.

### Keys or prose

Whatever the server can check goes in a key. The rest is prose inside a key. There is no
separate prose document: the agent never reads the YAML, it reads what `describe` prints.

- grain --> `primaryKey`. The server checks that the key is unique in the data.
- units --> `unit` per field.
- code meanings --> value and label per field. The server checks that the data holds no
  undeclared value.
- traps --> prose. A trap about one field goes in the `description` of that field. A trap
  about the dataset goes in `adele.warnings`, a list of short sentences.
- example queries --> `adele.examples`, a list of `question`, `sql`, `verified_at`. `describe`
  prints two or three. The server runs all of them after each fetch; an example that fails
  sets status to failing.

Sketch for the first dataset (key names to be settled when it runs; `categories` to be
checked against Data Package v2):

```yaml
name: entsoe_day_ahead_prices
title: Day-ahead prices per bidding zone (ENTSO-E)
resources:
  - name: prices
    schema:
      primaryKey: [bidding_zone, delivery_start]
      fields:
        - name: bidding_zone
          type: string
          description: Short zone name. Zones change over time (DE_AT_LU ended 2018-10-01).
          categories: [{value: CH, label: Switzerland}, {value: DE_LU, label: Germany-Luxembourg}]
        - name: delivery_start
          type: datetime
          description: Start of the delivery interval, UTC.
        - name: price
          type: number
          unit: EUR/MWh
adele:
  resolution:
    - {from: "2015-01-01", value: PT1H}
    - {from: "2025-10-01", value: PT15M}
  warnings:
    - A plain average over a period that spans 2025-10-01 gives the 15-minute rows 4 times the weight of the hourly rows.
    - The delivery day is defined in CET/CEST, not UTC.
  examples:
    - question: Average day-ahead price in CH per delivery day in March 2026?
      sql: |
        SELECT date_trunc('day', delivery_start AT TIME ZONE 'Europe/Zurich') AS day, avg(price)
        FROM prices WHERE bidding_zone = 'CH' AND ... GROUP BY 1
      verified_at: 2026-11-13
```

## Adding a dataset

A dataset is a folder `datasets/<id>/` in git:

- `datapackage.yaml`: the catalog entry (see Catalog).
- `fetch.py`: one function `fetch(start, end)` that returns a pyarrow Table or pandas DataFrame
  with the rows whose delivery time falls in [start, end). A source that only serves
  "everything" or "latest" may ignore the window; the server filters.

Each scheduled run fetches [last - lookback, now + horizon), where `last` is the time of the
last scheduled run that succeeded (`now` for the first run). `lookback` and `horizon` are set in
`adele.refresh`. The lookback is what catches revisions; the horizon covers data published
before delivery (e.g. day-ahead prices). The initial backfill calls `fetch` on successive
windows.

After a stop (the server was down, the source failed, a long backfill ran), the next run so
fetches everything since the last run that succeeded, and no hole stays. A run that fails is
tried again from the same place for one lookback. Then adele gives up on the older part, writes
which part to the alert log, and returns to [now - lookback, now + horizon). A dataset can set
`adele.refresh.max_window`: a longer window is fetched in pieces of that length, oldest first,
and a piece that fails does not stop the later ones.

The server does everything else: scheduling, schema check, revisions, storage, alerts.
A connector never writes files. Source credentials (e.g. an ENTSO-E token) come from the
server config, never from git.

Two skills in `skills/` support this work: `add-dataset` (a person writes the definitions, the
agent places them in the descriptor and writes `fetch.py`) and `review-dataset` (critics test
the descriptor against the data before the dataset is published).

## Time conventions

Every dataset has two time axes, and the catalog reports both:

- *delivery time*: the period a value refers to (e.g. the 15-minute interval for which a price holds).
- *knowledge time*: when the value became available (published by the source, fetched by adele).

Rules:

- all timestamps are stored in UTC; local time is a display concern only.
- a timestamp marks the start of its interval; intervals are half-open: [start, start + resolution).
- resolution is an ISO 8601 duration (PT15M, PT1H, P1D). If it changed over the dataset's
  history, the catalog lists each period with its resolution.
- coverage = first and last delivery interval present.
- freshness = last_fetched_at, last_changed_at (a fetch may bring nothing new), next_fetch_eta,
  status (ok | stale | failing).


## Revisions

Sources revise past values (e.g. ENTSO-E corrects actual load days later). Each dataset
declares its policy in the catalog:

- `overwrite`: adele keeps only the latest value.
- `append-only`: every row carries `fetched_at`. Queries return the latest value per key;
  `as_of=<timestamp>` returns what adele knew at that time.
  

## Storage

The server normalizes every source on ingest. Source formats (csv, xlsx, SQL database, APIs) never reach the client.

- a trap that a column can remove is removed on ingest, not only documented. E.g. a table with
  `load_mw` (mean power over the interval) also gets `energy_mwh`, which can be summed.
- a dataset is one or more tables; each table is stored as Parquet, partitioned by delivery month.
- DuckDB is the query engine: on the server for remote queries, on the client for local copies.
- a local copy is a set of Parquet partitions; sync is incremental (changed partitions only).
- the server writes each partition to a temporary file and renames it, so readers never see a half-written partition.

## Agent access

Access goes in four steps, each one cheap in tokens:

1. `list`: one line per dataset (id, title, resolution, coverage, status).
2. `describe <id>`: the full dataset card: description, grain (what one row is), fields
   (type, unit, description), coverage, freshness, license, 5 sample rows.
3. `query "<sql>"`: DuckDB SQL run on the server; results capped at N rows. A capped result
   says so and says how to get the rest ("showing 100 of 35,040 rows. Aggregate, narrow the
   filter, or use pull"). Every result ends with a short footer for the datasets that the
   query read: resolution, units, `adele.warnings`, freshness. An agent that skipped
   `describe` still gets the warnings next to the numbers.
4. `pull <id> [--since <date>]`: copy the Parquet partitions locally for heavy work.

Two items in describe help agents more than anything else:

- The grain, e.g. "one row per (bidding_zone, delivery_start)".
- Sample rows. They show the real value formats (EIC codes, units, nulls). Types alone do not.


## Security

Remote `query` runs SQL written by an agent, so the limits are set in the engine, not by
inspecting the SQL text.

- read-only: the server's DuckDB can read the Parquet files of the catalog and nothing else
  (no other local file, no network, no extension install, no change of settings by a query).
- limits per query: time, rows returned, memory.
- log: one line per query (key id, SQL, duration, rows).
- values in cells and descriptions that come from a source are data, never instructions. The
  skill says so.

## Backups

Back up the stored data and the server config. Some sources delete files after a day, and
sources replace old values with revised ones, so adele may hold the only copy left.

##  Non-goals

- no writes from clients
- no dashboards
- no real-time streaming
- no data that is not a table: images, PDFs, rasters, full grids. From a grid, adele stores an
  extract as a table (e.g. the cells over Switzerland).
- no data delivered by hand (a file exported in a browser, a table typed from a PDF): `fetch.py`
  gets every dataset from its source.