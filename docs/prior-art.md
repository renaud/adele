# Prior art for Adele

Search run on 2026-11-13: 20 agents, one per angle, then a critic and 5 gap-filling agents.
They reported 213 entries (with duplicates across angles).

**Caveat.** The claims come from pages that the agents read. No second verification pass was
run. Check a project before depending on it. Each entry in `prior-art-results.json` has a
`status` field that says what was verified and what was not.

**Result.** No project does what Adele does as a whole. One comes very close in design (PUDL
with its agent skills), and most parts exist as components.

## Closest in design

| Project | Why it matters |
|---|---|
| [PUDL](https://docs.catalyst.coop/pudl/en/latest/data_access.html) + [catalyst-cooperative/agent-skills](https://github.com/catalyst-cooperative/agent-skills) | US energy data with the same stack: Parquet, DuckDB, Frictionless Data Package v2, an agent skill, no MCP. Their generic `datapackage` skill may work unchanged on Adele descriptors. Read this first. |
| [eptr2](https://github.com/Tideseed/eptr2) | Turkish market client with the closest CLI: `list`, `search`, `describe`, `schema`, `install-skills`. No store, no freshness. |
| [Grid Status](https://docs.gridstatus.io/developers/api-reference/dataset-metadata) | Commercial, US. Best model for dataset metadata and for [publish time queries](https://docs.gridstatus.io/developers/concepts/publish-time.md). |
| [hsilvosa/entsoe-observatory](https://github.com/hsilvosa/entsoe-observatory) | One person's ENTSO-E pipeline to Parquet and DuckDB, with revisions and a snapshot cutoff. Only two data items. |
| [Open Energy Data Server](https://github.com/NOWUM/open-energy-data-server) | Self-hosted crawlers for ENTSO-E, JAO, SMARD into TimescaleDB. No metadata per dataset. |
| [Dinobase](https://github.com/DinobaseHQ/dinobase), Agnes (Keboola) | Generic "sync to Parquet, DuckDB, CLI for agents". Agnes reportedly has the same manifest-based `pull`, but its repo returned 404. |

## Candidates for reuse

- **Fetchers**: [entsoe-py](https://github.com/EnergieID/entsoe-py) (including its client for
  the ENTSO-E File Library), [jao-py](https://github.com/fboerman/jao-py).
- **Ingestion**: [dlt](https://github.com/dlt-hub/dlt) as a library (incremental state, schema
  contracts that block a load on drift), run by systemd timers. No orchestrator is justified
  for 12 sources. Note: dlt's Parquet destination partitions by load time, so Adele must write
  the partitions by delivery month itself (DuckDB `COPY ... PARTITION_BY`).
- **Catalog**: [frictionless-py](https://github.com/frictionlessdata/frictionless-py), with key
  names borrowed from [oemetadata](https://github.com/OpenEnergyPlatform/oemetadata)
  (energy-specific, also based on Frictionless).
- **Serving**: static Parquet behind Caddy or nginx, read by DuckDB `httpfs`;
  [Quack](https://duckdb.org/docs/2.0/quack/overview.html) (DuckDB's own client-server
  protocol, with per-user tokens) for remote SQL; [DuckLake](https://ducklake.select/faq) as an
  optional layer.
- **Agent side**: [duckdb-skills](https://github.com/duckdb/duckdb-skills) for work on pulled
  data, Anthropic's [skill authoring guide](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices).
- **Monitoring**: [Healthchecks](https://github.com/healthchecks/healthchecks), because the
  server cannot email about its own death.

## Best sources of ideas, per spec section

- **Bitemporal**: [ALFRED](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
  (vintages), [timedb](https://github.com/rebase-energy/timedb) (vocabulary: valid_time,
  knowledge_time, change_time), Energy Quantified "instances", the
  [SDMX REST API](https://github.com/sdmx-twg/sdmx-rest/blob/master/doc/data.md) (`asOf`,
  `updatedAfter`), Elexon (queries by publish time).
- **Self-description**: [ERDDAP](https://github.com/ERDDAP/erddap) (the catalog is itself a
  queryable table, with a staleness rule per dataset),
  [ODCS](https://bitol-io.github.io/open-data-contract-standard/latest/) and dbt (freshness
  thresholds), [OWID ETL](https://github.com/owid/etl).
- **Agent surface**: [MotherDuck agent-skills](https://github.com/motherduckdb/agent-skills),
  [lacon](https://github.com/andrii-su/lacon) (row caps with a visible "shown N of M"),
  Vercel's ["we removed 80% of our tools"](https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools).
- **Too heavy or dead**: DataHub, OpenMetadata, Unity Catalog, Airflow, Great Expectations.
  Amundsen and Vanna are archived. The energy MCP servers are almost all thin wrappers around
  live APIs.

## Challenges to the spec

Raised independently by several agents.

1. **`fetched_at` is not knowledge time.** Store the publication time of the source too
   (ENTSO-E gives one), and say which one `as_of` uses. A fixed `as_of` also does not cover
   backtests, which need a cutoff relative to each delivery time (Grid Status does this).
   Flag history that was backfilled (knowledge time not observed).
2. **Units are not enough per field.** Also needed: aggregation (mean MW or MWh per interval),
   sign convention, currency, code list. oemetadata already names `alignment` and
   `aggregationType`.
3. **Resolution and zones change over time.** Day-ahead prices went from 60 to 15 minutes on
   2025-10-01, and DE_AT_LU became DE_LU. A reference table of zones with validity dates does
   not exist anywhere and must be authored. Daily products need the time zone that defines the
   day.
4. **Licences are per dataset and several are not open.** JAO allows internal use only.
   ENTSO-E prices and load are reportedly not on its free re-use list (the primary page
   returned 403, so this is unconfirmed). Add licence, attribution and redistribution scope to
   each descriptor.
5. **Remote `query` needs hardening in the engine**, not by filtering SQL text: read-only mode
   still lets a query read local files. See
   [Securing DuckDB](https://duckdb.org/docs/2.0/operations_manual/securing_duckdb/overview.html).
   `pull` plus local DuckDB removes most of this risk.
6. **Smaller additions**: `adele search`, explicit row caps with a truncation marker, a status
   for "fetcher never ran", a query log, usage warnings per dataset, distinct values for
   categorical columns next to the 5 sample rows, a hash per partition in the manifest for
   `pull`.
7. **CLI and skill over MCP is supported.** MotherDuck, DataHub, Malloy and Rill started with
   MCP and added skills later. Benchmarks find roughly equal correctness, so MCP is only
   needed for chat clients without a shell.
8. **Evaluate the skill.** No benchmark measures units or grain. Build a small set of
   questions where the wrong time zone, unit, grain or revision gives a different number.

## Appendix: all entries per angle

Verdicts are those of the agents. Takeaways and verification status of each entry are in `prior-art-results.json`.

### energy-open-data-platforms

Closest prior art is PUDL: same stack (Parquet + DuckDB + Frictionless Data Package v2 + an agent skill, no MCP). Read its two skills before writing Adele's: they query datapackage.json with jq and never load it whole. No public energy platform that I found does bitemporal as_of over normalized Parquet. Elexon is the only one that exposes publish time as a first-class query axis, so Adele's knowledge-time axis is a real differentiator. Challenges to the spec: (1) borrow oemetadata's timeseries keys (resolutionValue/Unit, alignment, aggregationType) for the adele: block. The spec lacks alignment and aggregation type. (2) Add per-dataset and per-field usage warnings and a license with redistribution limits. Energy-Charts price data for many zones is restricted to internal use. (3) Add a "latest publish time per dataset" endpoint (Elexon) to make freshness cheap. (4) Consider nightly/stable/vDATE path aliases (PUDL) only if reproducibility matters. I found no ready-made self-hosted ENTSO-E pipeline with Parquet and DuckDB.

| Project | Verdict | What |
|---|---|---|
| [PUDL (Catalyst Cooperative)](https://docs.catalyst.coop/pudl/en/latest/data_access.html) | inspiration | Open pipeline that fetches, cleans and republishes US energy data (EIA, FERC, EPA) as Parquet files plus a single DuckDB database, with a Frictionless Data Package v2 descriptor. |
| [Catalyst Cooperative agent-skills (pudl + datapackage skills)](https://github.com/catalyst-cooperative/agent-skills) | reuse-as-component | Two agent skills: a generic 'datapackage' skill that teaches an agent to explore any Frictionless descriptor, and a 'pudl' skill built on top of it for PUDL data. |
| [oemetadata (Open Energy Platform metadata standard)](https://github.com/OpenEnergyPlatform/oemetadata) | inspiration | JSON metadata standard for energy datasets, based on Frictionless Data Package and FAIR, used by the Open Energy Platform. |
| [Elexon Insights Solution API (BMRS)](https://developer.data.elexon.co.uk) | inspiration | Public API of the GB balancing and settlement data, replacing the legacy BMRS. |
| [Energi Data Service (Energinet, Denmark)](https://www.energidataservice.dk/guides/api-guides) | inspiration | Danish TSO's open data API: one generic endpoint per dataset plus a metadata endpoint. |
| [Energy-Charts API (Fraunhofer ISE)](https://api.energy-charts.info/) | inspiration | JSON API for European generation, load, prices, cross-border flows and forecasts, derived from ENTSO-E, SMARD and exchanges. |
| [Electricity Maps parsers (electricitymaps-contrib)](https://github.com/electricitymaps/electricitymaps-contrib) | inspiration | Open repository of Python parsers that fetch and standardize production, consumption, price and exchange data per zone, worldwide. |
| [Open Power System Data (time series package)](https://data.open-power-system-data.org/time_series/) | inspiration | Academic project that compiled European load, wind, solar and price time series into versioned data packages. |
| [SMARD (Bundesnetzagentur) and the bundesAPI description](https://github.com/bundesAPI/smard-api) | inspiration | German regulator's market data portal; its undocumented JSON backend is described by the community project bundesAPI. |
| [Ember (API and European wholesale price dataset)](https://ember-energy.org/data/api) | inspiration | Think tank that publishes cleaned electricity data: an API for yearly and monthly generation, demand, emissions, and CSV files of European day-ahead prices. |
| [Swissgrid grid data files](https://www.swissgrid.ch/en/home/customers/topics/energy-data-ch.html) | inspiration | Swiss TSO publishes downloadable files: yearly 'Energy Statistic Switzerland' workbooks (15-minute data), Control Area Balance, Total System Imbalance. |
| [BFE energiedashboard.ch datasets on opendata.swiss and the SFOE data catalogue](https://github.com/SFOE/open_energy_data) | inspiration | The Swiss Federal Office of Energy publishes the CSV files behind its energy dashboard on opendata.swiss (CKAN, DCAT-AP CH), and maintains a markdown catalogue of about 40 Swiss open energy datasets. |
| [gridstatus (open-source library) and Grid Status hosted API](https://github.com/gridstatus/gridstatus) | inspiration | Python library that fetches market data from North American ISOs and the EIA, with a separate commercial hosted API. |
| [Open Electricity (formerly OpenNEM, Australia)](https://docs.openelectricity.org.au/introduction) | inspiration | Open platform for Australian electricity market data with an API key per user and Python and TypeScript SDKs. |
| [Open Energy Platform (OEP)](https://openenergyplatform.org/about/) | not-relevant | German research platform with a community database for energy scenario and model data, a REST API and the oemetadata standard. |

### energy-python-clients

No library found is reusable as a whole: they are clients of one source (entsoe-py, jao-py: reuse as fetchers) or hosted services (gridstatus.io, Energy Quantified). None combines self-hosted Parquet, a descriptor per dataset and an agent skill.

Conventions diverge, which confirms Adele's UTC and half-open rule: entsoe-py returns local time of the zone and keeps the row that starts at `end` (inclusive); gridstatus.io is UTC and end-exclusive; JAO and Elexon key data by local business day or settlement period.

Challenges to the spec:
1. Resolution is not constant per dataset (day-ahead prices: 60 min --> 15 min on 2025-10-01). Store delivery_end per row, or resolution with validity periods.
2. Bidding zone codes have validity periods (DE_AT_LU --> DE_LU). Needs a zone reference table (name, EIC, tz, valid_from/to).
3. Daily and monthly resolutions need a time zone (EQ: resolution = frequency + tz).
4. Source publish time ("issued") differs from fetched_at; gridstatus.io exposes publish_time_column in metadata.
5. Outage-like "period" data does not fit a fixed grain.

| Project | Verdict | What |
|---|---|---|
| [entsoe-py (EnergieID)](https://github.com/EnergieID/entsoe-py) | reuse-as-component | Python client for the ENTSO-E Transparency Platform REST API, with a raw client (XML) and a pandas client that parses to Series/DataFrame. |
| [gridstatus.io hosted API + gridstatusio client](https://docs.gridstatus.io/developers/api-reference/dataset-metadata) | inspiration | Commercial hosted API (free tier) over North American ISO data, with a dataset catalog, a metadata endpoint per dataset and a Python client (gridstatusio, BSD-3). |
| [gridstatus (open-source library)](https://github.com/gridstatus/gridstatus) | inspiration | Python library with one class per North American ISO (CAISO, ERCOT, PJM, MISO, SPP, NYISO, ISO-NE, IESO, AESO) plus EIA, returning pandas DataFrames. |
| [Energy Quantified Python client](https://energyquantified-python.readthedocs.io/en/latest/userguide/terminology.html) | inspiration | Open-source client (Apache 2.0) for the commercial Energy Quantified API. Its data model for 'curves' is the most explicit vocabulary found for market time series. |
| [ClariGrid](https://github.com/AlexanderHoogsteyn/ClariGrid) | inspiration | New Python SDK that normalises European and US energy data from many public providers (Energy-Charts, SMARD, Elia, ENTSO-E, EIA, CAISO, NYISO, weather sources) to pandas DataFrames, with a local Parquet cache. |
| [PUDL (Catalyst Cooperative)](https://github.com/catalyst-cooperative/pudl) | inspiration | Pipeline that cleans and integrates US public energy datasets (EIA, FERC, EPA) and publishes them as Parquet files and a DuckDB database, rebuilt nightly. |
| [jao-py](https://github.com/fboerman/jao-py) | reuse-as-component | Python client for the JAO (Joint Allocation Office) publication tools: flow-based capacity data for Core day-ahead, Core intraday, Nordic and Italy North. |
| [Open Power System Data - time series package](https://data.open-power-system-data.org/time_series/) | inspiration | Research data package with European load, wind, solar and price time series, published as CSV, XLSX and SQLite with a Frictionless datapackage.json. |
| [Open Energy Data Server (NOWUM)](https://github.com/NOWUM/open-energy-data-server) | inspiration | Self-hosted set of crawlers that fill a shared institute database (TimescaleDB/PostgreSQL) with ENTSO-E, ENTSO-G, JAO, SMARD, ERA5, Marktstammdatenregister and other data. |
| [nexa-marketdata (phasenexa)](https://github.com/phasenexa/nexa-marketdata) | inspiration | Alpha Python client that aims to unify Nord Pool, EPEX SPOT, ENTSO-E and EEX behind one interface. |
| [Open-Meteo API](https://open-meteo.com/en/docs) | inspiration | Weather forecast and history API (self-hostable), commonly used for weather features of power models. |
| [Volue Insight: wapi-python --> volue-insight-timeseries](https://github.com/volueinsight/wapi-python) | not-relevant | Python client for the commercial Volue (ex Wattsight) time series API. |
| [Elexonpy (Open Climate Fix)](https://github.com/openclimatefix/Elexonpy) | not-relevant | Python client for the Elexon Insights API (GB market), generated with Swagger Codegen. |
| [entsoe-apy](https://github.com/berrij/entsoe-apy) | not-relevant | Alternative ENTSO-E Transparency client that mirrors the API parameters closely. |

### energy-mcp-and-agents

No serious project in this angle does what Adele plans (local Parquet sync, bitemporal as_of, schema-drift alerts). Almost all are thin MCP wrappers: one tool per upstream endpoint, live calls, units only in tool descriptions, no coverage or freshness metadata. Vendors named in the brief: only Modo Energy (official MCP, June 2026) and Kpler (not power) verified. Nothing found for Montel, Volue, Energy Quantified, Amperon; Enverus, gridstatus and Electricity Maps only have third-party wrappers. Best ideas to copy: (1) eptr2's CLI `list | search | describe | schema` plus bundled skills and `install-skills` (closest match to Adele's CLI + skill design, confirms the no-MCP choice); (2) Grid Status dataset metadata fields (publication_frequency, publish_time_column, primary_key_columns, status enum); (3) cyanheads EIA server: browse/describe/search/query plus DuckDB staging, errors with a recovery hint; (4) Energy Aspects `release_date` (as_of) and schema resources. Challenge to the spec: add `adele search`, and a machine-readable full schema dump.

| Project | Verdict | What |
|---|---|---|
| [eptr2 (Tideseed / Robokami)](https://github.com/Tideseed/eptr2) | inspiration | Unofficial Python client for the Turkish EPIAS transparency platform (234 endpoints) that ships a CLI, an MCP server with 18 tools, 7 bundled agent skills and an AGENTS.md. |
| [Grid Status (gridstatus.io) API and docs](https://docs.gridstatus.io/llms.txt) | inspiration | Commercial hosted API over 455+ normalized datasets from US ISOs, with a dataset catalog and a per-dataset metadata endpoint. No official MCP server found. |
| [cyanheads/eia-energy-mcp-server](https://glama.ai/mcp/servers/cyanheads/eia-energy-mcp-server) | inspiration | Open-source MCP server over the US EIA API v2 with discovery tools and a DuckDB staging area where the agent runs SQL on fetched results. |
| [Energy Aspects MCP](https://mcp.energyaspects.com/doc) | inspiration | Official remote MCP server of a commercial commodity research firm: 4 read-only tools over research publications, live posts and time series. |
| [Modo Energy MCP](https://modoenergy.com/research/ai-academy-use-modo-energy-in-your-own-ai-tools) | inspiration | Official remote MCP server of Modo Energy (battery storage and power market benchmarks, forecasts, research), read-only. |
| [Luminus (luminus-mcp)](https://github.com/arefiva/luminus) | inspiration | Open-source MCP server (npm) that wraps about 25 public European and UK energy sources (ENTSO-E, ENTSOG, Elexon BMRS, energy-charts, SMARD, Nordpool, RTE, Fingrid, Terna, REE ESIOS, JAO ...) as 48 to 69 tools. |
| [gridstatus-api skill (MisterClean/claude-plugins)](https://github.com/MisterClean/claude-plugins/tree/main/skills/gridstatus-api) | inspiration | Community Claude Code skill (plugin) that teaches an agent to query the GridStatus.io API with curl or the Python SDK. |
| [S&P Global Energy MCP (on Databricks Genie)](https://www.remio.ai/ko/post/s-and-p-global-energy-conversational-data-replaces-custom-ai-access-layers-ko) | inspiration | S&P Global Energy exposes commodity datasets (including power) to agents through managed MCP servers in front of Databricks Genie spaces (natural language --> SQL). |
| [Pipeworx ENTSO-E / Elexon / Energy-Charts / GridStatus MCP packs](https://github.com/pipeworx-io/mcp-entso-e) | not-relevant | Thin MCP packs from a hosted gateway ("1864+ live data sources") that forward calls to upstream public APIs; the ENTSO-E pack has 5 tools and parses the XML to JSON. |
| [Kpler MCP](https://www.executivebiz.com/articles/kpler-mcp-maritime-supply-chain-intelligence) | not-relevant | Official MCP layer from Kpler that links LLM clients (ChatGPT, Claude) to its proprietary commodity and maritime datasets. |
| [Vinkius hosted wrappers (GridStatus, Enverus, Electricity Maps, ENTSO-E, EIA)](https://vinkius.com/apps/gridstatus-mcp/with/openai-agents-sdk) | not-relevant | Commercial MCP hosting directory that sells third-party wrappers around energy APIs (GridStatus 12 tools, Enverus 10 tools, Electricity Maps 3 tools), with the user's own API key. |

### duckdb-mcp-agent-data

All projects converge on three steps: list --> describe --> free SQL, with the SQL engine read-only by default and results capped (MotherDuck local: 1024 rows / 50,000 chars; lacon: 50 rows; cyanheads: 10,000 rows). This matches adele list | describe | query. Two vendors that started with MCP later added SKILL.md catalogs (MotherDuck, Data Commons), and Hugging Face and DuckDB ship CLI + skill. This supports the CLI + skill choice. Challenges to the spec: (1) add explicit row and character caps and a visible truncation marker to `adele query`; (2) add a "describe before query" rule and DuckDB dialect hints to the skill; (3) consider a server-side "guide" text per dataset (domain notes), as MotherDuck Guides and boettiger-lab prompt files do; (4) restrict the server DuckDB (no ATTACH, INSTALL, SET, local files). No project found covers freshness, ETA of next refresh, units or bitemporal queries: this part of Adele has no prior art in this angle.

| Project | Verdict | What |
|---|---|---|
| [MotherDuck Agent Skills](https://github.com/motherduckdb/agent-skills) | inspiration | Open-source catalog of 17 SKILL.md skills (connect, explore, query, duckdb-sql, plus workflow and use-case skills) that teach coding agents to use MotherDuck/DuckDB. Announced at https://motherduck.com/blog/motherduck-agent-skills/ |
| [mcp-server-motherduck (local DuckDB/MotherDuck MCP) and MotherDuck remote MCP](https://github.com/motherduckdb/mcp-server-motherduck) | inspiration | Official MCP server for local DuckDB files, S3 and MotherDuck. A separate hosted remote MCP (https://motherduck.com/docs/sql-reference/mcp/) adds catalog search, docs questions, and "Guides". |
| [boettiger-lab/mcp-data-server](https://github.com/boettiger-lab/mcp-data-server) | inspiration | MCP server that gives SQL access (DuckDB) to public Parquet datasets on S3, with dataset discovery from a STAC catalog. Aimed at H3-indexed environmental data. |
| [Hugging Face hf CLI + hf-cli skill (hf datasets sql / parquet) and dataset viewer](https://github.com/huggingface/skills/blob/main/skills/hf-cli/SKILL.md) | inspiration | The hf CLI exposes datasets as Parquet URLs and runs DuckDB SQL on them; a SKILL.md generated from the CLI help teaches agents the commands. The dataset viewer converts every dataset to Parquet (https://huggingface.co/docs/dataset-viewer/en/parquet). |
| [duckdb/duckdb-skills](https://github.com/duckdb/duckdb-skills) | reuse-as-component | Official DuckDB skills for Claude Code that drive the DuckDB CLI: attach-db, query, read-file, duckdb-docs, read-memories, install-duckdb. |
| [Data Commons MCP server (datacommonsorg/agent-toolkit)](https://docs.datacommons.org/mcp/) | inspiration | Google's hosted MCP server for public statistics (time series per variable and place), with packaged skills for agents. Repo: https://github.com/datacommonsorg/agent-toolkit |
| [lacon](https://github.com/andrii-su/lacon) | inspiration | Small CLI + Claude Code skill: agents query CSV/Parquet/JSON files through nine curated DuckDB primitives and receive capped answers instead of file contents. |
| [cyanheads/socrata-mcp-server](https://github.com/cyanheads/socrata-mcp-server) | inspiration | MCP server over the Socrata SODA API for 39 government open-data portals, with DuckDB staging of large results. |
| [ondata/ckan-mcp-server](https://github.com/ondata/ckan-mcp-server) | inspiration | MCP server for CKAN open-data portals (about 950 portals in its registry): dataset search, metadata, DataStore queries including SQL, quality scores. |
| [Datasette Agent (datasette/datasette-agent)](https://github.com/datasette/datasette-agent) | inspiration | Simon Willison's plugin that adds an LLM assistant inside Datasette (SQLite), launched 2026-05-21 (https://simonwillison.net/2026/May/21/datasette-agent/). |
| [MCP Toolbox for Databases (googleapis/genai-toolbox)](https://github.com/googleapis/genai-toolbox) | not-relevant | Google's open-source MCP server for databases: prebuilt generic tools (list_tables, execute_sql) and custom tools declared in tools.yaml as parameterized SQL statements. |
| [duckquill (sigridjineth/text2sql)](https://docs.rs/crate/duckquill/0.2.4/source/README.md) | inspiration | Rust CLI and HTTP service for agents in Codex CLI or Claude Code: convert raw file to Parquet, return schema, run read-only DuckDB SQL. |

### cli-skill-vs-mcp

The evidence supports CLI + SKILL.md for Adele's users (coding agents with a shell), but not as a general rule. Controlled evals (Scale Labs, Arize) find that correctness is about equal between MCP and CLI on frontier models; the differences are in cost, turns and composition, and they depend on the harness. Claude Code now defers MCP tool definitions by default, so the argument "MCP fills the context" is weaker than in 2025. Challenge to the spec: (1) a thin MCP wrapper is only needed for chat clients without a shell; (2) write a short opinionated skill, with `adele describe` as the source of truth, not a copy of the catalog; (3) measured gains for SQL come from representative values, keys, and column descriptions (a few points each on BIRD), so 5 sample rows should be complemented by distinct values per categorical column; (4) no benchmark found measures units or grain: build a small eval of 10 to 20 questions.

| Project | Verdict | What |
|---|---|---|
| [Vercel d0: "We removed 80% of our agent's tools"](https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools) | inspiration | Blog post (Andrew Qu, 2025-12-22) on Vercel's internal text-to-SQL agent. The team replaced many specialised tools with bash access to a directory of semantic layer files (Cube; YAML, Markdown, JSON), plus SQL execution. |
| [Scale Labs: MCP vs CLI tool interfaces (benchmark)](https://labs.scale.com/blog/mcp-vs-cli) | inspiration | Controlled comparison (dated 2026-07-08) of MCP-only, CLI-only, both, and hybrid routing on 50 long agentic tasks in two enterprise-style environments (113 and 140 tools), with Opus 4.6/4.8 and GPT-5.4/5.5, at least 4 runs per task and condition. |
| [Arize: MCP vs CLI Skills eval](https://arize.com/blog/mcp-vs-cli-skills-for-agents-what-our-eval-found-and-which-you-should-use/) | inspiration | Eval by Laurie Voss (May 2026): 25 GitHub tasks in 4 tiers, 5 runs each, Opus 4.6 in the Claude Agent SDK; arms: GitHub MCP server, a 2,187-line skill, a 341-line prescriptive skill, and bare Claude with a shell. |
| [Anthropic: Skill authoring best practices (docs)](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices) | reuse-as-component | Official documentation on how to write a SKILL.md: frontmatter limits, progressive disclosure patterns, scripts, evaluation. |
| [Anthropic engineering: Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) | inspiration | Engineering post (2025-10-16, updated 2025-12-18 when Agent Skills became an open standard) that defines the three levels of progressive disclosure. |
| [Anthropic engineering: Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) | inspiration | Engineering post (2025-11-04) on the two costs of direct MCP tool calls (definitions loaded upfront; intermediate results passing through the model) and on presenting tools as files that the agent explores. |
| [Anthropic engineering: Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) | inspiration | Engineering post (2025-09-11) with concrete rules for the output of tools used by agents; the rules apply equally to CLI output. |
| [MotherDuck CLI (agent docs) and motherduckdb/agent-skills](https://motherduck.com/docs/getting-started/interfaces/motherduck-cli/agents/) | inspiration | MotherDuck's CLI bundles DuckDB and is documented explicitly for agents; a separate MIT repository (https://github.com/motherduckdb/agent-skills) holds 21 skills in three layers (utility, workflow, use-case). MotherDuck also runs an MCP server. |
| [MotherDuck research: Query-log-informed schema descriptions and text-to-SQL](https://motherduck.com/research/query-log-informed-schema-descriptions-text-to-sql/) | inspiration | Thesis at MotherDuck (supervised by Hannes Muehleisen and Till Doehmen) that measures how samples and auto-generated column descriptions change execution accuracy on BIRD-Dev and on a benchmark built from MotherDuck's own warehouse. |
| [Synthetic SQL Column Descriptions and Their Impact on Text-to-SQL Performance (arXiv 2408.04691)](https://arxiv.org/html/2408.04691v4) | inspiration | Paper that builds gold column descriptions for BIRD-Dev and measures zero-shot execution accuracy of six models with no descriptions, the original BIRD descriptions, gold descriptions, and LLM-generated ones. |
| [CodeS (arXiv 2402.16347): ablation of prompt metadata](https://arxiv.org/html/2402.16347v1) | inspiration | Open-source text-to-SQL models (1B to 15B) with a prompt that contains column types, comments, representative values, primary/foreign keys; the paper has the cleanest ablation of each metadata component. |
| [Spider 2.0 (arXiv 2411.07763) and BIRD (arXiv 2305.03111)](https://arxiv.org/abs/2411.07763) | inspiration | The two reference benchmarks for text-to-SQL. Spider 2.0 has 632 enterprise workflow problems on databases that often have over 1,000 columns; BIRD has 12,751 pairs on 95 databases with human-written 'evidence' hints. |
| [dbt Labs: Semantic Layer vs Text-to-SQL, 2026 benchmark, and dbt-agent-skills](https://docs.getdbt.com/blog/semantic-layer-vs-text-to-sql-2026) | inspiration | Blog post (2026-04-07) that reruns an 11-question benchmark on a 15-table insurance schema, 20 runs per question, comparing free text-to-SQL with queries through the dbt Semantic Layer. dbt also publishes skills (https://github.com/dbt-labs/dbt-agent-skills, Apache-2.0). |
| [Simon Willison: Claude Skills are awesome, maybe a bigger deal than MCP](https://simonwillison.net/2025/Oct/16/claude-skills/) | inspiration | Blog post (2025-10-16) that argues for skills and CLI tools over MCP for agents that have a shell. |
| [Justin Poehnelt: Rewrite your CLI for AI agents (Google Workspace CLI lessons)](https://justin.poehnelt.com/posts/rewrite-your-cli-for-ai-agents.md) | inspiration | Blog post (2026-03-04) with design principles for a CLI whose main user is an agent, drawn from the Google Workspace CLI (gws). |
| [DuckDB Skills for Claude Code (duckdb/duckdb-skills)](https://duckdb.org/2026/09/16/duckdb-skills.html) | reuse-as-component | Official DuckDB plugin (announced 2026-09-16) with skills that drive the DuckDB CLI: attach-db, query, read-file, convert-file, s3-explore, duckdb-docs, install-duckdb, and others. |
| [OpenAI: Inside our in-house data agent](https://openai.com/index/inside-our-in-house-data-agent/) | inspiration | OpenAI post (2026-01-29, per search results) on an internal data agent that uses several layers of context about tables (schema and lineage, enrichment from code, human annotations, memory, runtime queries). |

### metadata-standards

No standard covers all of Adele's needs, so Frictionless Data Package v2 plus an "adele:" block is a defensible base. I verified that v2 has primaryKey but no unit, temporal coverage, update frequency or freshness, and no naming rule for custom properties. Challenge 1: declare the "adele:" block as a real v2 extension (a JSON Schema profile referenced by $schema) so that frictionless-py validates it. Challenge 2: do not invent field names. Borrow from oemetadata (unit per field, timeseries start/end/resolution/alignment/aggregationType, same domain, also Frictionless-based), from ODCS (slaProperties: frequency, latency, cron schedule; dataGranularityDescription) and from dbt (warn_after/error_after). Challenge 3: ODCS + datacontract-cli is the only stack with ready drift and breaking-change tooling on DuckDB/Parquet. Consider generating ODCS from the descriptor for those checks. Croissant, CSVW, DCAT and schema.org are export targets only. DuckLake could replace hand-built as_of logic.

| Project | Verdict | What |
|---|---|---|
| [Frictionless Data Package v2 (Table Schema) + frictionless-py](https://datapackage.org/standard/table-schema/) | reuse-as-component | The JSON/YAML descriptor standard that Adele already plans to use: package, resource, table schema. frictionless-py is the reference Python library. |
| [oemetadata (Open Energy Platform)](https://github.com/OpenEnergyPlatform/oemetadata) | inspiration | Metadata standard for energy datasets, built on Frictionless Data Package, used by the Open Energy Platform. Nested JSON with schema, template and example. |
| [Open Data Contract Standard (ODCS, Bitol / Linux Foundation)](https://bitol-io.github.io/open-data-contract-standard/latest/) | inspiration | YAML standard for data contracts: schema, data quality rules, SLA, servers, team, pricing. Documented up to v3.2.0. |
| [datacontract-cli](https://github.com/datacontract/datacontract-cli) | reuse-as-component | Open-source CLI and Python library that lints ODCS contracts and tests real data against them (schema and quality), with import/export to 25+ formats. |
| [dbt sources / model contracts (schema.yml)](https://docs.getdbt.com/reference/resource-properties/freshness) | inspiration | dbt's YAML properties for sources and models, including declarative freshness thresholds checked by 'dbt freshness'. |
| [DuckLake](https://ducklake.select/docs/stable/specification/introduction) | inspiration | Lakehouse format from the DuckDB team: metadata in a SQL catalog database, data in Parquet files, with snapshots and time travel. |
| [Croissant (MLCommons) + mlcroissant](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.1.html) | inspiration | JSON-LD metadata format for ML datasets built on schema.org/Dataset, with FileObject/FileSet, RecordSet and Field layers. mlcroissant is the Python library. |
| [Apache Ossie (incubating), formerly Open Semantic Interchange (OSI)](https://github.com/apache/ossie) | inspiration | Vendor-neutral YAML/JSON specification for exchanging semantic models (datasets, fields, relationships, metrics) between BI, analytics and AI tools. |
| [schema.org Dataset (and PropertyValue)](https://developers.google.com/search/docs/appearance/structured-data/dataset) | inspiration | The schema.org vocabulary for describing datasets in JSON-LD, used by Google Dataset Search; Croissant and DCAT mappings build on it. |
| [DCAT 3 (W3C)](https://www.w3.org/TR/vocab-dcat-3/) | inspiration | W3C RDF vocabulary for data catalogs, the base of European open data portals (DCAT-AP). |
| [dbt semantic layer / MetricFlow](https://docs.getdbt.com/docs/build/semantic-models) | not-relevant | dbt's YAML layer that declares entities, dimensions and metrics on top of models, so that tools generate SQL for metric queries. |
| [CSVW (CSV on the Web, W3C)](https://www.w3.org/TR/tabular-metadata/) | not-relevant | W3C metadata vocabulary (JSON-LD) for tabular data on the web: table groups, tables, columns, datatypes, keys. |
| [Hugging Face dataset cards](https://huggingface.co/docs/hub/datasets-cards) | inspiration | README.md with a YAML header that documents a dataset on the Hugging Face Hub (license, language, tags, task categories, file configuration). |
| [Datasheets for Datasets (Gebru et al.)](https://arxiv.org/abs/1803.09010) | not-relevant | A paper proposing that each dataset ships with a prose document that answers a fixed list of questions about motivation, composition, collection process and recommended uses. |
| [Apache Iceberg / Delta Lake table metadata](https://iceberg.apache.org/spec/) | not-relevant | Open table formats that add a metadata layer (schema, partitions, snapshots, column statistics) on top of Parquet files. |

### bitemporal-revisions

No existing project fits "append-only Parquet + DuckDB on one box" as a whole. TimeDB (ClickHouse), tshistory (PostgreSQL), XTDB (own Arrow engine) and ArcticDB (BSL license, own format) all replace the storage that Adele already chose. Best fit: build it as plain rows (delivery_start, fetched_at, value) in Parquet and compute as_of with a DuckDB filter plus "latest row per key" (QUALIFY row_number / arg_max). Borrow the vocabulary from TimeDB (valid_time, knowledge_time, change_time), the API shape from ALFRED, Energy Quantified and Volue, and the row-hash trick from dlt to avoid storing unchanged refetches. Challenges to the spec: (1) fetched_at is not the source's publication time. Keep both when the source gives one (ENTSO-E UpdateTime), and declare which one as_of uses. (2) Table-format time travel (DuckLake, Iceberg) versions the table, not the knowledge time, and it ends when snapshots expire. It cannot replace the fetched_at column. (3) DuckLake 1.x is a credible optional layer for atomic commits and schema-drift history.

| Project | Verdict | What |
|---|---|---|
| [rebase-energy/timedb](https://github.com/rebase-energy/timedb) | inspiration | Open-source Python client for "3-dimensional" time series from the energy sector (Rebase Energy). Stores forecast revisions and corrections as plain rows, with as-of reads. |
| [DuckDB native pattern (append-only rows + ASOF JOIN / QUALIFY)](https://duckdb.org/2023/09/15/asof-joins-fuzzy-temporal-lookups.html) | reuse-as-whole | Not a project: the pattern of storing every revision as a row with a knowledge timestamp in Parquet, and computing the as-of view in SQL with DuckDB (filter fetched_at <= T, keep the latest row per key; or ASOF JOIN for per-row cutoffs). |
| [DuckLake (time travel + data change feed)](https://ducklake.select/docs/stable/duckdb/usage/time_travel) | reuse-as-component | Lakehouse format from the DuckDB team: Parquet data files plus a SQL catalog database (a DuckDB file in the simplest setup) that holds snapshots, schema versions and statistics. |
| [ALFRED / FRED API real-time periods (St. Louis Fed)](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) | inspiration | The reference public API for vintage (revised) economic series: every observation carries a real-time period during which that value was the published one. |
| [Energy Quantified Python client (instances)](https://energyquantified-python.readthedocs.io/en/latest/userguide/terminology.html) | inspiration | Commercial European power and gas data vendor. Its client docs define a clean data model for forecast vintages: a curve of type INSTANCE holds one series per (issued, tag). |
| [Volue Insight (ex Wattsight) curve types](https://docs.volue.com/data-and-forecasts/volue-insight-timeseries/guides/curves) | inspiration | Commercial power market data API. Curves are typed by how the knowledge axis is exposed: TIME_SERIES, TAGGED, INSTANCES, TAGGED_INSTANCES, PAIRED_LIST. |
| [dlt (dlthub) scd2 merge strategy](https://dlthub.com/docs/general-usage/merge-loading) | reuse-as-component | Open-source Python ingestion library. Its `scd2` merge strategy keeps history of changed rows with validity columns and a row hash. |
| [AlphaForge PIT store](https://alphaforge.readthedocs.io/en/latest/guides/pit/) | inspiration | A Python research library (finance) with a point-in-time accessor backed by a "DuckDBParquetStore". The only project found that combines vintages, DuckDB and Parquet. |
| [Timeseries Refinery / tshistory (Pythonian)](https://pypi.org/project/tshistory/) | inspiration | A versioned time series store on PostgreSQL ("Timeseries store with version control") with a web UI and formula layer (the Refinery). Used in energy and commodity trading. |
| [dbt snapshots (SCD type 2)](https://docs.getdbt.com/docs/build/snapshots) | inspiration | dbt's built-in mechanism to turn a mutable source table into a history table with validity intervals, by comparing the source at each run. |
| [Feast point-in-time joins](https://docs.feast.dev/getting-started/concepts/point-in-time-joins) | inspiration | Open-source feature store. Its historical retrieval joins feature rows to an entity dataframe so that each training row only sees values available at its own timestamp. |
| [XTDB v2](https://docs.xtdb.com/concepts/key-concepts.html) | not-relevant | A bitemporal SQL database (SQL:2011 valid time + system time on every table), Postgres wire protocol, storage as Arrow files on an object store. |
| [ArcticDB (Man Group)](https://docs.arcticdb.io/latest/licensing/) | not-relevant | A versioned DataFrame store for Python (every write creates a version; snapshots; read with as_of), on LMDB or S3. |
| [Iceberg / Delta / lakeFS / Dolt (table or repository versioning)](https://duckdb.org/docs/current/core_extensions/iceberg/overview.html) | not-relevant | Table formats with snapshot time travel (Iceberg, Delta), and Git-like versioning of object stores (lakeFS) or of a MySQL-compatible database (Dolt). |

### ingestion-orchestration

No open-source tool gives "email on schema drift" out of the box. Closest: dlt schema contracts (freeze --> exception, nothing loaded) and Dagster build_column_schema_change_checks plus its SMTP run-failure sensor. Dagster's direct alerts on checks and freshness are paid (Dagster+). dlt documents only Slack and Sentry. Kestra gives email on any failure with one system flow.

Recommendation: systemd timers + plain Python, dlt as a library for extraction, incremental state and contract, and a dead man's switch (Healthchecks or an equivalent rule in Adele). An orchestrator is not justified for 12 sources, unless a UI with run history is wanted (then Dagster).

Challenges to the spec: (1) dlt's Parquet filesystem destination partitions by load time, not by a data column, so Adele must write the delivery-month partitions itself (DuckDB COPY PARTITION_BY). (2) Add a third status "stale / fetcher did not run": a failure email cannot report a job that never started. (3) Derive the refresh ETA from the timer definition.

| Project | Verdict | What |
|---|---|---|
| [dlt (dlthub)](https://github.com/dlt-hub/dlt) | reuse-as-component | Python library (no server, no daemon) that extracts from APIs, files and SQL, infers and versions a schema, and loads to a destination, including a local filesystem destination that writes Parquet. |
| [systemd timers (or cron) + plain Python + DuckDB](https://wiki.archlinux.org/title/Systemd_timer) | reuse-as-component | The baseline with no framework: one systemd timer and service unit per dataset, running a Python fetcher that writes Parquet with DuckDB. |
| [Healthchecks (healthchecks.io, self-hostable)](https://github.com/healthchecks/healthchecks) | reuse-as-component | Open-source monitor for cron jobs (Python/Django). Each job pings a URL. The service sends an alert when a ping is late or when the job reports a failure. |
| [Dagster](https://dagster.io/docs/guides/observe/asset-freshness-policies) | inspiration | Asset-based orchestrator in Python with a web UI, a daemon for schedules and sensors, asset checks and freshness policies. |
| [PUDL (Catalyst Cooperative)](https://github.com/catalyst-cooperative/pudl) | inspiration | Open-source pipeline that turns US public energy data (EIA, FERC, EPA: spreadsheets, CSV, database dumps) into Parquet tables plus a DuckDB database, rebuilt every night. |
| [Kestra](https://kestra.io/docs/installation/standalone-server) | inspiration | Declarative orchestrator (flows in YAML) on the JVM, with a UI and a large plugin catalog. |
| [Prefect (v3, self-hosted server)](https://docs.prefect.io/integrations/prefect-email) | inspiration | Python orchestrator: decorated flows and tasks, a server with UI, deployments with cron schedules, automations that react to events. |
| [Git scraping + git-history (Simon Willison)](https://simonwillison.net/2020/Oct/9/git-scraping/) | inspiration | Pattern: a scheduled job fetches a resource, writes it to a file in a git repo and commits only when it changed. git-history then converts the commit history of that file into SQLite tables. |
| [Bruin + ingestr](https://github.com/bruin-data/bruin) | inspiration | Bruin is a CLI that combines ingestion, SQL/Python transformations and data quality checks in one project. ingestr is its single-command tool that copies data from a source to a destination. |
| [Apache Airflow (3.x)](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html) | not-relevant | The standard DAG scheduler in Python. |
| [Meltano / Singer](https://github.com/meltano/meltano) | not-relevant | Declarative EL engine (yaml project) that runs Singer taps and targets as subprocesses. |
| [PyAirbyte](https://github.com/airbytehq/PyAirbyte) | not-relevant | Python library that runs Airbyte connectors in-process and writes to a local cache. |
| [SQLMesh](https://github.com/TobikoData/sqlmesh) | not-relevant | SQL/Python transformation framework (dbt-compatible) with model versioning, audits and a per-model cron. |
| [Flat Data (githubocto/flat)](https://github.com/githubocto/flat) | not-relevant | GitHub Action from GitHub's former OCTO team that fetches a URL or runs a SQL query on a schedule and commits the result to the repo, with an optional Deno postprocessing script. |
| [Bytewax](https://github.com/bytewax/bytewax) | not-relevant | Python stream-processing framework with a Rust engine (stateful dataflows, windows, Kafka connectors). |

### data-quality-schema-drift

No listed tool covers Adele's whole need, and most are too heavy or tied to dbt. The checks themselves are small: (1) compare DuckDB `parquet_schema()`/DESCRIBE with the types in the descriptor, (2) compare now with max(fetched_at) and max(delivery_start), (3) email when the status changes. Recommendation: write these in about 200 lines of DuckDB SQL and Python, and reuse two components: frictionless-py (validate the descriptor and the raw csv/xlsx at ingest) and a dead man's switch outside the box (Healthchecks), because the box cannot email about its own death. Challenges to the spec: (a) define freshness on both time axes with warn and error thresholds, plus a cron deadline with a tolerance window (Dagster model) to compute the ETA; (b) classify schema changes (added column, dropped column, type change) and define which ones block publication; (c) ODCS + datacontract-cli is the main competitor to Frictionless as the descriptor format: decide explicitly.

| Project | Verdict | What |
|---|---|---|
| [frictionless-py (Frictionless Framework)](https://github.com/frictionlessdata/frictionless-py) | reuse-as-component | Python library and CLI to describe, extract, validate and transform tabular data against Frictionless Table Schema / Data Package descriptors. |
| [Healthchecks (healthchecks.io, self-hostable)](https://github.com/healthchecks/healthchecks) | reuse-as-component | Dead man's switch for cron jobs: each job pings an URL, and the service alerts when a ping does not arrive on time or when the job signals a failure. |
| [Data Contract CLI (datacontract-cli) + Open Data Contract Standard (ODCS)](https://github.com/datacontract/datacontract-cli) | inspiration | CLI and Python library that lints a YAML data contract (ODCS), tests real data against it, and compares two versions of a contract. ODCS (https://github.com/bitol-io/open-data-contract-standard, v3.2.0, Apache-2.0, LF AI & Data) is the contract format. |
| [DuckDB parquet_schema() diff pattern (Kestra blueprint as a written example)](https://kestra.io/blueprints/duckdb-parquet-schema-evolution-guard) | inspiration | Not a library: a pattern that reads the footers of two Parquet files with DuckDB's `parquet_schema()`, joins them with a FULL OUTER JOIN on column name, and reports the differences. |
| [dbt source freshness / dbt freshness](https://docs.getdbt.com/reference/resource-properties/freshness) | inspiration | dbt's declarative freshness check: per source table, a timestamp column and two thresholds, evaluated by one SQL query. |
| [Dagster freshness policies](https://dagster.io/docs/guides/observe/asset-freshness-policies) | inspiration | Freshness policies attached to assets in the Dagster orchestrator: a time window or a cron deadline. |
| [Soda Core v4](https://github.com/sodadata/soda-core) | inspiration | Engine that verifies YAML data contracts (schema and data quality checks) against a data source, through a CLI (`soda contract verify`) and a Python API. |
| [Pandera](https://github.com/unionai-oss/pandera) | reuse-as-component | Python library that validates dataframes (pandas, polars, pyspark, ibis and others) against a schema declared in code. |
| [Pointblank (Posit)](https://github.com/posit-dev/pointblank) | inspiration | Python data validation library with validation plans, thresholds, HTML reports, a CLI and YAML plans. |
| [dlt schema contracts (dlthub)](https://dlthub.com/docs/general-usage/schema-contracts) | inspiration | The Python ingestion library dlt lets each pipeline declare what happens when incoming data does not fit the stored schema. |
| [Great Expectations (GX Core)](https://github.com/great-expectations/great_expectations) | not-relevant | Python data quality framework built on "Expectations" (unit tests for data), with validation results and generated documentation. |
| [Elementary (elementary-data)](https://github.com/elementary-data/elementary) | not-relevant | Open-source CLI and dbt package for data observability on top of dbt: anomaly tests, schema change tests, a report, alerts. |
| [DuckGuard](https://github.com/XDataHubAI/duckguard) | inspiration | Young Python data quality library built on DuckDB, with schema tracking, freshness monitoring, data contracts and notifiers. |
| [Uptime Kuma](https://github.com/louislam/uptime-kuma) | inspiration | Self-hosted monitoring tool with many monitor types, including push (heartbeat) monitors. |
| [re_data](https://github.com/re-data/re-data) | not-relevant | Open-source data reliability framework for dbt projects (metrics, anomalies, schema changes). |

### serving-and-sync

No single project gives authenticated remote SQL plus incremental pull. The least custom code is two stock parts. (1) Static Parquet partitions behind Caddy/nginx with a bearer check per API key: DuckDB httpfs reads them with range requests and an HTTP secret, and pull is a manifest diff (about 100 lines) or rclone. (2) Quack (DuckDB 2.0 core extension) for server-side SQL: per-user tokens through a SQL macro, database attached read-only, reverse proxy for TLS. It can replace a custom HTTP query API, but only DuckDB clients connect. Challenges to the spec: DuckLake snapshots (AT TIMESTAMP, table_changes) already implement knowledge time and as_of, and its file list is a ready pull manifest, so consider it instead of hand-made month partitions plus fetched_at. Plain HTTP has no documented glob, so descriptors must list partition files. GizmoSQL is in maintenance, Seafowl and ROAPI lack read auth, Delta Sharing and Iceberg REST need object storage.

| Project | Verdict | What |
|---|---|---|
| [DuckDB httpfs + static file server (nginx/Caddy) with HTTP bearer secret](https://duckdb.org/docs/2.0/core_extensions/httpfs/https.html) | reuse-as-component | DuckDB's core httpfs extension reads remote Parquet over HTTP(S) with range requests, so that only the footer and the needed columns are downloaded. Any static web server that honours Range headers can be the data server. |
| [Quack (DuckDB client-server protocol)](https://duckdb.org/docs/2.0/quack/overview.html) | reuse-as-component | Official DuckDB extension that turns a DuckDB instance into an HTTP server to which other DuckDB instances attach (`ATTACH 'quack:host' AS remote`). Announced 2026-05-12, autoloadable core extension since DuckDB 1.5.3. |
| [DuckLake (v1.0) and Frozen DuckLake over HTTPS](https://ducklake.select/faq) | reuse-as-component | Lakehouse format from DuckDB Labs: Parquet data files plus a SQL catalog database (DuckDB, SQLite or PostgreSQL) holding snapshots, schemas and file lists. v1.0 released 2026-04-13; v1.1 was announced for September 2026. |
| [rclone (HTTP backend)](https://rclone.org/http/) | inspiration | General file sync tool; its HTTP remote syncs from a web server that returns a parseable directory listing. |
| [Hardcharger (GizmoData)](https://gizmodata.com/hardcharger) | inspiration | Open-source standalone server for DuckDB 2.0, announced 2026-10-21, successor of GizmoSQL. Clients speak Chargewire, an HTTP/1.1 protocol with Arrow IPC results and JSON control messages. |
| [GizmoSQL](https://github.com/gizmodata/gizmosql) | not-relevant | Arrow Flight SQL server with DuckDB (or SQLite) as the engine, with TLS, password and JWT authentication. |
| [DuckDB httpserver community extension (Query.Farm)](https://duckdb.org/community_extensions/extensions/httpserver.html) | reuse-as-component | Community extension that exposes a DuckDB instance as an HTTP API: POST a SQL query, get results; includes a browser query UI. |
| [Delta Sharing (protocol + reference server)](https://github.com/delta-io/delta-sharing) | inspiration | Open REST protocol for read-only sharing of Delta/Parquet tables with bearer-token profiles; the server returns presigned URLs of Parquet files. Python connector with `load_as_pandas`. |
| [Hugging Face Hub datasets (hf:// in DuckDB)](https://duckdb.org/docs/2.0/core_extensions/httpfs/hugging_face.html) | inspiration | Hosted git-like dataset repositories that DuckDB reads directly through hf:// paths, with glob, private access tokens and revisions. |
| [ROAPI](https://github.com/roapi/roapi) | not-relevant | Rust server (DataFusion) that exposes static files as read-only APIs: SQL, GraphQL, REST, Flight SQL and Postgres wire protocol. |
| [Datasette + datasette-parquet](https://github.com/cldellow/datasette-parquet) | not-relevant | Datasette plugin that serves a DuckDB file or a directory of Parquet/CSV/JSONL files through Datasette's web UI and JSON API. |
| [Seafowl (Splitgraph / EDB)](https://github.com/splitgraph/seafowl) | inspiration | Single-binary analytical database on DataFusion with an HTTP SQL API designed for CDN caching; stores Parquet with the Delta protocol. |
| [Iceberg REST catalogs (Lakekeeper, Polaris) with DuckDB](https://duckdb.org/docs/current/core_extensions/iceberg/iceberg_rest_catalogs) | not-relevant | Standard REST catalog for Iceberg tables; DuckDB attaches to it with an iceberg secret (OAuth2). |
| [Pooch](https://www.fatiando.org/pooch/latest/) | inspiration | Python library that downloads data files only when needed into a local cache, driven by a registry of file names and hashes. |

### data-catalogs-with-ai

The heavy catalogs (DataHub, OpenMetadata, Unity Catalog, Gravitino, Marquez) are too heavy to reuse for a dozen datasets (JVM services, Postgres/Elasticsearch/Neo4j), and Amundsen (archived 2026-09-29) and Vanna (archived 2026-03-29) are dead. Their agent interfaces converge on the same small pattern, which transfers: (1) one discovery entry point that narrows progressively, (2) a separate call for time coverage and freshness, (3) token budgets and pagination on schema output, (4) free-text "ai instructions" stored next to the dataset, (5) skills shipped with the server. Closest prior art is Catalyst Cooperative's agent-skills (energy data, Frictionless datapackage.json, Parquet, DuckDB, SKILL.md, no MCP): it validates the Adele design almost point by point. Challenge to the spec: vendors that started with MCP (DataHub, MotherDuck, Malloy, Rill) all added skills afterwards, which supports "skill + CLI first"; but none of them exposes knowledge time or ETA of next refresh, so Adele must design those fields itself.

| Project | Verdict | What |
|---|---|---|
| [Catalyst Cooperative agent-skills (datapackage + pudl skills)](https://github.com/catalyst-cooperative/agent-skills) | reuse-as-component | Two agent skills from the maintainers of PUDL (US open energy data): a generic 'datapackage' skill for any Frictionless Data Package, and a 'pudl' skill with the domain knowledge for their Parquet tables published on a public S3 bucket. |
| [Malloy Publisher (MCP endpoint + bundled skills)](https://docs.malloydata.dev/documentation/user_guides/publishing/mcp_agents) | inspiration | The open-source server for Malloy semantic models. It serves REST plus one MCP endpoint with five tools, and ships agent skills. |
| [Rill (MCP server, ai_instructions, project skills)](https://docs.rilldata.com/guide/ai/mcp) | inspiration | BI-as-code tool on DuckDB/ClickHouse with a metrics layer in YAML. Its MCP server exposes metrics views, also from local Rill Developer (http://localhost:9009/mcp). |
| [DataHub MCP server + DataHub Skills](https://github.com/acryldata/mcp-server-datahub) | inspiration | MCP server for the DataHub metadata platform (search, entities, schema fields, lineage, real queries, aspect history) and an open-source skills registry on top. |
| [dbt MCP server](https://github.com/dbt-labs/dbt-mcp) | inspiration | Official MCP server for dbt: discovery of models and sources, semantic layer queries, SQL execution, dbt CLI commands, job administration. |
| [MotherDuck agent-skills (and duckdb-skills)](https://github.com/motherduckdb/agent-skills) | reuse-as-component | Open-source catalog of 17 SKILL.md skills that teach coding agents DuckDB SQL and MotherDuck workflows, published after MotherDuck already had an MCP server. |
| [OpenMetadata MCP server](https://docs.open-metadata.org/latest/how-to-guides/mcp/reference) | inspiration | MCP server built into the OpenMetadata catalog (enabled by default): 15 tools for search, entity details, lineage, context documents, data quality, and writes. |
| [Boring Semantic Layer (BSL)](https://github.com/boringdata/boring-semantic-layer) | inspiration | Lightweight semantic layer in Python on Ibis (dimensions and measures as lambdas), inspired by Malloy, with an MCP wrapper class. |
| [Wren AI (MDL semantic layer, CLI + skills + MCP)](https://github.com/Canner/WrenAI) | inspiration | Open-source 'GenBI' engine: a semantic and context layer in a git-friendly Modeling Definition Language, exposed to agents through a CLI, installable skills, SDKs and an MCP server. |
| [DataCharter](https://github.com/datacharter/datacharter) | inspiration | Small Python tool: a local SQL workspace where DuckDB federates files and databases and a charter.yaml contract governs what agents can see, served over a CLI and an MCP endpoint. |
| [Apache Ossie (incubating), formerly Open Semantic Interchange (OSI)](https://ossie.apache.org/) | inspiration | Vendor-neutral YAML specification for semantic models (datasets, fields, relationships, metrics) with an 'ai_context' block of instructions for agents. |
| [Cube (MCP server)](https://docs.cube.dev/docs/integrations/mcp-server) | not-relevant | Semantic layer (cubes, views, measures in YAML/JS) with an MCP server of 30 tools on the hosted platform. |
| [Unity Catalog OSS](https://github.com/unitycatalog/unitycatalog) | not-relevant | Open-source catalog for tables, volumes, functions and models (LF AI & Data sandbox project), with a REST API and a DuckDB extension. |
| [Apache Gravitino](https://github.com/apache/gravitino) | not-relevant | Federated metadata catalog ('metadata lake') over many sources, with Iceberg and Lance REST catalogs, a Trino connector, and an mcp-server directory in the repo. |
| [Dead or unsuitable: Amundsen, Vanna, Marquez/OpenLineage, Evidence, Data Contract CLI (ODCS)](https://github.com/amundsen-io/amundsen) | not-relevant | Group entry for the remaining starting points: Amundsen (catalog), Vanna (text-to-SQL), Marquez (OpenLineage server), Evidence (BI as code), plus Data Contract CLI as an unlisted neighbour. |

### financial-data-platforms

Finance and macro systems confirm the bitemporal core of the spec and suggest five additions. (1) Copy FRED/ALFRED: validity interval per row (realtime_start, realtime_end), a "list vintages" call, and read modes "as of T", "first release only", "new and revised only". (2) Add named catalog snapshots (ArcticDB) so that an analysis pins all datasets at once. (3) Flag datasets whose knowledge time was not observed (backfilled history) instead of inventing fetched_at (vintage UNKNOWN_VINTAGE). (4) Stable ids of the form source/dataset, plus a "latest" alias (DBnomics, OWID). (5) Per-field metadata rules from OWID (unit, short_unit, description, expected update period, origin block). Challenges to the spec: FRED uses closed intervals, keep half-open but document it. Massive and OpenBB moved from one tool per endpoint to search + call + SQL, and Macrobond ships MCP and Skill together: the CLI + SKILL.md + SQL choice is consistent with the trend, MCP stays optional. No whole system is reusable.

| Project | Verdict | What |
|---|---|---|
| [FRED / ALFRED API (St. Louis Fed)](https://fred.stlouisfed.org/docs/api/fred/series_observations.html) | inspiration | REST API for about 800k US macro series. ALFRED is the archive of vintages: every observation carries a real-time period that says when that value was the known one. |
| [ArcticDB (Man Group)](https://github.com/man-group/ArcticDB) | inspiration | Serverless DataFrame database for Python: the client library reads and writes versioned, compressed dataframes directly on S3, Azure Blob or LMDB. Successor of Arctic. |
| [Our World in Data ETL (owid/etl + owid-catalog)](https://docs.owid.io/projects/etl/architecture/design/uri/) | inspiration | Pipeline that republishes hundreds of public datasets through fixed stages (snapshot, meadow, garden, grapher), with yaml metadata in git and a Python catalog library. |
| [DBnomics](https://docs.db.nomics.world/) | inspiration | Free aggregator of public economic data (millions of series) with one fetcher per provider that runs daily, a common data model and one web API. |
| [vintage (vintage-mcp)](https://github.com/RezaSoleymanifar/vintage) | inspiration | Small open-source Python library and MCP server that gives point-in-time access to about 18 free financial sources (SEC EDGAR, FRED/ALFRED, Treasury, ECB...) for agents and backtests. |
| [Massive.com MCP server (formerly Polygon.io)](https://github.com/massive-com/mcp_massive) | inspiration | Official MCP server of a market data vendor. It replaced one tool per endpoint with three composable tools. |
| [OpenBB Open Data Platform (ODP) and openbb-mcp-server](https://docs.openbb.co/odp/python/extensions/interface/openbb-mcp) | inspiration | Open-source toolset that integrates many data providers behind one Python, REST, CLI and MCP interface. Formerly OpenBB Platform. |
| [Macrobond AI Data Feed](https://www.macrobond.com/company/newsroom/press-releases/macrobond-launches-ai-data-feed-with-mcp-and-skill-bringing-governed-macroeconomic-intelligence-to-enterprise-ai-workflows) | inspiration | Commercial macro data vendor that released on 2026-06-10 a service for AI workflows with three components: MCP, Skill and API. |
| [Qlib point-in-time database (Microsoft)](https://qlib.readthedocs.io/en/latest/advanced/PIT.html) | inspiration | Data layer of the Qlib quant framework for fundamentals that get amended, so that a backtest sees the version known at each date. |
| [EODHD MCP Server](https://github.com/EodHistoricalData/EODHD-MCP-Server) | not-relevant | Official MCP server of the EODHD market data API. |
| [Nasdaq Data Link (formerly Quandl)](https://docs.data.nasdaq.com/docs/tables) | inspiration | Commercial data marketplace with a time-series API (database_code/dataset_code ids) and a Tables API with a metadata endpoint. |
| [pandas-datareader](https://pandas-datareader.readthedocs.io/en/latest/whatsnew.html) | not-relevant | Python library with one DataReader function over several remote sources (FRED, Stooq, World Bank...), which returns DataFrames. |

### research-data-infra

No project here replaces Adele as a whole. PUDL has the closest shape (Parquet + DuckDB + Frictionless datapackage + agent skill). ERDDAP and SDMX offer the best ideas on self-description. ERDDAP: the catalog is itself a queryable table (allDatasets) with minTime, maxTime, and a per-dataset staleness rule (testOutOfDate --> outOfDate index); units travel inside the data files; email/URL subscriptions. SDMX: structure (DSD) is separated from data, Eurostat publishes UPDATE_DATA and UPDATE_STRUCTURE timestamps separately, and the REST API defines updatedAfter, asOf and includeHistory (the same bitemporal semantics as Adele). Challenges to the spec: (1) add a catalog table that DuckDB can query, not only one descriptor per dataset; (2) define staleness as a declared rule, not a free-text "refresh" field; (3) OEMetadata already extends Frictionless with unit, resolution, timestamp alignment and aggregation type, so reuse its key names instead of inventing an "adele:" block from scratch; (4) the spec lacks alignment and aggregation type per field.

| Project | Verdict | What |
|---|---|---|
| [PUDL (Public Utility Data Liberation, Catalyst Cooperative) + its agent skill](https://github.com/catalyst-cooperative/pudl) | inspiration | Open pipeline that cleans US energy data (EIA, FERC, EPA) and publishes it as one Parquet file per table, plus a DuckDB file, with a Frictionless datapackage.json. A separate repo (https://github.com/catalyst-cooperative/agent-skills) holds an agent skill for it. |
| [ERDDAP (NOAA)](https://github.com/ERDDAP/erddap) | inspiration | Java data server that gives a uniform URL-based way to download subsets of gridded and tabular (tabledap) scientific datasets in many file formats, with rich metadata per dataset. Used by NOAA, IOOS and many ocean institutes. |
| [SDMX REST API (sdmx-twg/sdmx-rest)](https://github.com/sdmx-twg/sdmx-rest/blob/master/doc/data.md) | inspiration | The official REST specification of SDMX, the standard used by Eurostat, ECB, OECD, BIS for statistical data and metadata exchange. Separates structure queries (dataflow, DSD, codelists, constraints) from data queries and availability queries. |
| [Eurostat dissemination API (SDMX 3.0 + Catalogue API)](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started/sdmx3.0) | inspiration | Eurostat's public implementation of SDMX 2.1 and 3.0, plus a catalogue API (table of contents, RSS of updates). |
| [OEMetadata (Open Energy Platform)](https://github.com/OpenEnergyPlatform/oemetadata) | reuse-as-component | A metadata standard for energy data, as nested JSON, based on the Frictionless Data Package specification and the FAIR principles. Used by the German Open Energy Platform. |
| [Our World in Data ETL + owid-catalog](https://github.com/owid/etl) | inspiration | The compute graph that builds all OWID datasets, with metadata authored in YAML next to each step, and a Python client (owid.catalog) to search and fetch tables, indicators and charts. |
| [STAC (Collection spec + table extension)](https://github.com/radiantearth/stac-spec/blob/master/collection-spec/collection-spec.md) | inspiration | SpatioTemporal Asset Catalog: a JSON specification for catalogs of geospatial assets, with a companion API. The 'table' extension (https://github.com/stac-extensions/table) describes tabular assets. |
| [Croissant (MLCommons)](https://docs.mlcommons.org/croissant/docs/croissant-spec.html) | inspiration | A metadata format for ML datasets, JSON-LD built on schema.org, describing files (FileObject/FileSet) and RecordSets with typed fields. |
| [CKAN DataStore API (also the base of opendata.swiss)](https://docs.ckan.org/en/latest/maintaining/datastore.html) | inspiration | The tabular storage extension of the CKAN open data portal: loads resources into PostgreSQL and exposes search, SQL and schema endpoints. |
| [DCAT-AP CH (opendata.swiss) / DCAT-AP (data.europa.eu)](https://handbook.opendata.swiss/de/content/glossar/bibliothek/dcat-ap-ch.html) | not-relevant | The RDF metadata profile that Swiss and European open data portals require for dataset and distribution descriptions. |
| [Open Power System Data (time series package)](https://data.open-power-system-data.org/time_series/) | inspiration | A Frictionless data package of European load, generation and price time series (mostly from ENTSO-E) at 15, 30 and 60 minute resolution, in CSV, XLSX and SQLite. |
| [Socrata SODA API](https://dev.socrata.com/docs/endpoints.html) | not-relevant | The query API of the Socrata (Tyler) open data platform used by many US governments, with a SQL-like language (SoQL). |
| [intake (Take2) and intake-esm](https://github.com/intake/intake) | not-relevant | Python package to describe, catalog and load data declaratively; intake-esm (https://github.com/intake/intake-esm) is a plugin whose catalog is a JSON descriptor pointing to a CSV table with one row per asset. |
| [Pangeo Forge (pangeo-forge-recipes)](https://github.com/pangeo-forge/pangeo-forge-recipes) | not-relevant | Python library to write ETL recipes that convert archival scientific data into cloud-optimized formats (Zarr) in object storage. |

### github-hn-longtail

No project found combines Adele's parts (scheduled fetchers + Frictionless catalog + bitemporal Parquet + CLI/skill) for European power data; existing open-source work is API clients, MCP proxies (Luminus) and toy pipelines. The closest prior art is Catalyst Cooperative's agent-skills (generic Frictionless datapackage skill + PUDL skill on Parquet/DuckDB): if Adele descriptors stay valid Frictionless, that skill and the official duckdb-skills work unchanged, so the Adele skill can be thin. Agnes (Keboola; repo returned 404, unverified) reportedly implements the same pull design (manifest --> MD5 --> changed files, pull at session start). Two challenges to the spec: (1) TimeDB separates knowledge_time from change_time; for forecast datasets, Adele's fetched_at mixes "published by source" with "fetched by Adele", and unchanged rows should be skipped on append. (2) A frozen DuckLake over HTTPS could replace the custom partition sync and give snapshot time travel. llms.txt alone carries no dataset metadata (gridstatus).

| Project | Verdict | What |
|---|---|---|
| [Catalyst Cooperative agent-skills (datapackage skill + PUDL skill)](https://github.com/catalyst-cooperative/agent-skills) | reuse-as-component | Two installable agent skills from the PUDL team (US open energy data): a generic 'datapackage' skill that teaches a coding agent to work with any Frictionless datapackage.json, and a 'pudl' skill layered on top for PUDL's public Parquet files. Docs at https://docs.catalyst.coop/agent-skills/datapackage-skill/ and https://docs.catalyst.coop/agent-skills/pudl-skill/ |
| [duckdb-skills (official DuckDB plugin for Claude Code)](https://github.com/duckdb/duckdb-skills) | reuse-as-component | Official DuckDB skills plugin announced 2026-09-16 (https://duckdb.org/2026/09/16/duckdb-skills.html): attach-db, query, read-file, convert-file, s3-explore, spatial, duckdb-docs, read-memories, install-duckdb. |
| [Agnes (keboola/agnes-the-ai-analyst)](https://github.com/keboola/agnes-the-ai-analyst) | inspiration | Described by a project index as an open-source platform that distributes data to AI analysts: a server prepares Parquet files, and analysts run Claude Code against a local DuckDB built from them. |
| [TimeDB and EnergyDB (rebase-energy)](https://github.com/rebase-energy/timedb) | inspiration | TimeDB is a small Python client for '3-dimensional' time series on ClickHouse, built by an energy forecasting company. EnergyDB (https://github.com/rebase-energy/energydb) adds an asset hierarchy, a series catalog in PostgreSQL and units. |
| [Dinobase](https://github.com/DinobaseHQ/dinobase) | inspiration | Open-source 'agent-first data platform': syncs 100+ SaaS/API/database sources to Parquet, with DuckDB as query engine and metadata store, used by agents through a CLI or an MCP server. |
| [DataSpoc Lens (+ Pipe)](https://github.com/dataspoclab/dataspoc-lens) | inspiration | Small open-source CLI that mounts Parquet files in a cloud bucket as DuckDB views, with a manifest written by its companion ingestion tool (Pipe, Singer taps to Parquet), a local cache and an MCP mode. |
| [Frozen DuckLake / fdl CLI](https://github.com/flo8s/fdl) | inspiration | A 'Frozen DuckLake' is a read-only DuckLake catalog file plus Parquet files served from plain HTTPS or object storage with no catalog server (concept post: https://ducklake.select/2025/10/24/frozen-ducklake/). 'fdl' (PyPI: frozen-ducklake) is a CLI that builds and pushes/pulls such catalogs. |
| [Clarigrid](https://github.com/alexanderhoogsteyn/clarigrid) | reuse-as-component | Python SDK by a single author that gives one normalized interface to many European and US energy data sources (ENTSO-E, SMARD, Energy-Charts, Energinet, Elia, NESO, Elexon, ENTSOG, Fingrid, EIA-930, CAISO, NYISO, weather sources). |
| [Luminus (luminus-mcp)](https://github.com/arefiva/luminus) | inspiration | MCP server that exposes European and GB electricity and gas data to agents: ENTSO-E, ENTSOG, Elexon, Nordpool, SMARD, energy-charts, Regelleistung, JAO, ACER REMIT, RTE, Fingrid, Terna, REE and more. |
| [Skardi](https://github.com/bakey/skardi) | inspiration | Open-source 'agent data plane' (beta): data sources are exposed as parameterized SQL pipelines written in YAML, served as REST endpoints and as shell verbs. The fetched page is a fork of SkardiLabs/skardi. |
| [Orca (mathisdrn/orca)](https://github.com/mathisdrn/orca) | inspiration | Reference implementation of a 'serverless, declarative and agentic-ready data warehouse' on HackerNews data: dlt ingestion, dbt, Dagster, DuckDB + DuckLake, a semantic layer, and AGENTS.md files plus skills in the repo. |
| [DataCharter](https://github.com/datacharter/datacharter) | not-relevant | Local SQL workspace on DuckDB where a charter.yaml contract in git decides which tables, columns and rows an agent may read (read-only, PII masked). |
| [gridstatus.io llms.txt](https://www.gridstatus.io/llms.txt) | inspiration | The llms.txt of a commercial provider of US power market data (with an open-source BSD-3 Python library, gridstatus). |
| [grid-france (ijlyttle)](https://github.com/ijlyttle/grid-france) | inspiration | One-person pipeline that compiles RTE France grid data every night and publishes Parquet files next to a Quarto website. |
| [ENTSOE-energy-price-forecast (felipefl142)](https://github.com/felipefl142/ENTSOE-energy-price-forecast) | not-relevant | Small personal project: ENTSO-E prices and load for DE_LU into Hive-partitioned Parquet (year=YYYY/month=MM), then DuckDB SQL templates for bronze/silver/gold layers, then a forecast model. |

### gap:sql-endpoint-hardening

Every source agrees on one point: filtering SQL text fails (Arc CVE-2026-47735, the Quack docs warning on WITH ... INSERT), and DuckDB read-only mode alone still lets a query read local files (MotherDuck README, Redash CVE-2026-77371). The controls must be set in the engine. Minimal set for one box and ten trusted users: (1) parquet reached only through allowed_directories, then enable_external_access=false, autoinstall/autoload off, community extensions off, threads/memory_limit/max_temp_directory_size, lock_configuration=true last; (2) a timer that calls interrupt() (DuckDB has no native timeout); (3) cap on rows and bytes; (4) unprivileged user or container; (5) one hashed key per person, TLS and rate limit in the reverse proxy; (6) a log line per query (key id, SQL, duration, rows). Challenge to the spec: `adele pull` plus local DuckDB removes most of this attack surface, so remote `query` could be secondary. DuckDB 2.0 Quack may replace a custom HTTP endpoint.

| Project | Verdict | What |
|---|---|---|
| [DuckDB docs: Securing DuckDB (v2.0)](https://duckdb.org/docs/2.0/operations_manual/securing_duckdb/overview.html) | reuse-as-component | Official DuckDB guide on running SQL that is not fully trusted. It lists the engine settings that restrict files, network, extensions, secrets and resources. |
| [DuckDB Quack extension (remote protocol of DuckDB)](https://duckdb.org/docs/2.0/quack/security) | reuse-as-component | DuckDB extension that turns a DuckDB instance into an HTTP server to which other DuckDB clients ATTACH with 'quack:host' URIs (default port 9494). It was not in the list of starting points. |
| [simonw/research: duckdb-security](https://github.com/simonw/research/tree/main/duckdb-security) | reuse-as-component | Research report by Simon Willison (January 2026) with demo scripts that test DuckDB settings for untrusted queries from Python, including a timeout. |
| [MotherDuck / DuckDB MCP server (mcp-server-motherduck)](https://github.com/motherduckdb/mcp-server-motherduck) | inspiration | MCP server by MotherDuck that lets LLM agents run SQL on local DuckDB files or on MotherDuck. |
| [Datasette](https://docs.datasette.io/en/stable/settings.html) | inspiration | Simon Willison's server that publishes SQLite files with an HTTP API accepting arbitrary read-only SQL. It is the longest-running public example of this design. |
| [Arc (Basekick-Labs), CVE-2026-47735](https://corgea.com/advisories/vulnerabilities/CVE-2026-47735) | inspiration | Time-series database built on DuckDB and Parquet with an authenticated HTTP SQL endpoint. An advisory showed that its regex filter on SQL let any authenticated user read local files. |
| [Redash DuckDB query runner, CVE-2026-77371](https://app.opencve.io/cve/CVE-2026-77371) | inspiration | Redash (BI tool) added a DuckDB data source that left enable_external_access at its default. Users with query access could read and write files of the server process. |
| [caddy-duckdb-module (tobilg)](https://github.com/tobilg/caddy-duckdb-module) | inspiration | Caddy web server module that exposes DuckDB over REST with API keys, roles, and limits. |
| [GizmoSQL and its successor Hardcharger (GizmoData)](https://github.com/gizmodata/gizmosql) | inspiration | GizmoSQL is an Arrow Flight SQL server in front of DuckDB. Its README now says it is in maintenance mode and recommends Hardcharger, a new server for DuckDB 2.0 by the same company. |
| [DuckDB MCP extension (duckdb_mcp) security guide](https://duckdb-mcp.readthedocs.io/en/latest/guides/security/) | inspiration | Community DuckDB extension that makes DuckDB an MCP server or client. Its security guide lists per-statement-class switches and exposure defaults. |
| [httpserver DuckDB community extension (Query.farm, formerly quackscience)](https://duckdb.org/community_extensions/extensions/httpserver.html) | not-relevant | Community extension that exposes a running DuckDB process over HTTP: POST a SQL string, get JSON back. |
| [Supabase MCP "lethal trifecta" incident (write-up by Simon Willison)](https://simonwillison.net/2025/Jul/6/supabase-mcp-lethal-trifecta/) | inspiration | July 2025 demonstration by General Analysis: text in a support ticket made a Cursor agent with the Supabase MCP read a private table and write its content where the attacker could see it. |
| [ROAPI](https://github.com/roapi/roapi) | not-relevant | Rust server that creates read-only REST, GraphQL and SQL APIs over static files (parquet, csv, etc.) with Apache DataFusion as engine. |
| [Seafowl (Splitgraph)](https://github.com/splitgraph/seafowl) | not-relevant | Rust analytical database on DataFusion built for queries over HTTP, with results that follow HTTP cache rules so that a CDN can serve repeated queries. |

### gap:energy-domain-semantics-and-reference-data

No project that I found ships the history of bidding zones as a table with validity intervals. entsoe-py has only a README table by year and a date-aware geometry loader. Adele must author a small `zones` reference dataset itself (EIC, short name, area type, timezone, valid_from, valid_to, predecessor), seeded from entsoe-py, electricitymaps and the ENTSO-E code list. Challenge to the spec: "units per field" is not sufficient. Each field also needs (1) aggregation (mean power over the interval, or energy per interval), (2) the timestamp label (period start), (3) a sign convention for flows and imbalances, (4) currency, (5) the code list that the values belong to. OEMetadata 2.0 already names two of these (alignment, aggregationType) and is Frictionless-based: copy its keys into the "adele:" block. Resolution must be allowed per row or per period, because 15-minute SDAC (delivery day 2025-10-01) made series mixed. Use pint-parseable unit strings as PUDL does; QUDT and OEO are optional URIs.

| Project | Verdict | What |
|---|---|---|
| [entsoe-py (EnergieID)](https://github.com/EnergieID/entsoe-py) | reuse-as-component | Python client for the ENTSO-E Transparency Platform API. Its mappings.py is the de facto reusable table of area codes and ENTSO-E code lists in Python. |
| [ENTSO-E EDI Library: code list, SKOS code list, CIM XSD package, ESMP](https://www.entsoe.eu/publications/electronic-data-interchange-edi-library/) | reuse-as-component | The official source of the ENTSO-E code lists (PSR types, business types, document types, process types, curve types, units, currencies, coding schemes) and of the CIM European Style Market Profile (IEC 62325-351 and 62325-451-x). |
| [OEMetadata (Open Energy Platform)](https://github.com/OpenEnergyPlatform/oemetadata) | inspiration | A JSON metadata standard for energy datasets, 'based on the Frictionless Data Package specifications', with ontology annotations per field. |
| [PUDL metadata system (Catalyst Cooperative)](https://docs.catalyst.coop/pudl/en/latest/dev/metadata.html) | inspiration | The metadata layer of the Public Utility Data Liberation project (US energy data, published as Parquet and SQLite): field definitions are shared across tables and units are validated. |
| [electricitymaps-contrib zone configs](https://github.com/electricitymaps/electricitymaps-contrib/tree/master/config/zones) | inspiration | One YAML file per zone (DE.yaml, DK-DK1.yaml, AU-NSW.yaml ...) that holds reference data for the Electricity Maps parsers, plus the geometries of the zones. |
| [Open Energy Ontology (OEO)](https://github.com/OpenEnergyPlatform/ontology) | inspiration | A domain ontology for energy system analysis (OWL), used by OEMetadata to annotate fields and values with stable URIs. |
| [Open Power System Data: time series data package](https://data.open-power-system-data.org/time_series/) | inspiration | A Frictionless data package of load, generation and day-ahead prices for European zones, built from ENTSO-E Transparency data. |
| [SDAC 15-minute market time unit (primary announcements)](https://www.epexspot.com/en/news/15-minute-mtu-sdac-was-implemented) | inspiration | Not a software project: the announcements of the power exchanges about the move of the single day-ahead coupling to a 15-minute market time unit. Listed because it is the reference fact for mixed resolutions. |
| [entsoeapi (R, krose)](https://krose.github.io/entsoeapi/articles/working-with-eic-codes.html) | inspiration | R client for the ENTSO-E Transparency Platform with functions that download the official EIC code lists as tables. |
| [PyPSA-Eur: build_bidding_zones rule](https://pypsa-eur.readthedocs.io/en/latest/preparation/) | not-relevant | A rule of the PyPSA-Eur workflow that builds one geojson of European bidding zones by merging the shapes of electricitymaps-contrib and of entsoe-py. |
| [Transparency Energy Knowledge Graph (TEKG, Ontotext)](https://transparency.ontotext.com/spec/glossary.html) | inspiration | A 2022 research project that converted ENTSO-E Transparency Platform data to an RDF knowledge graph, with a glossary and a specification of the model. |
| [QUDT, UCUM and pint (unit vocabularies)](https://github.com/qudt/qudt-public-repo) | reuse-as-component | Three ways to write a unit so that a machine can read it: QUDT (RDF ontology with URIs per unit), UCUM (a string grammar, used in data exchange), pint (Python registry that parses unit strings; pint-pandas for DataFrame dtypes). |
| [ENTSO-E Detailed Data Descriptions and Manual of Procedures](https://eepublicdownloads.entsoe.eu/clean-documents/mc-documents/transparency-platform/MOP/DetailedDescriptionDocument.pdf) | reuse-as-component | The official definition of each data item of the Transparency Platform (total load, day-ahead prices, physical flows, net positions, imbalance prices and volumes ...), part of the Manual of Procedures. |
| [entsoe-apy (BerriJ)](https://pypi.org/project/entsoe-apy/0.4.0/) | not-relevant | A newer Python client for the ENTSO-E Transparency Platform whose package structure mirrors the official API documentation (for example entsoe.Market.EnergyPrices for item 12.1.D). |

### gap:source-terms-bulk-channels-and-existing-mirrors

Main challenge to the spec: licences are per dataset and several are not open. Per a third-party reading of ENTSO-E's free re-use list (primary page returned 403), day-ahead prices, actual load and generation per type are NOT on the CC-BY 4.0 list. JAO terms (read) allow only "own internal purposes", forbid making content available to third parties, and forbid sharing the API token. Energy-Charts prices are "private and internal use only" outside 16 SMARD zones. So Adele is defensible as a mirror inside one organisation, not across organisations. Add to each descriptor: licence, attribution string, redistribution scope. Ingestion: use the ENTSO-E File Library (SFTP is discontinued), not the REST API. For the ETA of the next refresh, JAO itself recommends polling its monitoring/metadata endpoints around deadlines. No complete Parquet mirror exists. hsilvosa/entsoe-observatory is the closest prior art; Ember and Energinet are clean CC-BY backfills.

| Project | Verdict | What |
|---|---|---|
| [ENTSO-E Transparency Platform (terms of use, free re-use list, File Library, API rate limit)](https://eepublicdownloads.entsoe.eu/clean-documents/mc-documents/transparency-platform/ENTSOE_Transparency_Terms_Conditions.pdf) | reuse-as-component | The primary source for most Adele datasets. Governed by General Terms and Conditions plus a separate 'List of Data Available for Free Re-use' (CC-BY 4.0) published at https://transparencyplatform.zendesk.com/hc/en-us/articles/40921911218961-Legal-Terms-and-Conditions. |
| [JAO Publication Tool (PuTo) and JAO terms of use](https://www.jao.eu/news/publication-tool-access-parameters) | reuse-as-component | Source of flow-based domain data, capacities and auction results for Core, Nordic and Italy North. JAO published access parameters in Oct/Nov 2025 and has General Terms and Conditions for the Use of the Information Systems. |
| [Energy-Charts API (Fraunhofer ISE)](https://api.energy-charts.info/llms.txt) | inspiration | Public JSON API for German and European generation, load and day-ahead prices. It publishes an llms.txt file for agents and returns a licence field in each response. |
| [SMARD (Bundesnetzagentur)](https://www.smard.de/en/datennutzung) | reuse-as-component | German regulator's market data portal. It republishes ENTSO-E data after verification, with a download centre and an undocumented JSON endpoint. |
| [hsilvosa/entsoe-observatory](https://github.com/hsilvosa/entsoe-observatory) | inspiration | A one-person, low-cost data platform: ENTSO-E day-ahead prices (A44) and actual load (A65) for 51 bidding zones from 2015, with Open-Meteo weather and ECB rates, in Hive-partitioned zstd Parquet on Cloudflare R2, with DuckDB as the main engine. Published on Hugging Face. |
| [entsoe-mcp (entsoemcp.com) and its licensing page](https://entsoemcp.com/licensing) | inspiration | A free hosted service by one person that exposes European power-market data (47 zones, 45 endpoint families, 120M+ rows) to AI agents over MCP, with CSV/Parquet export. Its licensing page is the most precise per-source licence table that I found. |
| [Swissgrid grid data (Energy Statistic Switzerland, control area balance)](https://www.swissgrid.ch/en/home/customers/topics/energy-data-ch.html) | reuse-as-component | Swiss TSO publications: one XLSX per year with 15-minute aggregates (2009 to 2026), plus CSV/XLSX files for control area balance and total system imbalance. |
| [Elexon Insights Solution (BMRS) API](https://developer.data.elexon.co.uk) | reuse-as-component | GB balancing and settlement data API that replaced the old BMRS (switched off 31 May 2024), with the IRIS push service for near real-time data. |
| [Ember - European wholesale electricity price data](https://ember-energy.org/data/european-wholesale-electricity-price-data) | reuse-as-component | Cleaned hourly, daily and monthly day-ahead prices per European country, compiled from ENTSO-E, EMR (UK) and SEMOpx, as CSV and ZIP downloads. |
| [Open-Meteo (API terms and AWS Open Data bucket)](https://github.com/open-meteo/open-data) | reuse-as-component | Weather API with a free non-commercial tier, plus the full database published on AWS Open Data (s3://openmeteo, us-west-2) and a Docker image to sync and serve it locally. |
| [Energinet Energi Data Service](https://www.energidataservice.dk/terms-and-conditions) | reuse-as-component | Danish TSO open data portal with a free API for prices, production, flows and balancing data (DK and some Nordic series). |
| [entsoe-py (EntsoeFileClient) and entsoe.file.api](https://github.com/EnergieID/entsoe-py) | reuse-as-component | The standard Python client for the ENTSO-E API. It now contains a 'files' subpackage with EntsoeFileClient for the File Library. entsoe.file.api is an R wrapper for the same File Library API. |
| [jao-py (and the fb.amunmirror.eu mirror)](https://github.com/fboerman/jao-py) | reuse-as-component | Python wrapper for JAO: the web service API and the publication tools for Core day-ahead, Core intraday, Nordic and Italy North, with pandas clients. |
| [Elpriser datasets on Hugging Face](https://elpriser-readme.static.hf.space/index.html) | inspiration | Per-country Parquet datasets (DK, DE-LU, NO1-5, SE1-4, FI, NL) with day-ahead prices, generation per type, load, forecasts, installed capacity and interconnector flows, from Energinet and ENTSO-E. |
| [Open Power System Data and awesome-european-energy-data](https://open-power-system-data.org/) | inspiration | OPSD is the earlier academic data platform that packaged European time series as Frictionless Data Packages (CSV, JSON metadata, SQLite). awesome-european-energy-data (https://github.com/whipeeer-creator/awesome-european-energy-data) is a 2026 curated list of sources per TSO with access notes and pitfalls. |

### gap:whole-system-lookalikes-in-practice

No public write-up was found from an energy trader, utility or TSO (Octopus, Tibber, Statkraft, Axpo, Alpiq, BKW, Vattenfall, Uniper, RWE...) of the full combination (fetchers --> Parquet --> DuckDB + catalog with units and grain + bitemporal + agent interface). Only vendor case studies exist. The closest working system is PUDL: Parquet + Frictionless descriptor + an official agent skill, no MCP. It validates Adele's catalog and skill choices, and its generic "datapackage" skill may be reusable. Commercial vendors (Modo, Energy Aspects, S&P) all chose hosted MCP. Challenges to the spec: (1) a fixed as_of is not enough for backtests; Grid Status offers a cutoff relative to each delivery time; (2) fetched_at is not knowledge time: store the source's issue time and a source tag too; (3) daily products need the timezone that defines the day; (4) add usage warnings, verified example queries, an owner and benchmark questions per dataset.

| Project | Verdict | What |
|---|---|---|
| [PUDL (Catalyst Cooperative) + its agent skills (pudl, datapackage)](https://docs.catalyst.coop/pudl/en/stable/data_access.html) | inspiration | Open pipeline for US energy data (EIA, FERC, EPA) that publishes Parquet on public S3 with a Frictionless Data Package v2 descriptor, plus an official agent skill (https://github.com/catalyst-cooperative/agent-skills) that teaches coding agents to find tables, read column metadata and load the Parquet. |
| [Grid Status (hosted API, dataset metadata, publish-time model, Snowflake listing)](https://docs.gridstatus.io/developers/concepts/publish-time.md) | inspiration | Commercial US power market data service (about 500 datasets from the ISOs) with a REST API, a Python client, a Snowflake Marketplace listing, and docs published as llms.txt and per-page markdown for agents. |
| [S&P Global Energy: Genie agents + MCP over structured commodity data (Databricks blog, 2026-09-25)](https://www.databricks.com/blog/data-dialogue-how-sp-global-energy-made-its-structured-data-estate-conversational-databricks) | inspiration | Write-up by a data vendor on how it exposed its structured energy data to LLM agents: one narrow text-to-SQL agent per group of tables, each exposed as an MCP server, composed per commodity by a FastMCP proxy. |
| [timedb and EnergyDB (rebase.energy)](https://github.com/rebase-energy/timedb) | inspiration | Open-source Python client and schema for energy time series with three time dimensions (valid_time, knowledge_time, change_time), stored in ClickHouse; EnergyDB adds a Postgres catalog of assets and series with units. |
| [Energy Quantified (Montel) Python client and data model](https://energyquantified-python.readthedocs.io/en/latest/userguide/terminology.html) | inspiration | Commercial European power market data API (Montel) with a Python client. Its data model classifies each curve by storage type and identifies each forecast by issue time and tag. |
| [endjin: 'Auditing UK energy policy without a cluster' (DuckCon talk, published 2026-06-29)](https://endjin.com/what-we-think/talks/auditing-uk-energy-policy-without-a-cluster) | inspiration | Short talk by Barry Smart (endjin) on a laptop-scale analysis of UK public energy data: Python ingestion, data contracts, Parquet, DuckDB with bronze, silver and gold schemas, built with help from Claude Code. |
| [Energy Aspects MCP server](https://mcp.energyaspects.com/doc) | inspiration | Hosted read-only MCP server from a commodity research firm: 4 tools that search research and time series, with OAuth 2.1. |
| [Modo Energy MCP](https://modoenergy.com/research/en/modo-energy-mcp-benchmarks-forecasts-research) | not-relevant | Battery storage data and research firm that exposes its benchmarks, forecasts, market data and research to Claude, Copilot Studio and Claude Code through its own MCP server. |
| [Luminus and pipeworx mcp-entso-e (community MCP servers for European grid data)](https://github.com/arefiva/luminus) | not-relevant | Open-source MCP servers that wrap ENTSO-E and other public APIs as tools: Luminus lists 48 tools over 25 sources; pipeworx/mcp-entso-e (https://github.com/pipeworx-io/mcp-entso-e) has 5 ENTSO-E tools behind a hosted gateway. |
| [RWE Supply & Trading data lakehouse (Dremio customer case)](https://www.dremio.com/customers/rwe/) | not-relevant | Vendor case study of the analyst data platform at a large energy trader: AWS data lake fed by four core databases, Databricks for transformation and models, Dremio as the single access layer, Alation as catalog. |
| [Open Power System Data: time series data package](https://data.open-power-system-data.org/time_series/) | inspiration | Academic project that published European load, generation and price time series (from ENTSO-E and TSOs) as a versioned data package with datapackage.json, in CSV, XLSX and SQLite. |
| [OEMetadata (Open Energy Platform) and timely-beliefs (Seita)](https://github.com/OpenEnergyPlatform/oemetadata) | inspiration | Two small references from the research community: OEMetadata is an energy metadata standard based on Frictionless Data Package; timely-beliefs (https://github.com/SeitaBV/timely-beliefs) is a pandas data model for forecasts as 'beliefs' with a belief time. |
| [XTDB case study: energy retailer / virtual power plant](https://xtdb.com/case-studies/energy-vpp) | not-relevant | Vendor case study of an unnamed state-owned energy retailer that uses a bitemporal SQL database as the single store for schedules, telemetry and forecasts. |

### gap:agent-evaluation-of-catalog-and-skill

No ready-made tool covers this angle. Adele should build a small harness of its own from known parts. Proposal: 40 tasks (about 10 easy lookups, 25 "trap" tasks where the wrong timezone, unit, grain or revision gives a different number, 5 tasks that must not use Adele), 5 runs per task and per variant, deterministic comparison of result tables, plus a check of the executed SQL. With 40 tasks, only drops of roughly 15 points or more are detectable on the mean, so add a per-task rule. Challenges to the spec: (1) BuySideFlow found point-in-time violations in 50.8% of runs with a correct result, so the score must also inspect the SQL (as_of present); (2) Vercel measured that a skill was not invoked in 56% of cases, so test triggering; (3) `pull` + local DuckDB leaves no server log, so add client-side query logging; (4) the spec has no query log at all.

| Project | Verdict | What |
|---|---|---|
| [Anthropic skill-creator (anthropics/skills)](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md) | reuse-as-component | Official Anthropic skill that creates skills and evaluates them: paired runs with skill vs baseline, graded assertions, a benchmark with mean and standard deviation, and a loop that optimizes the description for triggering. |
| [promptfoo: guide 'Test agent skills'](https://www.promptfoo.dev/docs/guides/test-agent-skills/) | reuse-as-component | Open-source eval runner (YAML config, CLI) with a Claude Agent SDK provider and assertions made for skills. |
| [Inspect AI (UK AI Security Institute)](https://inspect.aisi.org.uk/metrics.html) | reuse-as-component | Python framework for LLM and agent evaluations: datasets, solvers/agents, sandboxes, scorers, metrics, log viewer. |
| [Miller, 'Adding Error Bars to Evals' (Anthropic, arXiv 2411.00640)](https://arxiv.org/abs/2411.00640) | inspiration | Paper with formulas for the uncertainty of an eval score, for the comparison of two variants on the same questions, and for the number of questions and repeats needed. |
| [Anthropic engineering: 'Demystifying evals for AI agents'](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | inspiration | Practical guide (January 2026) on building agent evals: tasks, trials, graders, capability vs regression suites. |
| [Spider 2.0 evaluation suite (xlang-ai/Spider2)](https://github.com/xlang-ai/Spider2/blob/main/spider2-lite/evaluation_suite/evaluate.py) | inspiration | Scoring code of the Spider 2.0 text-to-SQL benchmark: execution accuracy by comparison of the predicted result table with one or several gold tables. |
| [BuySideFlow (arXiv 2611.12966)](https://arxiv.org/abs/2611.12966) | inspiration | November 2026 benchmark of 408 tasks where LLM agents write SQL and SQL-Python workflows on a point-in-time financial database, with an expert audit of the executed workflows. |
| [MotherDuck: 'Trust the agents you build on your data' (Braintrust eval) and 'Claudeception'](https://motherduck.com/videos/text-to-sql-agent-evals/) | inspiration | Two MotherDuck write-ups: a 40-question eval of an agent writing DuckDB SQL through their MCP server, scored with Braintrust, and an analysis of 50 agent traces loaded back into the database. |
| [dbt-llm-sl-bench (dbt Labs)](https://github.com/dbt-labs/dbt-llm-sl-bench) | inspiration | Open benchmark harness of dbt Labs that compares text-to-SQL with the dbt Semantic Layer on 11 questions of the ACME Insurance dataset; results stored in DuckDB. |
| [ClickHouse Agentic Analytics Benchmark / Jev (ClickHouse/data-agent-mnist)](https://clickhouse.com/blog/agentic-analytics-benchmark-jev) | inspiration | October 2026 benchmark of data agents on an 18-table warehouse (201 frozen questions, 136 development questions) with a failure classifier that works from the queries the agent ran. |
| [Vercel: 'AGENTS.md outperforms skills in our agent evals'](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals) | inspiration | Vercel eval (27 January 2026) that compared a skill with a compressed documentation index in AGENTS.md for knowledge absent from training data. |
| [BIRD Mini-Dev (bird-bench/mini_dev)](https://github.com/bird-bench/mini_dev) | inspiration | Small version of the BIRD text-to-SQL benchmark (500 pairs, 780 in V2) with three metrics: execution accuracy, an efficiency score, and Soft F1. |
| [Braintrust](https://docs.braintrust.dev/evaluate/advanced-evaluations.md) | inspiration | Hosted evaluation and tracing platform with a Python/TypeScript SDK (Eval, scorers, experiments, comparison of trials). |
| [LangSmith evaluation (repetitions)](https://docs.langchain.com/langsmith/repetition) | not-relevant | LangChain's hosted evaluation platform; `evaluate()` runs a target over a dataset with evaluators and optional repetitions. |
| [Context-layer ablation on DABStep (arXiv 2609.22259) and Tk-Boost (arXiv 2602.13521)](https://arxiv.org/abs/2609.22259) | inspiration | Two papers on what part of the context given to a data agent improves accuracy: an ablation of a YAML 'data contract' on the DABStep benchmark, and a method that derives corrective knowledge from an agent's observed mistakes on a database. |
