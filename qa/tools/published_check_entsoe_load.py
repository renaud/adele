"""Published figures of the Swiss load against entsoe_load (latest versions); qa/published_figures_entsoe_load.md. Usage: <data_dir>"""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
for t in ("actual", "forecast"):
    c.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{d}/entsoe_load/{t}/*.parquet') WHERE superseded_at IS NULL")
# the actual load with the stamps as ENTSO-E serves them (end of the hour before 2024-12-31 23:00 UTC)
c.execute("""CREATE VIEW actual_served AS SELECT * REPLACE (CASE WHEN delivery_start < TIMESTAMPTZ '2024-12-31 22:00:00Z'
             THEN delivery_start + INTERVAL 1 HOUR ELSE delivery_start END AS delivery_start) FROM actual""")


def one(sql):
    return c.execute(sql).fetchone()[0]


ok = bad = 0


def cmp(label, published, got, tol, src):
    global ok, bad
    match = got is not None and abs(float(got) - published) <= tol
    ok += match
    bad += not match
    print(f"{'ok  ' if match else 'DIFF'} {label}: published {published}, adele {got if got is None else round(float(got), 3)} ({src})")


# ENTSO-E Statistical Factsheets 2019-2025 (TP data, UTC hours "HH:00-HH+1:00" = hour starting HH:00)
SFS = {  # year: (TWh, (ENTSO-E peak hour, CH MW), (ENTSO-E low hour, CH MW), (CH max hour, MW), (CH min hour, MW))
    2019: (63.4, ("2019-01-22 18:00", 9609), ("2019-06-02 05:00", 6382), ("2019-01-24 10:00", 9924), ("2019-08-03 03:00", 4333)),
    2020: (62.4, ("2020-01-22 18:00", 9404), ("2020-05-31 05:00", 6418), ("2020-12-01 11:00", 9874), ("2020-05-09 04:00", 4704)),
    2021: (63.5, ("2021-02-11 18:00", 9765), ("2021-08-08 05:00", 5806), ("2021-12-10 11:00", 10242), ("2021-07-27 03:00", 4377)),
    2022: (64.6, ("2022-01-26 18:00", 9731), ("2022-08-14 05:00", 5112), ("2022-01-21 13:00", 10189), ("2022-08-01 06:00", 4510)),
    2023: (60.3, ("2023-12-05 18:00", 9039), ("2023-05-28 05:00", 6553), ("2023-02-08 07:00", 10013), ("2023-02-17 00:00", 3747)),
    2024: (59.6, ("2024-01-10 18:00", 9583), ("2024-05-19 05:00", 4736), ("2024-12-06 08:00", 10437), ("2024-12-05 22:00", 2743)),
    2025: (62.4, ("2025-01-14 18:00", 9496), ("2025-04-20 05:00", 5360), ("2025-01-14 10:00", 10330), ("2025-07-20 03:00", 4219)),
}
for y, (twh, pk, lo, mx, mn) in SFS.items():
    src = f"SFS{y}"
    got = one(f"SELECT sum(load * epoch(resolution) / 3600) / 1e6 FROM actual WHERE year(delivery_start) = {y}")
    cmp(f"{y} net consumption TWh (UTC year)", twh, got, 0.05, src)
    for what, (h, v) in (("at ENTSO-E peak hour", pk), ("at ENTSO-E low hour", lo), ("max hour", mx), ("min hour", mn)):
        served = one(f"SELECT load FROM actual_served WHERE delivery_start = TIMESTAMPTZ '{h}:00Z'")
        moved = one(f"SELECT load FROM actual WHERE delivery_start = TIMESTAMPTZ '{h}:00Z'")
        cmp(f"{y} CH {what} {h} UTC, served stamp", v, served, 0.5, src)
        if moved is not None and abs(moved - v) <= 0.5 and (served is None or abs(served - v) > 0.5):
            print("     (matches at adele's own stamp)")
    cmp(f"{y} CH max of the year (UTC year)", mx[1], one(f"SELECT max(load) FROM actual WHERE year(delivery_start) = {y}"), 0.5, src)
    cmp(f"{y} CH min of the year (UTC year)", mn[1], one(f"SELECT min(load) FROM actual WHERE year(delivery_start) = {y}"), 0.5, src)

# Kazmi & Tao 2022, Table 1, CH: R2 (squared correlation) .74, ME (y - yhat) -68 MW, MAE 416 MW, WAPE 5.84 %
print("\nKazmi & Tao 2022 (published: R2 .74, ME -68, MAE 416, WAPE 5.84):")
for span in ((2015, 2021), (2017, 2021)):
    for name, a in (("adele stamps", "actual"), ("served stamps", "actual_served")):
        r = c.execute(f"""SELECT round(corr(a.load, f.load) ^ 2, 3), round(avg(a.load - f.load), 1), round(avg(abs(a.load - f.load)), 1),
                                 round(100 * sum(abs(a.load - f.load)) / sum(abs(a.load)), 2), count(*)
                          FROM {a} a JOIN forecast f USING (bidding_zone, delivery_start)
                          WHERE year(f.delivery_start) BETWEEN {span[0]} AND {span[1]}""").fetchone()
        print(f"  {span[0]}-{span[1]}, {name}: R2 {r[0]}, ME {r[1]}, MAE {r[2]}, WAPE {r[3]}, hours {r[4]}")

# Tzortzis et al. 2023, Table 2, CH: sNaive(168) MAPE 6.25 % in the test year 2021 (local time)
print("\nTzortzis et al. 2023 (published: sNaive(168) MAPE 6.25 %, 2021, local time):")
for tz in ("Europe/Zurich", "UTC"):
    r = one(f"""SELECT round(100 * avg(abs(a.load - p.load) / a.load), 2) FROM actual a JOIN actual p
                ON p.delivery_start = a.delivery_start - INTERVAL 168 HOUR
                WHERE year(a.delivery_start AT TIME ZONE '{tz}') = 2021""")
    print(f"  year in {tz}: {r}")
print(f"\n{ok} match, {bad} differ")
