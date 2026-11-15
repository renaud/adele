# Decisions

Implementation choices and why we made them. SPEC.md says what adele does. This file says how
we build it, why, and which alternatives we rejected.

Open questions sit at the top. When one is answered, it becomes a new Dn entry and leaves the
list.

Entries are append-only. To reverse a decision, add a new entry that supersedes it, and add
"Superseded by Dn" to the old one. Don't change the old entry otherwise.

## Open

None.

## D1 - Client depends only on DuckDB; frictionless is server-only (2026-11-13)

**Decision.** The client package depends on duckdb only. frictionless-py is a server dependency.

**Why.** The client is what every team member installs. Measured with `uv pip compile` (Linux,
Python 3.12, duckdb 2.0.0, frictionless 5.21.0; install sizes measured on macOS):

- duckdb: 0 dependencies, ~49 MB (one native wheel).
- frictionless: 38 dependencies, ~35 MB. Most of them serve features that adele doesn't use:
  reading tabular data (petl, chardet, simpleeval), its own CLI (typer, rich, shellingham),
  report rendering (jinja2, marko, tabulate). The server only needs frictionless to validate
  descriptors at startup (SPEC.md, Catalog).
- For scale: fastapi + uvicorn alone bring 14 packages. fastapi + uvicorn + duckdb +
  frictionless + pyyaml bring 47.

**Rejected.**

- frictionless on both sides.
- Replacing frictionless on the server by jsonschema + pyyaml, validating against the Data
  Package JSON Schema (7 packages). Possible later, if the checks that frictionless runs beyond
  the JSON Schema turn out not to matter.

## D2 - The CLI uses the standard library only (2026-11-13)

**Decision.** The client parses its arguments with `argparse` and calls the server with
`urllib.request`, both from the standard library. With D1, the client installs one package:
duckdb.

**Why.** Rule: the CLI gets what it needs, with as few libraries as possible. Beyond DuckDB, the
CLI needs an argument parser for four subcommands, and an HTTP client, because every command
calls the server's REST API (`query` sends SQL, `pull` downloads Parquet files). The standard
library covers both. Users who call the REST API directly bring their own HTTP client (e.g.
`requests`); that adds nothing to the client's dependencies.

**Rejected.** typer + httpx (19 packages in total, with duckdb). typer generates help text from
type hints; httpx reuses connections when `pull` downloads many partitions. Neither matters at
four commands. Revisit if `pull` turns out slow.

## D3 - Two distributions: `adele` and `adele-server` (2026-11-13)

**Decision.** The client and the server ship as two separate distributions: `adele` (the CLI,
D1 and D2) and `adele-server`.

**Why.** Every team member installs the client; only the Linux server runs the server. With two
distributions, the server's dependencies can't end up in the client's install.

**Rejected.** One package with an optional extra (`pip install adele[server]`). The client
package would then contain the server code, which fails to import unless the extra is installed.

## D4 - The library and the CLI ship together in `adele` (2026-11-13)

**Decision.** The `adele` distribution (D3) contains both the Python library (`import adele`,
e.g. `adele.query(...)`) and the CLI. The library is the core. The CLI is a thin layer: each
subcommand parses its arguments, calls one library function and prints the result.
`[project.scripts]` in `pyproject.toml` creates the `adele` command on install.

**Why.** Agents that work in Python call the library; agents that use the shell call the CLI.
Since D2 the CLI adds no packages, so nothing argues for a split. With one code path, the CLI
and the library can't behave differently. The same package installs two ways:
`uv tool install adele` (the command, in its own environment) or `uv add adele` (importable in
a project).

**Rejected.** Three distributions (`adele`, `adele-cli`, `adele-server`), or a CLI extra
(`adele[cli]`). A split only pays off if the CLI needs dependencies that library users
shouldn't have to install (typer, rich).

## D5 - Client and server are two independent uv projects in one repo (2026-11-13)

**Decision.** One repo with two folders: `client/` (distribution `adele`) and `server/`
(distribution `adele-server`, D3). Each folder is an independent uv project with its own
`pyproject.toml`, `uv.lock` and `.venv`. For end-to-end tests, the server's dev dependency group
installs the client from its folder.

**Why.** The client's `.venv` then holds duckdb and nothing else (D1, D2). If client code imports
any other package, the import fails at once, in development and in the tests. In a shared
`.venv` the same import would succeed, because the server's packages are installed there, and
the error would show up only when a team member installs the client.

**Rejected.**

- A uv workspace (one lockfile and one `.venv` for both): it hides the imports that break D1
  and D2, for the reason above.
- Two GitHub repos: a change to the HTTP API changes both sides, and one commit should hold
  both.

## D6 - Library API for the POC (2026-11-13)

**Decision.** For the POC, the library has one function per CLI subcommand:

- `adele.datasets()` and `adele.describe(id)` return the text that the CLI prints.
- `adele.query(sql)` returns an object with `columns`, `rows`, `total` (the row count before
  the cap) and `footer`. Its `str()` is what the CLI prints.

