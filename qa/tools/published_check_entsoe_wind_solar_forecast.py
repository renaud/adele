"""Published figures of the Swiss wind and solar forecasts against entsoe_wind_solar_forecast (latest
versions); qa/published_figures_entsoe_wind_solar_forecast.md.

Usage: <data_dir> [<actual.parquet>]

The forecast-only figures need nothing else. The error figures need ENTSO-E's actual generation
(A75): from <data_dir>/entsoe_generation (WP5.2) when it exists, else from <actual.parquet>, a file
with columns datetime (UTC, start), psr_type (B16, B19), value_mw, such as
swissgrid_project/data/entsoe/generation.parquet (the same series, downloaded 2026-10-31).
"""
import sys
from pathlib import Path

import duckdb

d = Path(sys.argv[1])
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{d}/entsoe_wind_solar_forecast/forecast/*.parquet') "
          "WHERE superseded_at IS NULL")
gen = d / "entsoe_generation" / "generation"
if gen.exists():
    c.execute(f"CREATE VIEW actual AS SELECT production_type, delivery_start, generation AS y "
              f"FROM read_parquet('{gen}/*.parquet') WHERE superseded_at IS NULL AND bidding_zone = 'CH'")
    actual_src = str(gen)
elif len(sys.argv) > 2:
    c.execute(f"""CREATE VIEW actual AS SELECT CASE psr_type WHEN 'B16' THEN 'solar' ELSE 'wind_onshore' END AS production_type,
                  datetime AS delivery_start, value_mw AS y FROM read_parquet('{sys.argv[2]}') WHERE psr_type IN ('B16', 'B19')""")
    actual_src = sys.argv[2]
else:
    actual_src = None
print(f"actual generation: {actual_src or 'none (error figures skipped)'}\n")

ok = bad = 0


def cmp(label, published, got, tol, src):
    global ok, bad
    match = got is not None and abs(float(got) - published) <= tol
    ok += match
    bad += not match
    print(f"{'ok  ' if match else 'DIFF'} {label}: published {published}, adele {got if got is None else round(float(got), 3)} ({src})")


def one(sql):
    return c.execute(sql).fetchone()[0]


# Zsiborács et al. 2022, Sustainability 14:16446, Table 3: completeness (%) of the day-ahead onshore wind
# forecast of CH, hourly. Their share also drops the hours without an actual value; computed here both ways.
Z3 = {2015: 99.2, 2016: 99.4, 2017: 99.7, 2018: 100, 2019: 100, 2020: 100, 2021: 100}
for tz in ("UTC", "Europe/Zurich"):
    print(f"Zsiborács Table 3, CH day-ahead wind onshore, {tz} years:")
    for y, pub in Z3.items():
        hours = one(f"SELECT epoch(TIMESTAMPTZ '{y + 1}-01-01 00:00:00 {tz}' - TIMESTAMPTZ '{y}-01-01 00:00:00 {tz}') / 3600")
        where = (f"f.forecast_type = 'day_ahead' AND f.production_type = 'wind_onshore' "
                 f"AND f.delivery_start >= TIMESTAMPTZ '{y}-01-01 00:00:00 {tz}' AND f.delivery_start < TIMESTAMPTZ '{y + 1}-01-01 00:00:00 {tz}'")
        fc = 100 * one(f"SELECT count(*) FROM f WHERE {where}") / hours
        cmp(f"{y} share of hours with a forecast", pub, fc, 0.05, "Zsiborács 2022 T3")
        if actual_src:
            both = 100 * one(f"SELECT count(*) FROM f JOIN actual a USING (production_type, delivery_start) WHERE {where}") / hours
            print(f"     with an actual value too: {both:.2f}")
    print()

# Zsiborács et al. 2023, IEEE Access 11:74953, Table 2: the same for the day-ahead solar forecast of CH
# (an image in the PDF, read by eye at 300 dpi).
Z23 = {2015: 99.5, 2016: 99.5, 2017: 99.7, 2018: 100, 2019: 100, 2020: 100, 2021: 100, 2022: 100}
print("Zsiborács 2023 Table 2, CH day-ahead solar, local years:")
for y, pub in Z23.items():
    hours = one(f"SELECT epoch(TIMESTAMPTZ '{y + 1}-01-01 00:00:00 Europe/Zurich' - TIMESTAMPTZ '{y}-01-01 00:00:00 Europe/Zurich') / 3600")
    where = (f"f.forecast_type = 'day_ahead' AND f.production_type = 'solar' "
             f"AND f.delivery_start >= TIMESTAMPTZ '{y}-01-01 00:00:00 Europe/Zurich' AND f.delivery_start < TIMESTAMPTZ '{y + 1}-01-01 00:00:00 Europe/Zurich'")
    cmp(f"{y} share of hours with a forecast", pub, 100 * one(f"SELECT count(*) FROM f WHERE {where}") / hours, 0.05, "Zsiborács 2023 T2")
    if actual_src:
        both = 100 * one(f"SELECT count(*) FROM f JOIN actual a USING (production_type, delivery_start) WHERE {where}") / hours
        print(f"     with an actual value too: {both:.2f}")
print()

if actual_src:
    # Zsiborács et al. 2023, Table 6: CH solar, day-ahead, the same regulation needs as Table A5 below
    T6 = {2015: (9.4, 37.5), 2016: (8.5, 20.0), 2017: (4.6, 16.6), 2018: (4.6, 42.7), 2019: (5.3, 12.0)}
    print("Zsiborács 2023 Table 6, CH day-ahead solar, local years (actual above forecast, forecast above actual):")
    for y, (down, up) in T6.items():
        r = c.execute(f"""SELECT 100 * sum(greatest(a.y - f.generation, 0)) / sum(a.y), 100 * sum(greatest(f.generation - a.y, 0)) / sum(a.y)
                          FROM f JOIN actual a USING (production_type, delivery_start)
                          WHERE f.forecast_type = 'day_ahead' AND f.production_type = 'solar'
                            AND year(f.delivery_start AT TIME ZONE 'Europe/Zurich') = {y}""").fetchone()
        cmp(f"{y} downward need, %", down, r[0], 0.05, "Zsiborács 2023 T6")
        cmp(f"{y} upward need, %", up, r[1], 0.05, "Zsiborács 2023 T6")
    print()

    # Zsiborács et al. 2022, Table A5: CH onshore wind, day-ahead. "Downward regulation need" = the
    # energy produced above the forecast, "upward" = the forecast energy not produced, each as a share
    # of the year's actual energy (Yang et al. 2020); which is which is checked both ways here.
    A5 = {2015: (18.9, 46.1), 2016: (22.8, 36.1), 2017: (17.6, 29.6), 2018: (15.5, 67.9), 2019: (41.5, 8.9)}
    for tz in ("UTC", "Europe/Zurich"):
        print(f"Zsiborács Table A5, CH day-ahead wind onshore, {tz} years (actual above forecast, forecast above actual):")
        for y, (down, up) in A5.items():
            r = c.execute(f"""SELECT 100 * sum(greatest(a.y - f.generation, 0)) / sum(a.y), 100 * sum(greatest(f.generation - a.y, 0)) / sum(a.y)
                              FROM f JOIN actual a USING (production_type, delivery_start)
                              WHERE f.forecast_type = 'day_ahead' AND f.production_type = 'wind_onshore'
                                AND year(f.delivery_start AT TIME ZONE '{tz}') = {y}""").fetchone()
            cmp(f"{y} downward need, %", down, r[0], 0.05, "Zsiborács 2022 A5")
            cmp(f"{y} upward need, %", up, r[1], 0.05, "Zsiborács 2022 A5")
        print()

    # Kazmi & Tao 2022, Applied Energy 323:119565, Tables 2 (wind) and 3 (solar), CH, 2017-2021, hourly,
    # ME = mean(actual - forecast). They dropped missing and "anomalous" values with a filter they don't describe.
    print("Kazmi & Tao 2022, CH day-ahead, 2017-2021 (published: wind ME 5.6, MAE 8.9, wMAPE 83, R2 0; "
          "solar ME 97, MAE 109.8, WAPE 78.3, R2 0.27):")
    for pt in ("wind_onshore", "solar"):
        r = c.execute(f"""SELECT count(*), avg(a.y - f.generation), avg(abs(a.y - f.generation)),
                                 100 * sum(abs(a.y - f.generation)) / sum(abs(a.y)), corr(a.y, f.generation) ^ 2
                          FROM f JOIN actual a USING (production_type, delivery_start)
                          WHERE f.forecast_type = 'day_ahead' AND f.production_type = '{pt}'
                            AND year(f.delivery_start) BETWEEN 2017 AND 2021""").fetchone()
        print(f"     {pt}: n {r[0]}, ME {r[1]:.1f}, MAE {r[2]:.1f}, WAPE {r[3]:.1f}, R2 {r[4]:.3f}")
    pub = {"wind_onshore": (5.6, 8.9, 83, 0), "solar": (97, 109.8, 78.3, 0.27)}
    for pt, (me, mae, wape, r2) in pub.items():
        r = c.execute(f"""SELECT corr(a.y, f.generation) ^ 2 FROM f JOIN actual a USING (production_type, delivery_start)
                          WHERE f.forecast_type = 'day_ahead' AND f.production_type = '{pt}'
                            AND year(f.delivery_start) BETWEEN 2017 AND 2021""").fetchone()
        cmp(f"{pt} R2 2017-2021", r2, r[0], 0.005, "Kazmi & Tao 2022 T2-3")

print(f"\n{ok} match, {bad} differ")
