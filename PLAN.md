# adele: plan

Written 2026-11-15. The datasets are listed in `docs/datasets-inventory.md`, the detail of each
step is in `TODOs.md`, the reasons are in `DECISIONS.md`.

## Work packages

| | name | what it is |
|---|---|---|
| WP1 | Server | Install adele on the server with one timer per dataset, and let it fetch unattended for a week. |
| WP2 | Table shapes | Build tables without a time column (D22) and tables by calendar day, month or year (D26). |
| WP3 | Versions | Build `append-only` and `as_of`: adele keeps every version of a value, not only the latest. |
| WP4 | Files that the source overwrites or revises | Keep each raw answer, and compare a whole file at each fetch. |
| WP5 | Datasets that fit today | Write the descriptor and the `fetch.py` of each dataset that needs nothing new, and backfill it on the server. |
| WP6 | Datasets that wait for WP2 to WP4 | The same for the other datasets, as each of WP2 to WP4 is done. |
| WP7 | Curation | For each dataset, Renaud writes or accepts what the data means in its `datapackage.yaml`. |
| WP8 | QA with published figures | For each dataset, figures published by others become checks that run after each fetch. |
| WP9 | Use at work | Each team member has the CLI, the skill and a key, and answers a first real question with adele. |

## Order and state

| | state on 2026-11-15 | depends on |
|---|---|---|
| WP1 | steps 0-5 done: adele runs on the server (`/opt/adele`, commit 32237db), both datasets backfilled (their figures match the Mac), one timer per dataset since 16:11 UTC, memory limits on the fetch units. Running: the week (step 7, from 2026-11-15). Next: HTTPS (step 6), faults on purpose (step 8). `docs/work-packages/WP1-server.md` | Renaud: the port for HTTPS |
| WP2 | decided, not built. First the `adele:` block per table | |
| WP3 | built and in `main`: `revisions: append-only`, the views `<table>` and `<table>_versions`, `as_of` (D30, storage with `superseded_at`). First dataset `entsoe_load` (CH load, actual and day-ahead), backfilled on the Mac. Measured which ENTSO-E series are revised (`qa/revisions_entsoe_ch.md`). Next: `entsoe_load` on the server for 1-2 days (`TODOs.md`, V1). `docs/work-packages/WP3-versions.md` | WP1 done, for the server |
| WP4 | decided: two datasets for Swissgrid's TSI. Open: raw answers kept (G4), whole files (G6), who takes over from the poller | WP3 for the Swissgrid files |
| WP5 | 3 of 30 datasets are in adele | WP1 for the backfill on the server |
| WP6 | started with WP3: `entsoe_load`. Next (agreed by Renaud): the datasets of the revised ENTSO-E series, generation, flows, schedules, imbalance volume; whether flows and schedules leave WP5 is open (`TODOs.md`) | WP2, WP3, WP4 |
| WP7 | weathernext3 accepted; day-ahead prices open on Renaud's side; `entsoe_load` drafted by Claude at Renaud's request (unit and stamps confirmed by him) | each dataset of WP5 and WP6 |
| WP8 | day-ahead prices: 82 figures as checks; `entsoe_load`: 50 (ENTSO-E's Statistical Factsheets 2019-2025, two papers) | each dataset of WP5 and WP6 |
| WP9 | deployed 2026-11-23: HTTPS on 8443, limits on queries, instructions for users (D35 to D38). Next: first user outside the team | |

Updated 2026-11-15 evening: WP1 runs its week on the server, WP3 is built (it reaches the server
once WP1 is done). WP2 and WP4 are builds in the server and can run next to them. WP7 and WP8
go with each dataset. WP9 can start as soon as the first datasets answer on the server.

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

Measured 2026-11-15 (`qa/revisions_entsoe_ch.md`): of the ENTSO-E series counted as fitting
today, the physical flows and the scheduled exchanges are revised after publication, so
`append-only` would keep what `overwrite` loses; and the CH load, counted as waiting for
versions, was not revised in 15 days (it is in adele anyway, as `entsoe_load`).

## Done when

- Every dataset of swiss_energy_data and swissgrid_project that is in scope is installed in adele
  on the server and fetched on its schedule.
- Each dataset has its `datapackage.yaml`, and its curation is good or on its way.
- The QA of each dataset is done with published figures: numbers published by others that the
  data must reproduce. It is a lazy and cheap QA, and still a very effective one.
- We can start using adele for work.
