"""Published figures against entsoe_generation (latest versions): ENTSO-E's Statistical Factsheets
2019-2025, net generation per type. qa/published_figures_entsoe_generation.md.
Usage: python published_check_entsoe_generation.py <data_dir>

Each figure is compared with the year cut in UTC and in Europe/Zurich; a figure matches when one
of them is within the tolerance."""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute(f"CREATE VIEW gen AS SELECT * FROM read_parquet('{d}/entsoe_generation/generation/*.parquet') "
          "WHERE superseded_at IS NULL")
ok = bad = 0


def year_filter(y: int, zone: str) -> str:
    if zone == "UTC":
        return (f"delivery_start >= TIMESTAMPTZ '{y}-01-01 00:00:00Z' "
                f"AND delivery_start < TIMESTAMPTZ '{y + 1}-01-01 00:00:00Z'")
    return f"year(delivery_start AT TIME ZONE 'Europe/Zurich') = {y}"


def cmp(label: str, published: float, where: str, y: int, tol: float) -> None:
    global ok, bad
    got = {z: c.execute(f"SELECT sum(generation * epoch(resolution) / 3600) / 1e6 FROM gen WHERE {where} "
                        f"AND {year_filter(y, z)}").fetchone()[0] for z in ("UTC", "local")}
    hit = [z for z, v in got.items() if v is not None and abs(v - published) <= tol]
    ok += bool(hit)
    bad += not hit
    vals = ", ".join(f"{z} {v if v is None else round(v, 4)}" for z, v in got.items())
    print(f"{'ok  ' if hit else 'DIFF'} {label}: published {published}; {vals}")


# TWh to 0.1. 2023 is left out: the factsheet's Swiss values come from SFOE and Pronovo (footnote 3).
SFS = {
    "nuclear": {2019: 25.7, 2020: 23.4, 2021: 18.7, 2022: 23.6, 2024: 23.0, 2025: 18.4},
    "hydro_pumped_storage": {2019: 7.7, 2020: 6.9, 2021: 6.5, 2022: 5.7, 2024: 9.6, 2025: 8.0},
    "hydro_run_of_river": {2019: 1.9, 2020: 2.1, 2021: 2.1, 2022: 1.9, 2024: 2.3, 2025: 14.5},
    "hydro_reservoir": {2019: 11.9, 2020: 11.9, 2021: 10.8, 2022: 8.1, 2024: 13.9, 2025: 9.8},
    "solar": {2019: 0.4, 2020: 2.4, 2021: 2.5, 2022: 3.0, 2024: 4.3, 2025: 5.2},
    "wind_onshore": {2019: 0.1, 2020: 0.1, 2021: 0.1, 2022: 0.2, 2024: 0.1, 2025: 0.2},
}
TOTAL = {2019: 47.7, 2020: 46.7, 2021: 40.8, 2022: 42.5, 2024: 53.2}  # all types
for t, years in SFS.items():
    for y, v in years.items():
        cmp(f"{y} {t}", v, f"production_type = '{t}'", y, 0.05)
for y, v in TOTAL.items():
    cmp(f"{y} total", v, "true", y, 0.05)
cmp("2025 total without pumped storage (exclusive storage units)", 48.0, "production_type <> 'hydro_pumped_storage'",
    2025, 0.05)
print(f"\n{ok} match, {bad} differ")
