"""Published figures against entsoe_imbalance_volume (latest versions): ElCom's counts of quarter-hours
per bin of Swissgrid's control area balance (CAB), 2017-2025. qa/published_figures_entsoe_imbalance_volume.md.
Usage: python published_check_entsoe_imbalance_volume.py <data_dir>

A86 is an energy per quarter-hour (MWh), CAB a mean power (MW): MW = MWh * 3600 / epoch(resolution).
None of these counts matched on 2026-11-15: A86 is not CAB."""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute(f"CREATE VIEW imb AS SELECT * FROM read_parquet('{d}/entsoe_imbalance_volume/imbalance/*.parquet') "
          "WHERE superseded_at IS NULL")

BINS = [(-5000, -1000), (-1000, -900), (-900, -800), (-800, -700), (-700, -600), (-600, -500),
        (500, 600), (600, 700), (700, 800), (800, 900), (900, 1000), (1000, 5000)]
ELCOM = {  # ElCom, Besondere Ereignisse in der Regelzone Schweiz im Jahr 2025, Tab. 1 (= the reports on 2023, 2024)
    2025: [0, 5, 18, 33, 92, 215, 116, 39, 12, 1, 0, 0], 2024: [33, 24, 24, 67, 91, 212, 68, 34, 10, 8, 1, 7],
    2023: [1, 11, 17, 17, 46, 87, 93, 28, 22, 4, 0, 3], 2022: [4, 3, 4, 3, 28, 107, 39, 5, 1, 0, 2, 0],
    2021: [1, 0, 2, 2, 12, 73, 16, 3, 1, 4, 0, 0], 2020: [2, 0, 2, 2, 1, 19, 10, 0, 1, 0, 0, 0],
    2019: [1, 3, 2, 3, 10, 32, 1, 2, 1, 0, 0, 0], 2018: [1, 0, 0, 0, 9, 38, 11, 5, 1, 2, 4, 0],
    2017: [5, 0, 2, 1, 2, 7, 15, 3, 0, 0, 0, 0],
}
YEAR = {"UTC": "delivery_start >= make_timestamptz({y}, 1, 1, 0, 0, 0, 'UTC') "
               "AND delivery_start < make_timestamptz({y} + 1, 1, 1, 0, 0, 0, 'UTC')",
        "local": "year(delivery_start AT TIME ZONE 'Europe/Zurich') = {y}"}
for y, counts in ELCOM.items():
    for zone, cond in YEAR.items():
        got = [c.execute(f"""SELECT count(*) FROM imb WHERE {cond.format(y=y)}
                             AND imbalance * 3600 / epoch(resolution) >= {lo}
                             AND imbalance * 3600 / epoch(resolution) < {hi}""").fetchone()[0] for lo, hi in BINS]
        same = sum(g == p for g, p in zip(got, counts))
        print(f"{y} {zone}: {same} of 12 bins equal; ElCom {counts}; adele {got}")
