"""Published figures of WP5.1 that are NOT checks: the figures that differ or that come from
other data, recomputed on the stored data (the figures that match are in each dataset's
checks.yaml and run with `adele-server check <id>`). Notes: qa/published_figures_entsoe_*.md.

Usage: python published_check_wp51.py <data_dir>
"""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
for ds, t in [("entsoe_imbalance_prices", "prices"), ("entsoe_imbalance_volume_neighbours", "volumes"),
              ("entsoe_balancing_state", "state")]:
    latest = "WHERE superseded_at IS NULL" if ds != "entsoe_balancing_state" else ""
    c.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{d}/{ds}/{t}/*.parquet') {latest}")


def one(sql):
    return c.execute(sql).fetchone()[0]


print("ElCom, Besondere Ereignisse 2025, Tabelle 2 (figures left out of checks.yaml):")
for year, col, thr, published in [(2023, "price_short", 2000, 29), (2025, "price_short", 1000, 60),
                                  (2025, "price_long", 1000, 196), (2025, "price_long", 2000, 50),
                                  (2025, "price_long", 3000, 11)]:
    got = one(f"""SELECT count(*) FROM prices WHERE area = 'CH' AND abs({col}) > {thr}
                  AND year(delivery_start AT TIME ZONE 'Europe/Zurich') = {year}""")
    print(f"  {year} |{col}| > {thr}: published {published}, adele {got}")

print("\nElCom, Tabelle 4, the single quarter-hours that differ (local start of the quarter-hour):")
for local, lo, sh in [("2025-02-12 14:00", 60, 5566), ("2025-06-21 15:45", -85, 136), ("2025-09-21 13:00", 8, 469)]:
    r = c.execute(f"""SELECT price_long, price_short FROM prices WHERE area = 'CH'
                      AND delivery_start = TIMESTAMPTZ '{local}:00 Europe/Zurich'""").fetchone()
    print(f"  {local}: published long {lo} short {sh}, adele {r}")

print("\nENTSO-E Balancing Report 2020, France 2018-2019 (published: +390 / -350 MWh, 55 % / 45 %):")
r = c.execute("""SELECT avg(imbalance) FILTER (imbalance > 0), avg(imbalance) FILTER (imbalance < 0),
                        100.0 * count(*) FILTER (imbalance > 0) / count(*), 100.0 * count(*) FILTER (imbalance < 0) / count(*)
                 FROM volumes WHERE area = 'FR' AND year(delivery_start AT TIME ZONE 'Europe/Paris') IN (2018, 2019)""").fetchone()
print("  adele: mean positive %.1f, mean negative %.1f, share positive %.1f %%, share negative %.1f %%" % r)

print("\nENTSO-E LFC annual reports, block SG (FRCE of Swissgrid, 15-minute means) against adele's B33 15-minute means:")
ALFC = {  # period: mean, sd, p1, p5, p10, p90, p95, p99 as printed
    "2020": (-0.1, 7, -18, -11, -7, 6, 9, 15), "2021": (-0.1, 7, -19, -11, -7, 7, 9, 15),
    "2022": (-0.1, 6, -19, -11, -7, 7, 9, 15), "2023": (0.0, 8, -18, -11, -7, 6, 9, 14),
    "2024": (0.3, 14, -17, -10, -7, 6, 9, 15), "2025-01": (-0.2, 5, -15, -10, -6, 6, 8, 14),
    "2025-02": (0.1, 10, -23, -16, -10, 10, 15, 30), "2025-03": (0.1, 5, -15, -8, -6, 6, 8, 14),
    "2025-04": (0.1, 5, -15, -8, -5, 5, 8, 13), "2025-05": (0.1, 5, -15, -8, -6, 6, 8, 15),
}
c.execute("""CREATE VIEW q AS SELECT time_bucket(INTERVAL 15 MINUTE, delivery_start) AS t, avg(control_error) AS v
             FROM state GROUP BY 1""")
for period, pub in ALFC.items():
    cond = (f"year(t AT TIME ZONE 'Europe/Zurich') = {period}" if len(period) == 4
            else f"strftime(t AT TIME ZONE 'Europe/Zurich', '%Y-%m') = '{period}'")
    got = c.execute(f"""SELECT avg(v), stddev_pop(v), quantile_cont(v, 0.01), quantile_cont(v, 0.05), quantile_cont(v, 0.10),
                               quantile_cont(v, 0.90), quantile_cont(v, 0.95), quantile_cont(v, 0.99) FROM q WHERE {cond}""").fetchone()
    worst = max(abs(g - p) for g, p in zip(got[2:], pub[2:]))
    print(f"  {period}: published {pub}; adele " + ", ".join(f"{g:.1f}" for g in got) + f"; largest percentile gap {worst:.1f} MW")
