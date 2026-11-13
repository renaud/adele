# SQL table names: should the dataset id appear in the SQL?

Status: decided 2026-11-13: option A (DECISIONS.md, D8). The recommendation below (C) was
the first one and was not kept.

## Why the question comes up

All datasets sit behind one SQL connection on the server, so every table needs a name that is
unique there. Two cases force a decision:

1. **Two datasets have a table with the same name.** `entsoe_day_ahead_prices` and
   `entsoe_imbalance_prices` can both have a table `prices`. Then `FROM prices` is ambiguous,
   even in a query that touches only one dataset.
2. **Joins across datasets.** Many questions need two datasets in one query (price against
   load, price against wind generation).

A third requirement holds for every option: the same SQL must run on the server (`adele query`)
and on a local copy (after `pull`).

## Example

Question: "In CH, what was the correlation between day-ahead price and actual load in March 2026?"

| Dataset | Table | Columns |
|---|---|---|
| `entsoe_day_ahead_prices` | `prices` | bidding_zone, delivery_start, price |
| `entsoe_actual_load` | `load` | bidding_zone, delivery_start, load_mw |
| `entsoe_imbalance_prices` | `prices` | bidding_zone, delivery_start, price |

Both 15-minute series give about 3,000 rows per table for March.

### A. Qualified names: `<dataset>.<table>`

One DuckDB schema per dataset.

```sql
SELECT corr(p.price, l.load_mw)
FROM entsoe_day_ahead_prices.prices AS p
JOIN entsoe_actual_load.load AS l USING (bidding_zone, delivery_start)
WHERE p.bidding_zone = 'CH'
  AND p.delivery_start >= '2026-03-01 00:00+01:00'
  AND p.delivery_start <  '2026-04-01 00:00+02:00';
```

### B. One dataset per query, bare table names

`adele query <dataset> "<sql>"`. The table names are those of that dataset only.

```
adele query entsoe_day_ahead_prices "SELECT delivery_start, price FROM prices WHERE ..."
adele query entsoe_actual_load      "SELECT delivery_start, load_mw FROM load WHERE ..."
```

The join cannot run on the server. The agent has to join the two results itself. With a cap of
100 rows (the example in SPEC.md, Agent access), each result here is truncated, so in practice
this question needs `pull` of both datasets and a local join.

### C. One flat namespace: table names unique across the catalog

The server refuses to start if two tables have the same name. Here the imbalance table must be
called something like `imbalance_prices`.

```sql
SELECT corr(p.price, l.load_mw)
FROM day_ahead_prices AS p
JOIN actual_load AS l USING (bidding_zone, delivery_start)
WHERE p.bidding_zone = 'CH'
  AND p.delivery_start >= '2026-03-01 00:00+01:00'
  AND p.delivery_start <  '2026-04-01 00:00+02:00';
```

### D. A, plus a default dataset

Qualified names always work. `adele query --dataset X` also lets bare names resolve inside X
(DuckDB `search_path`). The SQL is short when a query touches only one dataset, and joins still
work. Cost: two ways to write the same query. And Security locks the settings, so the server
must set the search path before it locks them (to verify).

## Comparison

| | A qualified | B one dataset per query | C flat, unique | D A + default |
|---|---|---|---|---|
| dataset id in the SQL | always | never | never | only in joins |
| join across datasets on the server | yes | no | yes | yes |
| name collisions | impossible | impossible | refused at startup | impossible |
| same SQL locally and remotely | yes | yes, if the client scopes local queries the same way | yes | yes, if the client sets the same default |
| what the agent must get right | copy names from `describe` | which dataset each query targets | copy names from `describe` | which of the two rules applies |

## Recommendation

C. It keeps the dataset id out of the SQL and still allows joins on the server. The price is one
rule ("table names are unique across the catalog") that the server checks at startup, which
fits the principle "declared means checked". With a dozen datasets, the rule costs nothing.

In practice, C makes table names carry the source (`entsoe_day_ahead_prices`,
`epex_day_ahead_prices`), so for single-table datasets the table name and the dataset id end up
almost the same.

## Open

- Constraint for any option: Frictionless names must match `^[-a-z0-9._/]+$` (checked with
  frictionless-py 5.21.0 on 2026-11-12), and unquoted SQL identifiers can't contain `-`, `.`
  or `/`. So dataset and table names should use `[a-z0-9_]` only.
- Naming convention for tables under C (e.g. table name = dataset id for single-table datasets).
- Reference tables shared by several datasets (bidding zones): one dataset of their own
  (`ref_bidding_zones`) rather than a copy in each dataset that uses them?
