"""Published figures of the neighbours' wind and solar forecasts against
entsoe_wind_solar_forecast_neighbours (latest versions); qa/published_figures_entsoe_wind_solar_forecast_neighbours.md.

Usage: <data_dir>

Germany as one area: DE_AT_LU until 2018-09-30 22:00 UTC, DE_LU after (the bidding zone), unless a
figure says otherwise.
"""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute("SET memory_limit='8GB'")
c.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{d}/entsoe_wind_solar_forecast_neighbours/forecast/*.parquet') "
          "WHERE superseded_at IS NULL")
c.execute("""CREATE VIEW de AS SELECT * REPLACE ('DE' AS area) FROM f
             WHERE (area = 'DE_AT_LU' AND delivery_start < TIMESTAMPTZ '2018-09-30 22:00:00Z')
                OR (area = 'DE_LU' AND delivery_start >= TIMESTAMPTZ '2018-09-30 22:00:00Z')""")
c.execute("CREATE VIEW g AS SELECT * FROM f UNION ALL SELECT * FROM de")

ok = bad = 0


def cmp(label, published, got, tol, src):
    global ok, bad
    match = got is not None and abs(float(got) - published) <= tol
    ok += match
    bad += not match
    print(f"{'ok  ' if match else 'DIFF'} {label}: published {published}, adele {got if got is None else round(float(got), 3)} ({src})")


def one(sql):
    return c.execute(sql).fetchone()[0]


# 1. Ben Amor & Ziel 2026, arXiv 2512.04690v2, Appendix, Table 7: German day-ahead forecasts, hourly, in GW
#    (labelled MWh); wind = onshore + offshore. Periods 01.10.2018-14.01.2022 and 15.01.2022-13.01.2025,
#    read as local days, end included. How they made hours of quarter-hours is not stated: hourly means here.
BAZ = {("2018-10-01 00:00:00+02", "2022-01-15 00:00:00+01"): {"wind": (14.1, 10.1, 0.2, 6.1, 11.5, 19.9, 47.2),
                                                               "pv": (4.8, 7.6, 0.0, 0.0, 0.1, 7.4, 36.4)},
       ("2022-01-15 00:00:00+01", "2025-01-14 00:00:00+01"): {"wind": (15.4, 11.5, 0.2, 6.0, 12.3, 22.7, 50.3),
                                                               "pv": (6.7, 10.2, 0.0, 0.0, 0.2, 10.7, 48.2)}}
STATS = ("mean", "std", "min", "q25", "median", "q75", "max")
for area in ("DE_LU", "TSO4"):
    for (s, e), series in BAZ.items():
        where_area = "area = 'DE_LU'" if area == "DE_LU" else "area IN ('DE_50HZ', 'DE_AMPRION', 'DE_TENNET', 'DE_TRANSNETBW')"
        r = c.execute(f"""
            WITH q AS (SELECT delivery_start,
                              sum(generation) FILTER (production_type IN ('wind_onshore', 'wind_offshore')) AS wind,
                              sum(generation) FILTER (production_type = 'solar') AS pv
                       FROM f WHERE {where_area} AND forecast_type = 'day_ahead'
                         AND delivery_start >= TIMESTAMPTZ '{s}' AND delivery_start < TIMESTAMPTZ '{e}' GROUP BY 1),
                 h AS (SELECT date_trunc('hour', delivery_start) AS hr, avg(wind) / 1e3 AS wind, avg(pv) / 1e3 AS pv FROM q GROUP BY 1)
            SELECT {', '.join(f'avg({v}), stddev_samp({v}), min({v}), quantile_cont({v}, 0.25), median({v}), quantile_cont({v}, 0.75), max({v})' for v in series)}
            FROM h""").fetchone()
        print(f"Ben Amor & Ziel Table 7, {area}, [{s}, {e}):")
        for i, (v, pub) in enumerate(series.items()):
            for j, (stat, p) in enumerate(zip(STATS, pub)):
                cmp(f"{v} {stat} GW", p, r[7 * i + j], 0.05, "Ben Amor & Ziel 2026 T7")
        print()

# 2. Canaydin, Mascarenhas & Kazmi, "Transparency++", EFC 2025, slide 13: missing values [%] in 2024,
#    DE-LU solar forecast 0.55, wind onshore 0.27; FR solar and wind onshore 0.01. Resolution, zone of the
#    year and the meaning of "missing" not stated: share of the year's time without a value, both years.
T13 = {("DE_LU", "solar"): 0.55, ("DE_LU", "wind_onshore"): 0.27, ("FR", "solar"): 0.01, ("FR", "wind_onshore"): 0.01}
for tz in ("UTC", "Europe/Brussels"):
    for (area, pt), pub in T13.items():
        got = one(f"""SELECT 100 * (1 - sum(epoch(resolution)) / epoch(TIMESTAMPTZ '2025-01-01 00:00:00 {tz}' - TIMESTAMPTZ '2024-01-01 00:00:00 {tz}'))
                      FROM f WHERE area = '{area}' AND forecast_type = 'day_ahead' AND production_type = '{pt}'
                        AND delivery_start >= TIMESTAMPTZ '2024-01-01 00:00:00 {tz}' AND delivery_start < TIMESTAMPTZ '2025-01-01 00:00:00 {tz}'""")
        cmp(f"{area} {pt} day-ahead 2024 ({tz} year), % missing", pub, got, 0.005, "Transparency++ slide 13")
print()
# slide 15: "FR Wind Offshore Forecast Constant Value (240 MW) (Dec 30-Jan 4)", around the turn of 2023-2024
r = c.execute("""SELECT min(generation), max(generation), count(*) FROM f
                 WHERE area = 'FR' AND forecast_type = 'day_ahead' AND production_type = 'wind_offshore'
                   AND delivery_start >= TIMESTAMPTZ '2023-12-30 00:00:00 Europe/Paris' AND delivery_start < TIMESTAMPTZ '2024-01-05 00:00:00 Europe/Paris'""").fetchone()
print(f"FR offshore day-ahead 2023-12-30 to 2024-01-04 (local days): min {r[0]}, max {r[1]}, {r[2]} rows")
cmp("FR offshore day-ahead 2023-12-30 to 2024-01-04, the constant value, MW", 240, r[1] if r[0] == r[1] else None, 0.5,
    "Transparency++ slide 15")
print()

# 3. pv magazine 2026-09-09: actual solar beat the IT day-ahead forecast "on 83 of the 91 days that carried
#    one", June-August 2026 (92 days).
days = one("""SELECT count(DISTINCT CAST(delivery_start AT TIME ZONE 'Europe/Rome' AS DATE)) FROM f
              WHERE area = 'IT' AND forecast_type = 'day_ahead' AND production_type = 'solar'
                AND delivery_start >= TIMESTAMPTZ '2026-06-01 00:00:00 Europe/Rome' AND delivery_start < TIMESTAMPTZ '2026-09-01 00:00:00 Europe/Rome'""")
cmp("IT days of June-August 2026 with a day-ahead solar forecast", 91, days, 0.5, "pv magazine 2026-09-09")
print()

# 4. ENTSO-E & SolarPower Europe 2015, "Solar eclipse March 2015", policy brief, p. 14, column "D) Day-ahead
#    forecast value for PV generation at 12:00 CET (MW)", 2015-03-20. Read as the interval that starts at
#    11:00 UTC. Germany = the four TSO areas; Italy (before the area IT exists) = the zones.
ECL = {"DE (4 TSO areas)": ("area IN ('DE_50HZ', 'DE_AMPRION', 'DE_TENNET', 'DE_TRANSNETBW')", 22000, 500),
       "FR": ("area = 'FR'", 2300, 50), "AT": ("area = 'AT'", 400, 50),
       "IT (zones)": ("area LIKE 'IT\\_%' ESCAPE '\\'", 7500, 250)}
for name, (where, pub, tol) in ECL.items():
    got = one(f"""SELECT sum(generation) FROM f WHERE {where} AND forecast_type = 'day_ahead' AND production_type = 'solar'
                  AND delivery_start = TIMESTAMPTZ '2015-03-20 11:00:00Z'""")
    cmp(f"eclipse 2015-03-20 12:00 CET, {name} day-ahead solar MW", pub, got, tol, "ENTSO-E/SPE 2015 p.14")
print("     (the same table: estimated real PV injection in Italy at 12:00 CET 9,653 MW)\n")

# 5. Zsiborács et al. 2022, Sustainability 14:16446, Tables 3 (onshore) and 4 (offshore): completeness (%) of
#    the day-ahead (DA) and intraday (ID) wind forecasts of each country, "national data" (FR: the bidding
#    zone). Their share also drops the intervals without an actual value, which is not in this dataset:
#    computed here as the share of the year's time with a forecast value.
Z = {("AT", "wind_onshore"): {"day_ahead": {2015: 100, 2016: 99.4, 2017: 100, 2018: 100, 2019: 100, 2020: 100, 2021: 100},
                              "intraday": {2018: 58.2, 2019: 100, 2020: 100, 2021: 100}},
     ("DE", "wind_onshore"): {"day_ahead": {y: 100 for y in range(2015, 2022)},
                              "intraday": {2015: 100, 2016: 100, 2017: 100, 2018: 98.9, 2019: 97.5, 2020: 99.4, 2021: 95.6}},
     ("DE", "wind_offshore"): {"day_ahead": {2015: 99.7, 2016: 100, 2017: 100, 2018: 100, 2019: 100, 2020: 100, 2021: 100},
                               "intraday": {2015: 100, 2016: 100, 2017: 99.7, 2018: 100, 2019: 100, 2020: 100, 2021: 100}},
     ("FR", "wind_onshore"): {"day_ahead": {2015: 99.5, 2016: 97.6, 2017: 99.8, 2018: 99.6, 2019: 99.4, 2020: 98.3, 2021: 98.9},
                              "intraday": {2018: 48.3, 2019: 70.8, 2020: 69.8, 2021: 70.8}},
     ("IT", "wind_onshore"): {"day_ahead": {2020: 4.4, 2021: 98.9}, "intraday": {2021: 98.6}},
     # Zsiborács et al. 2023, IEEE Access 11:74953, Table 2 (PV; an image in the PDF, read by eye at 300 dpi)
     ("AT", "solar"): {"day_ahead": {2015: 100, 2016: 99.5, 2017: 100, 2018: 100, 2019: 100, 2020: 100, 2021: 100, 2022: 100},
                       "intraday": {2018: 58.6, 2019: 100, 2020: 100, 2021: 100, 2022: 100}},
     ("DE", "solar"): {"day_ahead": {2015: 100, 2016: 100, 2017: 100, 2018: 99.4, 2019: 100, 2020: 100, 2021: 100, 2022: 100},
                       "intraday": {2015: 100, 2016: 100, 2017: 100, 2018: 99.2, 2019: 97.5, 2020: 99.2, 2021: 95.9, 2022: 99.2}},
     ("FR", "solar"): {"day_ahead": {2015: 99.6, 2016: 98.5, 2017: 99.4, 2018: 99.4, 2019: 99.1, 2020: 98.3, 2021: 99.1, 2022: 99.5},
                       "intraday": {2018: 48, 2019: 70.3, 2020: 69.3, 2021: 70.1, 2022: 92.1}},
     ("IT", "solar"): {"day_ahead": {2019: 94.8, 2020: 91, 2021: 92.1, 2022: 99.2}}}
for tz in ("UTC", "Europe/Brussels"):
    print(f"Zsiborács Tables 3-4, {tz} years:")
    for (area, pt), by_type in Z.items():
        for ft, years in by_type.items():
            for y, pub in years.items():
                got = one(f"""SELECT 100 * coalesce(sum(epoch(resolution)), 0) / epoch(TIMESTAMPTZ '{y + 1}-01-01 00:00:00 {tz}' - TIMESTAMPTZ '{y}-01-01 00:00:00 {tz}')
                              FROM g WHERE area = '{area}' AND forecast_type = '{ft}' AND production_type = '{pt}'
                                AND delivery_start >= TIMESTAMPTZ '{y}-01-01 00:00:00 {tz}' AND delivery_start < TIMESTAMPTZ '{y + 1}-01-01 00:00:00 {tz}'""")
                cmp(f"{area} {pt} {ft} {y}, % of the year with a forecast", pub, got, 0.05, "Zsiborács 2023 T2" if pt == "solar" else "Zsiborács 2022 T3-4")
    print()

print(f"{ok} match, {bad} differ")
