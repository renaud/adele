# adele: plan

Written 2026-11-15. The datasets are listed in `docs/datasets-inventory.md`, the detail of each
step is in `TODOs.md`, the reasons are in `DECISIONS.md`.

## Work packages

| | name | what it is |
|---|---|---|
| WP1 | Server on steacher1 | Install adele on steacher1 with one timer per dataset, and let it fetch unattended for a week. |
| WP2 | Table shapes | Build tables without a time column (D22) and tables by calendar day, month or year (D26). |
| WP3 | Versions | Build `append-only` and `as_of`: adele keeps every version of a value, not only the latest. |
| WP4 | Files that the source overwrites or revises | Keep each raw answer, and compare a whole file at each fetch. |
| WP5 | Datasets that fit today | Write the descriptor and the `fetch.py` of each dataset that needs nothing new, and backfill it on steacher1. |
| WP6 | Datasets that wait for WP2 to WP4 | The same for the other datasets, as each of WP2 to WP4 is done. |
| WP7 | Curation | For each dataset, Renaud writes or accepts what the data means in its `datapackage.yaml`. |
| WP8 | QA with published figures | For each dataset, figures published by others become checks that run after each fetch. |
| WP9 | Use at work | Each team member has the CLI, the skill and a key, and answers a first real question with adele. |

## Order and state

| | state on 2026-11-15 | depends on |
|---|---|---|
| WP1 | not started. Units drafted and tested once in a container; the fetch per dataset is built (D27) | Renaud: root on steacher1; IT for the ports 80 and 443 |
| WP2 | decided, not built. First the `adele:` block per table | |
| WP3 | not designed in detail (POC 2) | |
| WP4 | decided: two datasets for Swissgrid's TSI. Open: raw answers kept (G4), whole files (G6), who takes over from the poller | WP3 for the Swissgrid files |
| WP5 | 3 of 30 datasets are in adele | WP1 for the backfill on steacher1 |
| WP6 | not started | WP2, WP3, WP4 |
| WP7 | weathernext3 accepted; day-ahead prices open on Renaud's side | each dataset of WP5 and WP6 |
| WP8 | day-ahead prices: 82 figures as checks | each dataset of WP5 and WP6 |
| WP9 | client and skill exist as drafts | WP1, and the first datasets on steacher1 |

WP1 and WP5 start now. WP2, WP3 and WP4 are builds in the server and can run next to them. WP7
and WP8 go with each dataset. WP9 can start as soon as the first datasets answer on steacher1.

## The datasets

The inventory lists 83 datasets. 18 are out of adele (not a table, delivered by hand, copies) and
the derived tables are out for now. About 60 are to install:

| family | fit today (WP5) | wait for versions (WP3) | wait for WP2 or WP4 (one for a bookmark) | not worked out |
|---|---|---|---|---|
| Swissgrid | 1 | | 7 | 2 |
| ENTSO-E | 7 | 6 | 2 | |
| other market sources | 4 | | | |
| PV production and capacity | 3 | 2 | 4 | |
| weather observations | 10 | | 6 | |
| weather forecasts | 5 | | 2 | |
| context tables | | | 2 | |

## Done when

- Every dataset of swiss_energy_data and swissgrid_project that is in scope is installed in adele
  on steacher1 and fetched on its schedule.
- Each dataset has its `datapackage.yaml`, and its curation is good or on its way.
- The QA of each dataset is done with published figures: numbers published by others that the
  data must reproduce. It is a lazy and cheap QA, and still a very effective one.
- We can start using adele for work.
