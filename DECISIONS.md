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