**Why.** The server renders the describe card and the query footer as text, so that the CLI and
the HTTP fallback show the same thing. Returning that text costs nothing. `query` returns rows
because a Python agent computes on the values, not on printed text. The name `datasets` avoids
`list`, which would shadow Python's built-in.

**Later.** Typed returns for `datasets()` and `describe()` (e.g. the merged descriptor as a
dict), once someone uses them from Python. `pull()` comes with POC 2 (TODOs.md).

## D7 - On the Mac, the data folder is `data_nosync/` (2026-11-13)

**Decision.** When the server runs on the Mac, its data folder is `data_nosync/` at the repo
root. The suffix `_nosync` keeps it out of the SWITCHdrive sync, and `.gitignore` keeps it out
of git.

**Why.** Every fetch rewrites month partitions, which SWITCHdrive would upload again each time.
The folder has no backup. That is acceptable on the Mac, because a backfill from the ENTSO-E API
regenerates it. On the Linux server, the config sets the data folder, and SPEC.md, Backups,
applies.

## D8 - SQL table names are qualified: `<dataset>.<table>` (2026-11-13)

**Decision.** Option A of docs/sql-table-names.md. Each dataset is a DuckDB schema named after
its id. Each resource of its datapackage is a view in that schema, named after the resource.
Queries always name both: `entsoe_day_ahead_prices.prices`. Dataset ids and resource names use
`[a-z0-9_]` and start with a letter. A dataset id must not be a name that DuckDB reserves
(`main`, `temp`, `system`, `memory`, `information_schema`, `pg_catalog`). The server checks both
rules at startup.

**Why.**

- Two tables can't have the same name, by construction.
- It matches Frictionless exactly: package --> schema, resource --> table. Resource names only
  need to be unique within their package, as the standard says.
- An agent that leaves out the dataset id gets an error, not a wrong number. Tested with duckdb
  2.0.0: `FROM prices` returns `Did you mean "entsoe_day_ahead_prices.prices or
  entsoe_imbalance_prices.prices"?`
- The query footer reads the dataset from the schema name.
- The cost, a longer name in every query, is small: under C, table names would have to carry the
  source anyway to stay unique.

