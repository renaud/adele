# Decisions

Implementation choices and why we made them. SPEC.md says what adele does. This file says how
we build it, why, and which alternatives we rejected.

Open questions sit at the top. When one is answered, it becomes a new Dn entry and leaves the
list.

Entries are append-only. To reverse a decision, add a new entry that supersedes it, and add
"Superseded by Dn" to the old one. Don't change the old entry otherwise.

## Open

- **Repo layout for the two distributions (D3).** Proposal: one repo, two folders (`client/`,
  `server/`), each an independent uv project with its own `pyproject.toml`, `uv.lock` and
  `.venv`. Alternatives: a uv workspace (one lockfile and one `.venv` shared by both), or two
  GitHub repos.
- **Library API (D4).** Function names, and what each function returns. `list` can't be a
  function name: it would shadow Python's built-in `list` (e.g. `adele.datasets()` instead).

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
