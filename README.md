# Adele: *a*gentic *d*ata *l*ayer

Expose datasets to agents for them to consume data efficiently and clearly: agents know without ambiguity what a dataset is about, its fields & data type, the timeframe of the dataset (since when, till when, ETA for next refresh). It also knows how to fetch the dataset, either remotely (query adele on the fly) or by copying the dataset locally.

## Principles

- Quality over quantity: manually curated datasets that agents can "trust".
- Docs as files, data through SQL: agents get yaml descriptions of datasets, then query them with SQL.
- Nothing happens silently: no silent schema change, no silent truncation, no stale data served as fresh.
- Declared means checked: whatever a descriptor states (grain, types, codes, examples), it has been written by a human expert and the server verifies against the data.
- One convention for all datasets: time, units and codes are normalized at ingestion, so an agent learns the rules once.
- Boring standards: Parquet, DuckDB SQL, Frictionless: formats that agents already know, nothing invented.

## Current Usecase

- a dozen different publicly available datasets on electricity markets
- some updated daily, some every 15m.
- most datasets that get downloaded consist of files: parquet, SQL databases, csv, xlsx, etc; some are exposed through an api
- almost all datasets are tabular (or at least relational)
