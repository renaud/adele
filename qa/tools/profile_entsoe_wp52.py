"""Profile of the four datasets of WP5.2 as stored (latest versions): per series, the first and last
interval, the periods of each resolution, the holes (intervals missing between the first and the
last), the extremes and the yearly energy (UTC years). Usage: python profile_entsoe_wp52.py <data_dir>"""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")


PATHS = {}


def view(name: str, ds: str, table: str) -> None:
    PATHS[name] = f"{ds}/{table}"
    c.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{d}/{ds}/{table}/*.parquet') WHERE superseded_at IS NULL")


view("gen", "entsoe_generation", "generation")
view("flo", "entsoe_physical_flows", "flows")
view("da", "entsoe_scheduled_exchanges", "day_ahead")
view("tot", "entsoe_scheduled_exchanges", "total")
view("imb", "entsoe_imbalance_volume", "imbalance")

SERIES = {  # name: (view, series key expression, value columns)
    "generation": ("gen", "production_type", ["generation"]),
    "flows": ("flo", "border", ["from_ch", "to_ch"]),
    "scheduled day_ahead": ("da", "border", ["from_ch", "to_ch"]),
    "scheduled total": ("tot", "border", ["from_ch", "to_ch"]),
    "imbalance": ("imb", "control_area", ["imbalance", "mv_minus_sv"]),
}

for name, (v, key, cols) in SERIES.items():
    rows_latest = c.execute(f"SELECT count(*) FROM {v}").fetchone()[0]
    rows_all = c.execute(f"SELECT count(*) FROM read_parquet('{d}/{PATHS[v]}/*.parquet')").fetchone()[0]
    print(f"\n=== {name}: {rows_latest:,} rows, {rows_all:,} versions in the files")
    # periods of each resolution per series (a new period when the resolution changes)
    rows = c.execute(f"""
        WITH r AS (SELECT {key} AS k, delivery_start AS t, resolution AS res,
                          lag(resolution) OVER (PARTITION BY {key} ORDER BY delivery_start) AS prev FROM {v}),
             g AS (SELECT *, sum(CASE WHEN prev IS DISTINCT FROM res THEN 1 ELSE 0 END)
                                 OVER (PARTITION BY k ORDER BY t) AS grp FROM r)
        SELECT k, res, min(t), max(t), count(*) FROM g GROUP BY k, res, grp ORDER BY k, min(t)""").fetchall()
    per_key = {}
    for k, res, a, b, n in rows:
        per_key.setdefault(k, []).append((res, a, b, n))
    for k, periods in per_key.items():
        text = "; ".join(f"{res} {a:%Y-%m-%d %H:%M} .. {b:%Y-%m-%d %H:%M} ({n:,})" for res, a, b, n in periods[:6])
        more = f"; ... {len(periods) - 6} more periods" if len(periods) > 6 else ""
        print(f"  {k}: {text}{more}")
    # holes: an interval whose end is not the start of the next one
    holes = c.execute(f"""
        WITH r AS (SELECT {key} AS k, delivery_start + resolution AS e,
                          lead(delivery_start) OVER (PARTITION BY {key} ORDER BY delivery_start) AS nxt FROM {v})
        SELECT k, e, nxt, nxt - e AS gap FROM r WHERE nxt IS NOT NULL AND nxt <> e ORDER BY gap DESC""").fetchall()
    by_key = {}
    for k, e, nxt, gap in holes:
        by_key.setdefault(k, []).append((e, nxt, gap))
    for k, hs in by_key.items():
        big = ", ".join(f"{e:%Y-%m-%d %H:%M} ({gap})" for e, _, gap in hs[:4])
        print(f"  holes {k}: {len(hs)}, longest from {big}")
    for col in cols:
        ext = c.execute(f"""SELECT {key}, min({col}), max({col}), count(*) FILTER (WHERE {col} IS NULL),
                                   count(*) FILTER (WHERE {col} < 0) FROM {v} GROUP BY 1 ORDER BY 1""").fetchall()
        for k, lo, hi, nulls, neg in ext:
            print(f"  {col} {k}: min {lo}, max {hi}, nulls {nulls:,}, negative {neg:,}")
    for col in cols:
        unit = "TWh" if name != "imbalance" else "GWh of |imbalance|"
        expr = (f"sum({col} * epoch(resolution) / 3600) / 1e6" if name != "imbalance"
                else f"sum(abs({col})) / 1e3")
        ys = c.execute(f"""SELECT year(delivery_start) y, {key}, round({expr}, 3)
                           FROM {v} GROUP BY ALL ORDER BY 2, 1""").fetchall()
        line = {}
        for y, k, val in ys:
            line.setdefault(k, []).append(f"{y}: {val}")
        for k, vals in line.items():
            print(f"  {col} {k} ({unit} per UTC year): {', '.join(vals)}")

# clock changes: the local days of the change must have 23 and 25 hours (92 and 100 quarter-hours)
print("\n=== local days of the clock change (Europe/Zurich), quarter-hours of the imbalance in 2016-2025")
print(c.execute("""SELECT CAST(delivery_start AT TIME ZONE 'Europe/Zurich' AS DATE) d, count(*) FROM imb
                   WHERE strftime(delivery_start AT TIME ZONE 'Europe/Zurich', '%m-%d') BETWEEN '03-25' AND '03-31'
                      OR strftime(delivery_start AT TIME ZONE 'Europe/Zurich', '%m-%d') BETWEEN '10-25' AND '10-31'
                   GROUP BY 1 HAVING count(*) <> 96 ORDER BY 1""").fetchall())
