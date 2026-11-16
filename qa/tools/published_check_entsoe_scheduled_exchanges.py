"""Published figures against entsoe_scheduled_exchanges (latest versions): Buckley & Schaefer's yearly
sums of scheduled commercial exchanges for CH (TIB LDM4Energy, DOI 10.71694/1b92fgz8, 2021-2024),
compared with both tables. qa/published_figures_entsoe_scheduled_exchanges.md.
Usage: python published_check_entsoe_scheduled_exchanges.py <data_dir>

UTC years. The differences are printed in GWh; a figure matches within 0.02 GWh (checks.yaml)."""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
for table in ("day_ahead", "total"):
    c.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{d}/entsoe_scheduled_exchanges/{table}/*.parquet') "
              "WHERE superseded_at IS NULL")

TIB = {  # year: (imports, exports, imports netted, exports netted), TWh, CH over all borders
    2021: (33.28380761499999, 29.345362665, 26.377398267500002, 22.4389533175),
    2022: (33.7710441725, 28.847504344999997, 26.438840155, 21.5153003275),
    2023: (31.89447822, 37.26577813, 25.46236054, 30.83366045),
    2024: (27.457757230749998, 41.56687815825, 22.6323983995, 36.741519327),
}
LABELS = ("imports", "exports", "imports netted", "exports netted")
ok = bad = 0
for table in ("day_ahead", "total"):
    print(f"== {table}")
    for y, published in TIB.items():
        w = (f"delivery_start >= TIMESTAMPTZ '{y}-01-01 00:00:00Z' "
             f"AND delivery_start < TIMESTAMPTZ '{y + 1}-01-01 00:00:00Z'")
        gross = c.execute(f"SELECT sum(to_ch * epoch(resolution) / 3600) / 1e6, "
                          f"sum(from_ch * epoch(resolution) / 3600) / 1e6 FROM {table} WHERE {w}").fetchone()
        netted = c.execute(f"""SELECT sum(greatest(imp - exp, 0)) / 1e6, sum(greatest(exp - imp, 0)) / 1e6
            FROM (SELECT border, time_bucket(INTERVAL 1 HOUR, delivery_start) AS hour,
                         avg(from_ch) AS exp, avg(to_ch) AS imp FROM {table} WHERE {w} GROUP BY 1, 2)""").fetchone()
        for label, p, g in zip(LABELS, published, (*gross, *netted)):
            diff = None if g is None else (g - p) * 1e3
            hit = diff is not None and abs(diff) <= 0.02
            ok += hit
            bad += not hit
            print(f"{'ok  ' if hit else 'DIFF'} {y} {label}: published {p} TWh; adele "
                  f"{'none' if g is None else f'{g:.6f} TWh ({diff:+.3f} GWh)'}")
print(f"\n{ok} match, {bad} differ")