**Rejected.** B (no join on the server). C (a rule across the whole catalog that the standard
doesn't have, checked at startup; it was the first recommendation of docs/sql-table-names.md).
D (two ways to write the same query, and the search path must be set before the configuration is
locked).

## D9 - DuckDB writes the partitions; no ingestion library (2026-11-13)

**Decision.** The server writes the month partitions with DuckDB. For each delivery month of a
fetched batch: read the month's partition, drop the rows whose primary key is in the batch, add
the batch, write a temp file, rename it. No ingestion library.

**Why.** dlt (the candidate of docs/prior-art.md) would duplicate what adele already takes from
the descriptor: the fetch window (lookback, horizon) and the schema (`datapackage.yaml`). And its
file destination doesn't fit SPEC.md, Storage
(https://dlthub.com/docs/dlt-ecosystem/destinations/filesystem, read 2026-11-13):

- with plain Parquet files, "`merge` - falls back to `append`". Merge on a key needs Delta or
  Iceberg tables.
- the layout placeholders are the table name, the load id, the file id and the time of the
  load. None of them comes from a value in the rows, so dlt can't write one file per delivery
  month.

**Rejected.** dlt as a library. Revisit if the number of sources or of revision policies grows.

## D10 - Agent SQL: engine settings for reads, a statement filter for writes (2026-11-13)

**Decision.** Each query gets a fresh in-memory DuckDB connection: `enable_external_access =
false` with `allowed_directories = [data_dir]`, extensions neither installed nor loaded
automatically, `memory_limit`, `threads`, `TimeZone = 'UTC'`, then `lock_configuration = true`.
Only one statement per query, and only SELECT or EXPLAIN, as DuckDB's parser classifies it
(`extract_statements`). A timer calls `interrupt()` at the time limit. On the Linux server, the
HTTP process runs as a user that can only read the data folder; the fetch runs as another user.

**Why.** Measured with duckdb 2.0.0; the attempts are now tests (`server/tests/test_engine.py`):

- Reads outside the data folder fail, including `..` and symlinks. So do reads over https,
  installing or loading an extension, and changing a setting after the lock. `getenv` doesn't
  exist in the Python API.
- Writes inside an allowed folder succeed: `COPY ... TO`, `EXPORT DATABASE` and `ATTACH` created
  files next to the partitions. A query could have added or replaced a partition. No DuckDB
  setting makes an allowed folder read-only. The statement filter blocks these writes; the OS
  user is the layer that doesn't depend on parsing.
- DuckDB has no time limit of its own. `interrupt()` stopped a query after 1.00 s.
- SPEC.md, Security says the limits are set in the engine, not by inspecting the SQL text. The
  filter reads DuckDB's own parse, not the text, but it is still a check of the query. That is
  why the OS user matters on Linux.

Side effects: PIVOT is refused (DuckDB classifies it as MULTI, even inside a subquery).
DESCRIBE, SUMMARIZE and SHOW are SELECT and pass. `current_setting('allowed_directories')`
shows the server's data path (accepted).

**Rejected.** `allowed_paths` with one entry per partition file: it blocks new files, not the
replacement of a listed file.

## D11 - adele replaces `swiss_energy_data` (2026-11-13)

**Decision.** adele is the one data layer of the EnTr projects. Renaud drops the sibling project
`_EnTr/projects/swiss_energy_data/` (catalog as tables, `_asof` views, embargo, QA gate, source
YAMLs). What adele should keep from it is listed in `docs/from-swiss-energy-data.md`.

**Why.** The two projects overlapped on most of their scope (catalog, freshness, revisions,
checks against published figures), and both planned ENTSO-E next.

**Rejected.** adele serving `swiss_energy_data`'s tables to agents while it keeps the ingestion;
keeping both separate (one on the Mac for the swissgrid project, one on a server for the team).

## D12 - Published figures are checks, in `checks.yaml` (2026-11-13)

**Decision.** A dataset folder may hold `checks.yaml`: figures published by others (regulators,
exchanges, papers), each with a question, an SQL query, the expected value, a tolerance and the
source. The server runs them after each fetch, on `recheck` and on `adele-server check`. An error,
an empty result or a value outside the tolerance sets the status to failing and names the check.
The describe card shows one line about them, not the list.

**Why.** Renaud, 2026-11-13: "the figures ARE the QA". They test the stored numbers against
sources that don't go through adele. entsoe_day_ahead_prices has 82 (the 79 matches of
`qa/published_figures.md`, FR 2015 negative hours, CRE's rounded 96.9 and RTE's 513); all pass,
in about 2 s. Figures that differ for a known reason stay out and are explained in
`qa/published_figures.md`. A separate file, because 82 examples would put 82 queries in every
describe card: examples teach agents, checks test the data.

**Rejected.**

- `expected` and `source` on `adele.examples` (accepted first, changed for the size of the card).
- Agent QA with 3 runs per question. The 20 questions of `qa/` stay as a regression set, run
  once when the skill or the describe card changes. The figures don't test whether an agent finds
  the right SQL; those runs do.

## D13 - Each `fetch.py` declares its dependencies and runs through uv (2026-11-13)

**Decision.** A `fetch.py` with a PEP 723 block (`# /// script`) runs in a separate process:
the server writes a small runner with the block's dependencies plus pandas and pyarrow, starts it
with `uv run --no-project --script`, and reads the Parquet files that it writes to a temporary
folder. The time limit per fetch kills the process group. A `fetch.py` without the block runs in
a spawned child process, as before (the test datasets). The server no longer depends on
entsoe-py.

**Why.** WeatherNext 3 needs zarr, gcsfs and numcodecs; ENTSO-E needs entsoe-py. Each source's
libraries would otherwise land in the server's environment, and two sources may need versions
that conflict. A dataset folder that carries its own dependencies can also move to its own
repository later (packaging, TODOs.md). Cost, accepted by Renaud: the server needs uv, and access
to PyPI for the first run of each `fetch.py`. entsoe-py is pinned (0.8.1), because the fetch
calls two of its private functions.

**Rejected.** All source libraries as server dependencies.

## D14 - A dataset names its window column: `adele.window` (2026-11-13)

**Decision.** `adele.window` names the time column that the server uses for the fetch window,
for the [start, end) filter on staged rows and for the partitions. The default is
`delivery_start`. weathernext3 uses `init_time`. `adele list` shows the coverage of that column
when it is not `delivery_start`.

**Why.** A forecast run made at T covers T+1 h to T+48 h. With the window on the delivery time, a
run is read once for each day that it touches (2 to 3 times, 4.4 GB each), and the runs at the
edges of a backfill are cut. With the window on the init time, a run belongs to one window, is
read once and is stored whole. Accepted by Renaud on 2026-11-13. SPEC.md (Adding a dataset,
Storage) still says delivery time: paste-ready text in TODOs.md.

**Rejected.** A window on the delivery time for every dataset.

## D15 - Revision policy `none`: fetch only what isn't stored (2026-11-13)

**Decision.** A third policy next to `overwrite` and `append-only`: `revisions: none`, for
sources whose values never change once published (forecast runs). A fetch asks only for the
parts of the window that hold no stored value of the window column; a value counts as stored
only when every table of the dataset has rows for it. Each gap gets its own `fetch` call, and its
rows are cut to that gap. A fetched row whose key is stored with other values is an error, and
nothing is written. A backfill that stops can be run again and continues where it stopped.

**Why.** weathernext3 with `overwrite` re-read every run of its 12 h lookback at each hourly
refresh: about 22 GB per hour on steacher1, for runs that never change. With `none`, each run is
read once, and a run that appears late is still fetched while it is inside the lookback.
Accepted by Renaud on 2026-11-13.

**Known limit.** A run that never appears sets the status to failing only while it is inside the
lookback; after that the status clears. `stale` (TODOs.md) or a check on gaps would keep it
visible.

**Rejected.** `overwrite` with a short lookback (still re-reads), and passing the list of stored
values to `fetch` (changes the signature of every `fetch.py`).

## D16 - Partitions by month or by day, declared per dataset (2026-11-13)

**Decision.** `adele.partition: month | day`, default month, on the window column (D14).
weathernext3 uses day. A folder that holds files of the other size makes fetches and checks fail
until `adele-server repartition <id>` has rewritten it. The size is declared, not chosen by the
server, and day files are not compacted into months later.

**Why.** The merge rewrites a whole partition. A month of weathernext3 holds about 50 million
rows (730 MB), so each hourly run would rewrite 730 MB to add 70,000 rows; a day file is about
25 MB. A declared size is visible in git, and the skill `add-dataset` can choose it from the
backfill profile. Compaction would add a second layout and a step that rewrites checked data,
for almost no gain: DuckDB reads 365 files of 25 MB per year well. Accepted by Renaud on
2026-11-13.

**Rejected.** An automatic choice from the row count; compacting closed months.

## D17 - Instants: a table has `delivery_start` or `valid_at` (2026-11-13)

**Decision.** A table has exactly one time field. `delivery_start` marks the start of an interval
and comes with a resolution. `valid_at` marks an instant and has no resolution. Coverage uses
that field; `adele list` shows "instants" in the resolution column, and the card's conventions
say how to match an instant to an interval.

**Why.** WeatherNext 3 gives solar radiation as an amount over the hour that ends at the forecast
time (an interval), and cloud cover as the value at that time (an instant). Stored with
`delivery_start` and PT1H, a cloud value would read as a mean over the following hour, and a join
with hourly data would pair it with one hour although it is as close to the one before. A
different column name makes the difference visible to an agent. Accepted by Renaud on 2026-11-13
(clouds in `weathernext3.weather`).

**Rejected.** `delivery_start` with resolution PT0S (consistent, but a weight by duration gives
these rows zero weight); leaving instants out.

## D18 - Prepared for one repository per dataset (2026-11-13)

**Decision.** Every descriptor carries `adele.format: 1`; the server refuses a missing or
unknown format. `adele.secrets` lists the environment variables that a fetch gets; it gets
nothing else besides what uv and Python need (PATH, HOME, locale, certificates, proxies, `UV_*`,
`PYTHON*`, `XDG_*`). Both ways of running a fetch are subprocesses with that environment. The
server config lists `datasets_dirs`: an entry with a `datapackage.yaml` is one dataset (its folder
name is free), any other entry is a folder of datasets; a duplicate id is an error.
`datasets_dir` still works for one entry.

**Why.** Renaud, 2026-11-13: one repository per dataset, so that a dataset can have an owner
without access to the server code, can be shared outside the team, and the server repository
stays tidy. The split waits until the descriptor format has held for a week on steacher1 (POC
step 6): today it changed six times (D12 to D17), and with separate repositories each change
means one pull request per dataset. Then: `git subtree split` per dataset, a template repository,
and `adele-server sync` with pinned tags that only the admin moves. Code from other owners runs
on the server, so a fetch must not see the secrets of other datasets. The filter covers
environment variables only; files that the fetch user can read stay readable.

**Rejected.** Splitting now; datasets as Python packages (each fetch needs its own environment
anyway, D13).

## D19 - `adele.format` is named `adele.format_version` (2026-11-14)

**Decision.** The version of the descriptor format (D18) is `adele.format_version: 1`. The
server refuses a descriptor without it or with another version. Supersedes the name in D18.

**Why.** Renaud, 2026-11-14: `format` reads as a file format; the field holds a version.

## D20 - The query footer shows only the warnings marked for it (2026-11-14)

**Decision.** A warning in `adele.warnings` is either a string or a mapping
`{text: ..., footer: true}`. `describe` shows every warning. The footer under a query result
shows only the warnings marked `footer: true` (plus units, resolution and freshness, as before).
Not built yet (TODOs.md).

**Why.** The footer printed every warning under every result: 8 lines for weathernext3. An agent
reads `describe` once, but the footer each time; a long footer gets skipped. The dataset owner
decides which warnings matter for every query.

**Rejected.** All warnings in the footer (too long); one line "N warnings: run adele describe"
(the agent would have to act on it, and the warning that matters most is not in front of it).

## D21 - Expected spacing of the window column, checked for gaps (2026-11-14)

**Decision.** A dataset can declare the spacing of its window values (D14) in periods, in the
same shape as `resolution`:

    adele:
      expected_spacing:
        - {from: 2024-01-01, value: PT3H}   # weathernext3: 8 runs per day in 2024-2025
        - {from: 2026-01-01, value: PT1H}   # 24 runs per day from 2026

The server lists each expected value between the first `from` and the last stored value that no
table holds. Each one is a problem: the status is failing, and `describe` shows the count and
the ranges. Values before the first `from` are not checked. Not built yet (TODOs.md).

**Why.** With `revisions: none` (D15), a run that never appears fails the status only while it is
inside the lookback (12 h for weathernext3); then the status clears and the gap goes unnoticed.
A gap in forecast runs is the failure that `stale` doesn't catch: newer runs keep arriving.

**Rejected.** Waiting for `stale` (it sees only that nothing new arrives). Open: a run that the
source never publishes keeps the status failing; how to accept such a gap (a list of known gaps,
or a warning) is decided when it happens.

## D22 - A table may have no time column; each fetch replaces it whole (2026-11-14)

**Decision.** A table has `delivery_start`, or `valid_at` (D17), or no time column. A table
without one (a register of plants, a list of stations) is stored as one file. Each fetch returns
the whole table and the server replaces the stored one: a row that the source no longer delivers
goes. A fetch that returns no row for such a table is an error, and the stored table stays. The
window (D14), the partitions (D16) and `revisions: none` (D15) don't apply to such a table. In
place of a coverage, `adele list` and `describe` show its row count and the time of its last
change. Supersedes "exactly one time field" in D17. Not built yet (TODOs.md).

**Why.** Nobody decided against such tables: the rule of D17 came from the first two datasets,
which are time series, and D14 gave the time column three jobs (which rows a fetch brings, which
file a row goes into, the coverage). In the inventory of the two earlier projects
(docs/datasets-inventory.md), 18 of the 85 tables of sources have no time column, and most series
need one of them to explain their codes: 135 stations with position and altitude don't fit in
`categories`. Renaud, 2026-11-14: "we should definitely find a way to support any dataset that
does not have a time column"; the table mirrors the source (his answer "1 a").

**Rejected.** Rows that are only added or changed, never removed: the table would keep a plant
that left the register, with no mark. With `append-only` (POC 2), the history of a row that goes
can be kept.

## D23 - Nothing passes between two fetches for now; no journal, no SQLite file (2026-11-14)

**Decision.** `fetch(start, end)` gets the window and nothing else. adele keeps no journal of its
requests and no SQLite file per dataset. What a dataset holds (its coverage, the stored values of
the window column) is computed from the Parquet files when needed. A bookmark (a small JSON that
`fetch` gets and returns, kept in `state.json`) is added when the first dataset needs one.

**Why.** Renaud, 2026-11-14: "I'm not sold on using an SQLite per dataset", then "5 ok, fine
then. no sqlite for this". Between nothing and a bookmark, Claude recommended nothing; his answer
was "Use subagents for 1,3,4", which Claude read as an ok for this point (3). Measured the same
day: computing what is stored costs milliseconds (the footers of 120 day files with 201 million
rows: 11-19 ms; `count, min, max` over them: 68-108 ms). A subagent then looked for a dataset
that needs memory among the 83 of docs/datasets-inventory.md: none has an API with a cursor, none
serves only what changed since the last call, and no recorded limit is exceeded at the `every`
that the source needs. An answer of Swissgrid's TSI file is 120 bytes (median of about 2,300
downloads in the poller's log), so asking every minute without an ETag moves 0.17 MB a day.

**Limits.** Three cases will need a bookmark or a conditional request when they come. Swissgrid's
year files, if they are asked more often than once a day: EnergieUebersichtCH is 18 to 26 MB, and
the poller, which asked hourly, got "not modified" for 360 of 469 answers (1.1 GB saved in 20
days; read in its log by the subagent). The "recent" files of MeteoSwiss SMN, if they are asked
more often than once a day: 851 MB per fetch. The Open-Meteo backfill: its budget of calls
belongs to the source, not to one dataset, so a bookmark per dataset can't enforce it. The check
also found three defects of the server that memory would not solve (TODOs.md): a hole older than
the lookback is never fetched again, a backfill doesn't resume, and with `revisions: none` a run
stored in part counts as stored.

**Rejected.** A journal in a SQLite file per dataset (Claude's first recommendation): a second
store that can contradict the Parquet files, against a cost of computing that the measurements
don't show. A bookmark now: no dataset would use it.

## D24 - A query reads only the folders of the tables, and lists decide what is a read (2026-11-14)

**Decision.** Two changes to D10. (1) `allowed_directories` is one folder per table of the catalog
(`<data_dir>/<dataset>/<table>/`), not the data folder. (2) The filter on writes becomes a set of
allow-lists, all read from DuckDB's parser: one statement, of type SELECT or EXPLAIN; in its parse
tree (`json_serialize_sql`) only query nodes that read (SELECT, set operations, recursive CTE), at
any depth; table functions only from a list of 37 (`TABLE_FUNCTIONS` in `engine.py`). A SELECT
that DuckDB can't serialize is refused. For EXPLAIN, the server takes the text after the keyword,
checks it as a SELECT and adds `EXPLAIN` itself. So `EXPLAIN ANALYZE` and an EXPLAIN with options
are refused, and so are the table functions `query`, `query_table` and `histogram`, which
answered before. Built: `server/src/adele_server/engine.py`, 93 new tests.

**Why.** Found on 2026-11-14 with the real engine. Reads: the data folder also holds the query
log (`logs/queries.jsonl`, the SQL of every member), `alerts.log` and a `state.json` per dataset;
`read_json` returned the 36 lines of the log. Writes: the filter of D10 looked only at the type of
the statement. `EXPLAIN ANALYZE COPY ... TO` has the type EXPLAIN and runs the COPY. A COPY in a
CTE of a SELECT has the type SELECT. Three table functions run SQL that they get as data (`query`,
`json_execute_serialized_sql`, `destroy_external_resource`). Each of these added or replaced a
partition of a table (synthetic data: 96 --> 97 rows, then 2). DuckDB 2.0.0 has no setting that
makes a folder read-only. Renaud, 2026-11-14: to "Apply the fix of the readable folders now?" he
answered "Use subagents for 1,3,4", which Claude read as a yes. Claude added the guard on writes
the same day without his answer; he decides whether it stays as it is.

**Limits.** Scalar functions are on no list (814 in duckdb 2.0.0; none was found that writes).
The check relies on `json_serialize_sql` showing every node. A query can still read every file
inside the folder of a table (the temporary files of a merge hold rows of the same table) and
DuckDB's own `.tmp` folder. The layer that doesn't depend on parsing is the operating system: on
the Linux server the query process runs as a user for whom the data folder is read-only
(`deploy/adele-server.service`, a draft that was never tried).

**Rejected.** Moving the logs out of the data folder as the only fix: the state files stay
readable. A list of forbidden words (ANALYZE, COPY): a later DuckDB can add a construct that
writes, and an allow-list refuses what it doesn't hold.

## D25 - A scheduled run starts at the last run that succeeded; a failing stretch is given up after one lookback (2026-11-15)

**Decision.** Four rules for the window of a scheduled run (`fetch --due`, or `fetch <dataset>`
without `--start` and `--end`):

1. The window is [last - lookback, now + horizon), where last is the time of the last scheduled
   run that succeeded (`last_scheduled_at` in `state.json`), and `now` on the first run.
2. A new optional key, `adele.refresh.max_window`: a window longer than it is fetched in pieces
   of that length, oldest first, each one merged before the next starts. Every piece is
   attempted, and the run succeeds only if all of them do.
3. A run that fails keeps last. Once the runs have failed for longer than the lookback
   (`failing_since`), the window is [now - lookback, now + horizon) until a run succeeds, and the
   part that is given up, [last - lookback, now - lookback), is written once to `alerts.log`.
4. A fetch with `--start` or `--end` changes nothing. A backfill sets last to the time at which
   it started, when it reaches the present, starts at or before last - lookback, and has at least
   one window that succeeded. It lists its failed windows.

weathernext3 declares `max_window: PT1H`. Built: `server/src/adele_server/ingest.py`
(`scheduled_window`, `scheduled_fetch`, `backfill`), `catalog.py`, `state.py`, `cli.py`;
`server/tests/test_catch_up.py` (32 tests).

**Why.** The window was always [now - lookback, now + horizon). After a stop longer than the
lookback, the time in between was never fetched again and nothing reported it. A long backfill
is such a stop: it ends at the time at which it was started, and the first scheduled run after
it starts at now - lookback (weathernext3: a lookback of 12 h, a backfill of days). Found by a
subagent on 2026-11-14. Renaud, to "The hole older than the lookback: fix now?": "4 yes. put this
decision also in SPEC.md"; to `max_window`: "3 ok". Rule 3 was added by Claude after the first
build: with rules 1 and 2 alone, a failure that never ends stops a dataset for good. weathernext3
has that case: its `fetch.py` raises for a run without `success` marker from 10 h after its init.
Before, that run left the lookback 2 h later. One lookback of retries is what a failure inside
the usual window got before; it now also holds for the time of a stop. Simulated on a synthetic
dataset: with `max_window: PT1H`, a run that is never written fails 13 hourly runs and only that
run is missing; without the key, nothing is stored during those 13 h and 9 more runs are lost.

**Limits.** A source that fails for longer than the lookback still leaves a hole, as before; the
alert log now names it, and D21 would report it. A source that serves only its latest values
brings nothing for the time of a stop. A usual run of weathernext3 is now 14 pieces; their cost
is not measured, and no real fetch ran with this code yet. An unknown key under `adele.refresh`
is not refused, so a misspelt `max_window` is ignored.

**Rejected.** The last stored value as the start (a source that lags or has stopped would make
every window grow). `last_fetched_at` as the start (each window of a backfill sets it, also one
of 2015). Retrying a failing stretch for ever (stops the dataset). Filling the time of a stop
once, without retry (one network error in a catch-up of 180 pieces leaves a hole).

## D26 - Calendar periods: a date column named after its period, and a time zone per table (2026-11-15)

**Decision.** A table whose rows cover a calendar day, month or year in local time has a date
column in place of `delivery_start`:

- The column is `delivery_date` for a day, `delivery_month` for a month, `delivery_year` for a
  year. All three are of type date. A month and a year are stored as their first day, and the
  server checks that.
- The table declares its zone: `timezone` in its `adele:` block, an IANA name (Europe/Zurich) or
  `UTC`. An abbreviation such as `CET` is refused: DuckDB applies summer time to it.
- Such a table has no `resolution`: the name of the column gives it.
- When the source does not state the zone of its days, the author writes the most likely zone,
  and the description of the column says that it is assumed.
- A fetch keeps a period when it overlaps the window [start, end), not only when its first
  instant falls inside.
- `describe` prints the zone and the expression that joins the table with a table in UTC,
  together with the plain filter that lets DuckDB skip partitions.
- A day of UTC is a fixed duration: such a table keeps `delivery_start` and `P1D`.

With D22, this supersedes "exactly one of `delivery_start` and `valid_at`" in D17. Not built yet
(TODOs.md). A prerequisite: the `adele:` block per table, because `resolution`, `window` and
`partition` are per dataset today.

**Why.** A day of Europe/Zurich lasts 23 to 25 hours and a month has no fixed duration, so
"a start in UTC plus a resolution" is wrong for them: on 2026-03-29, `delivery_start + INTERVAL 1
DAY` joins 96 quarter-hours where the day has 92. Renaud chose the date column on 2026-11-14
("2 c"), over a start with an end and over all three columns. A subagent then tested the details
against the server code, the 9 datasets of docs/datasets-inventory.md with such periods and
duckdb 2.0.0. With one name for the three periods, a join of a table by day with a table by month
returns 12 rows a year instead of 365, without an error; with three names the same join fails.
The catalog refuses `P1M` and `P1Y` on purpose (their length varies), hence no `resolution`. A
table by month with a lookback of 3 days stored 0 rows with the status ok, hence the rule on the
window. Renaud, 2026-11-15: "1 ok" to the three names; on a zone that the source does not state:
"a. write it down, so this is known".

**Limits.** Not covered: a period with its own end (ENTSO-E outages; Swissgrid's reserve
auctions, whose products cover a week, a day or a block of 4 hours) and a state at a date (the
BFE Energie Reporter gives the capacity on the last day of each month). They wait for the first
dataset that needs them. The join needs the zone: a cast without it gives 96 quarter-hours on
every day, without an error, and puts 2,300 of the 35,040 quarter-hours of 2026 on the wrong day.
A DuckDB on a laptop uses the zone of the machine, so a local copy can answer differently from
the server.

**Rejected.** A start and an end (a filter by date then reads the wrong day). All three columns
(Claude's recommendation). One name, `delivery_date`, for the three periods (Claude's first
proposal). A value `unknown` for the zone (`describe` could then print no join).

## D27 - One systemd timer and one service per dataset (2026-11-15)

**Decision.** On the Linux server each dataset has its own pair of units, instances of two
templates: `adele-fetch@<id>.timer` ticks every minute and starts `adele-fetch@<id>.service`,
which runs `adele-server fetch <id> --if-due`. The schedule stays in the descriptor: the timer
only gives the tick. With it:

- `fetch <id> --if-due` exits at once, without output, when the dataset is not due. That path
  reads only the state file and the `every` of that one descriptor.
- A dataset is due when `now` lies in a later period of `every` than its last attempt. The
  periods are counted on the clock, in UTC. A last attempt later than `now` counts as due.
- A new optional key, `adele.refresh.timeout`: the limit of one call of `fetch.py` is the smaller
  of it and the server's `fetch_timeout_s`. An unknown key under `adele.refresh` is an error.
- Each service keeps the six sandbox settings, and reads the secrets of its dataset from
  `/etc/adele/env.d/<id>` (root only). There is no shared file of secrets any more.
- A backfill holds the lock of its dataset from its first window to its final checks.
- One invalid descriptor no longer stops the fetch of the other datasets. `validate` and `serve`
  stay strict.

Built: `deploy/adele-fetch@.service`, `deploy/adele-fetch@.timer` (drafts, not tried on a
server), `server/src/adele_server/` (`cli.py`, `state.py`, `catalog.py`, `ingest.py`),
`server/tests/test_fetch_command.py`. On the Mac, `fetch --due` from cron stays possible.

**Why.** Swissgrid's 5-minute file keeps a value for 15 minutes, and a fetch of weathernext3
lasts minutes. With one timer and one service for all datasets, a prototype on the Mac fetched
the dataset due every minute in 4 of 14 minutes (longest gap 360 s): systemd does not start a
unit again while it runs, and one run fetched the datasets one after the other. Renaud,
2026-11-14: "I insist on sandbox settings", which rules out a plain cron line; 2026-11-15: "3 B"
to one timer per dataset. A subagent compared the candidates with prototypes (each fetched in 14
of 14 minutes, about 0.7 s after the tick, no double fetch), and the claims about systemd were
tested in a container (`deploy/scheduling-poc/`, 27 checks passed): a unit that runs is not
started twice, the sandbox settings hold for children and grandchildren, a file of secrets that
only root reads reaches the unit, and the unit can't read the file. The rule on periods: with
"time since the last attempt", an attempt stamped 12:00:01 made the tick of 12:01:00 "not due".
The cost of a tick that fetches nothing went from 0.36 s to 0.04 s of CPU (measured, one
dataset). The lock: with a tick every minute, a scheduled run would have started between two
windows of a long backfill; the next window then failed on the lock and ended the backfill.

**Limits.** Nothing ran on steacher1. Root runs one command per dataset (`systemctl enable --now
adele-fetch@<id>.timer`). All timers fire in the same second. A credential that is a file (the
Google credentials) stays readable by every fetch.

**Rejected.** A scheduler that stays running (best numbers in the prototype, but a restart or a
crash stops every fetch in progress: tested, and `KillMode=mixed` does not wait for them; one
journal for all datasets). A tick that starts one unit per due dataset (needs a polkit rule, or
a line that runs as root). Two lanes, fast and slow (the slow lane lost 11 of 14 ticks in the
prototype). cron with `systemd-run` (the sandbox settings would sit in a cron line).

## D28 - `EXPLAIN ANALYZE` of a checked SELECT is allowed (2026-11-15)

**Decision.** A query may be `EXPLAIN ANALYZE <select>`, when the SELECT passes the checks of
D24. The server takes the text after the two words, checks it, and adds `EXPLAIN ANALYZE`
itself. EXPLAIN with options in parentheses stays refused, and so does the spelling `ANALYSE`.
This changes one sentence of D24. Built: `server/src/adele_server/engine.py`.

**Why.** D24 refused `EXPLAIN ANALYZE` because it runs the statement that follows, a COPY
included. Once that statement is a SELECT that only reads, running it is what every query does.
It gives agents the run times of their own queries back. Renaud, 2026-11-15: "2 b", among (a)
the guard as built, (b) with `EXPLAIN ANALYZE` back, (c) a short list of forbidden functions in
place of the list of allowed ones.

**Rejected.** (c): a function that a later DuckDB adds, and that runs SQL from a string, would
pass unchecked.

## D29 - A query is one SELECT: no EXPLAIN (2026-11-15)

**Decision.** The server runs one statement of type SELECT and nothing else. `EXPLAIN` and
`EXPLAIN ANALYZE` are refused, like every other statement. Supersedes D28, and the sentence on
EXPLAIN in D24. Built: `server/src/adele_server/engine.py` (the function `explained` and the
branch for EXPLAIN are removed), `server/tests/test_engine.py`.

**Why.** Renaud, 2026-11-15, an hour after D28: "if we could disallow all `explain` or `explain
analyze`, that would be good enough", then "EXPLAIN: disallow, then". The handling of EXPLAIN was
the most delicate part of the guard against writes: DuckDB gives no parse tree for an EXPLAIN, so
it was the one place where the server took a query apart with the tokenizer and put it together
again. Without it the guard has two parts, the check of the parse tree and the list of table
functions. Nobody used EXPLAIN: 0 of the 36 queries of the real log, and neither the skill nor
the client mentions it.

**Limits.** An agent can't see the plan or the run times of a query. A query that is too slow
gets the message of the time limit, which says to aggregate or to narrow the filter.

## D31 - An example can name a published figure; at most five examples (2026-11-15)

**Decision.** An entry of `adele.examples` is either a question with its SQL (and `verified_at`
once a person has confirmed the result), or `check: <name>`, the name of a check of
`checks.yaml`. For the second, `describe` prints the check's question and SQL, and the published
figure with its source (`published_figure: 513 (RTE, ...)`); when the check fails, the line says
that the data doesn't reproduce the figure now. Such an example isn't run a second time: its
check runs after each fetch. A dataset has at most five examples, and `describe` prints them
all (it printed the first three). `entsoe_day_ahead_prices` has its example plus four checks,
one per trap: a mean weighted by duration across 2025-10-01 (`de_2025_mean`), negative hours as
a sum of durations (`de_2024_negative_hours`), RTE's hours of quarter-hours
(`fr_2025_negative_hours_hourly_mean`), days cut in Europe/Zurich
(`ch_2022_mean_of_daily_means`). Built: `server/src/adele_server/catalog.py`, `checks.py`,
`render.py`, `server/tests/test_published_checks.py`. Numbered D31 because the branch `wp3`
holds D30.

**Why.** Renaud, 2026-11-15: "option b, have the one example plus 4 from checks.yaml". The 82
checks use 7 kinds of query, and the single example of the card showed none of the traps that
the warnings name: its plain `avg(price)` is right for one local day, and wrong when an agent
reuses it over a period that spans the change of resolution. An example taken from a check
keeps its SQL in one place, is tested against a figure published by others after each fetch,
and gives the agent a known answer. This partly reverses D12, which refused `expected` and
`source` on examples for the size of the card: with five examples at most, the card grows by
four lines.

**Rejected.** (a) Copying checks into `adele.examples`: the same SQL in two files. (c) A
command that returns more examples on request (`adele examples <id> --search ...`): agents
follow the steps of the skill and seldom make optional calls, and for this dataset it would
return near-copies of the same seven queries. To reconsider if a run of the questions of `qa/`
shows an agent missing a trap that a check would have taught.
