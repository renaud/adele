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
