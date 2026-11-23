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
- extensions: all adele properties go in one `adele:` block at package level
  (format_version, resolution, refresh, revisions, window, partition, expected_spacing,
  secrets, plus the computed ones). `adele.format_version` is the version of the
  descriptor format (1); the server refuses another. Fields get a free-text `unit`
  (EUR/MWh, MW, MWh).
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
  about the dataset goes in `adele.warnings`, a list of short sentences. A warning that
  matters for every query is marked `{text: ..., footer: true}`: the query footer shows it.
- example queries --> `adele.examples`, at most five; `describe` prints them all. An example
  is a `question` and its `sql`, with `verified_at` once a person has confirmed the result.
  Or it names a check of `checks.yaml` (`check: <name>`): `describe` then prints the check's
  question and SQL, and the published figure that the SQL reproduces, with its source. The
  server runs every example after each fetch; an example that fails sets status to failing.

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

Each scheduled run fetches [last - lookback, now + horizon), where `last` is the time of
the last scheduled run that succeeded (`now` for the first run). `lookback` and `horizon`
are set in `adele.refresh`. The lookback catches revisions and late data; the horizon
covers data published before delivery (e.g. day-ahead prices). The initial backfill calls
`fetch` on successive windows.

After a stop (the server was down, the source failed, a long backfill ran), the next run
fetches everything since the last run that succeeded, and no hole stays. A run that fails
is tried again from the same place for one lookback. Then adele gives up on the older part,
writes which part to the alert log, and returns to [now - lookback, now + horizon). A
dataset can set `adele.refresh.max_window`: a longer window is fetched in pieces of that
length, oldest first, and a piece that fails does not stop the later ones. It can also set
`adele.refresh.timeout`, the time limit of one call of `fetch.py`.

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

- a table has one time column, or none:
  - `delivery_start`: the start of an interval of fixed duration, in UTC.
  - `valid_at`: an instant, in UTC.
  - `delivery_date`, `delivery_month` or `delivery_year`: a calendar day, month or year in
    the time zone that the table declares (`timezone`, e.g. Europe/Zurich), stored as a
    date. A month and a year are stored as their first day. `describe` prints the
    expression that joins such a table with a table in UTC.
  - none (a register of plants, a list of stations): each fetch replaces the whole table.
- all timestamps are stored in UTC. A calendar period is stored as a date, never as a
  timestamp: a local day lasts 23 to 25 hours.
- a timestamp marks the start of its interval; intervals are half-open: [start, start +
  resolution). A value at an instant (e.g. cloud cover at 12:00) has no interval: its table
  has `valid_at` instead of `delivery_start`, and no resolution.
- coverage = first and last delivery interval (or instant) present, and the range of the
  window column when it isn't the delivery time.
- resolution is an ISO 8601 duration (PT15M, PT1H, P1D). When it differs between series or
  changes over time, each row carries it in a `resolution` column, and the catalog lists the
  periods of each series, computed from the data.
- freshness = last_fetched_at, last_changed_at (a fetch may bring nothing new), next_fetch_eta,
  status (ok | stale | failing).
- expected spacing: a dataset can declare how often its window values appear (e.g. one
  forecast run per hour), in periods like resolution. Each expected value that is missing
  between the first period and the last stored value sets status to failing.

## Revisions

Sources revise past values (e.g. ENTSO-E corrects actual load days later). Each dataset
declares its policy in the catalog:

- `overwrite`: adele keeps only the latest value.
- `append-only`: adele keeps every version of a row. A fetch stores a row when its key is new
  or one of its values changed, with `fetched_at`, the time at which adele got it.
  `<id>.<table>` returns the latest version of each row, `<id>.<table>_versions` every
  version. `as_of=<timestamp>` returns what adele held at that time. Versions start with the
  first scheduled fetch (`versions_since`): rows backfilled before carry the time of the
  backfill, so an earlier `as_of` is refused. `fetched_at` is not the time at which the source
  published a value: a value may look later than it was, never earlier.
- `none`: values never change once published (e.g. forecast runs). adele fetches only the
  parts of the window that it doesn't hold yet; a changed value is an error.
  
## Storage

The server normalizes every source on ingest. Source formats (csv, xlsx, SQL database, APIs) never reach the client.

- a trap that a column can remove is removed on ingest, not only documented. E.g. a table with
  `load_mw` (mean power over the interval) also gets `energy_mwh`, which can be summed.
- a dataset is one or more tables; each table is stored as Parquet, partitioned by month of
  its window time (by default the delivery month), or by day when the dataset declares
  `adele.partition: day`.
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
   query read: resolution, units, the warnings marked for the footer, freshness. An agent
   that skipped `describe` still gets the main warnings next to the numbers.
4. `pull <id> [--since <date>]`: copy the Parquet partitions locally for heavy work.

Two items in describe help agents more than anything else:

- The grain, e.g. "one row per (bidding_zone, delivery_start)".
- Sample rows. They show the real value formats (EIC codes, units, nulls). Types alone do not.


## Security

Remote `query` runs SQL written by an agent, so the limits are set in the engine, not by
inspecting the SQL text.

- read-only: the server's DuckDB can read the Parquet files of the catalog and nothing else
  (no other local file, no network, no extension install, no change of settings by a query).
  DuckDB can't make an allowed folder read-only, so the server runs only what DuckDB's
  parser shows to be a read (one SELECT, with table functions from a list; no other
  statement, also no EXPLAIN), and the query process runs as a user that can only read the
  data.
- limits per query: time, rows returned, memory, temporary files. A limited number of queries
  run at once; the others wait, then get an error that says so.
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