"""Published figures against entsoe_physical_flows (latest versions): ENTSO-E's Statistical
Factsheets 2019-2025, "Hourly netted physical flow values". qa/published_figures_entsoe_physical_flows.md.
Usage: python published_check_entsoe_physical_flows.py <data_dir>

Each figure is compared with the year cut in UTC and in Europe/Zurich; a figure matches when one
of them is within the tolerance."""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute(f"CREATE VIEW flo AS SELECT * FROM read_parquet('{d}/entsoe_physical_flows/flows/*.parquet') "
          "WHERE superseded_at IS NULL")
# the hourly net: the mean power of each direction over the UTC hour (DE has quarter-hours from 2021-08),
# then the difference
c.execute("""CREATE VIEW hourly AS SELECT border, time_bucket(INTERVAL 1 HOUR, delivery_start) AS delivery_start,
                                          avg(from_ch) - avg(to_ch) AS net FROM flo GROUP BY 1, 2""")
ok = bad = 0


def year_filter(y: int, zone: str) -> str:
    if zone == "UTC":
        return (f"delivery_start >= TIMESTAMPTZ '{y}-01-01 00:00:00Z' "
                f"AND delivery_start < TIMESTAMPTZ '{y + 1}-01-01 00:00:00Z'")
    return f"year(delivery_start AT TIME ZONE 'Europe/Zurich') = {y}"


def cmp(label: str, published: float, part: str, border: str, y: int, tol: float) -> None:
    global ok, bad
    got = {z: c.execute(f"SELECT sum({part}) / 1e3 FROM hourly WHERE border = '{border}' "
                        f"AND {year_filter(y, z)}").fetchone()[0] for z in ("UTC", "local")}
    hit = [z for z, v in got.items() if v is not None and abs(v - published) <= tol]
    ok += bool(hit)
    bad += not hit
    vals = ", ".join(f"{z} {v if v is None else round(v, 4)}" for z, v in got.items())
    print(f"{'ok  ' if hit else 'DIFF'} {label}: published {published}; {vals}{'  (' + '/'.join(hit) + ')' if hit else ''}")


SFS = {  # border: {year: (CH --> border, border --> CH)}, GWh
    "DE": {2019: (3434, 11809), 2020: (5171, 9760), 2021: (1306, 13875), 2022: (736, 16129), 2023: (4012, 7792),
           2024: (8317, 3854), 2025: (3613, 6546)},
    "FR": {2019: (2010, 7690), 2020: (2315, 8066), 2021: (1955, 8218), 2022: (3063, 6864), 2023: (2218, 9612),
           2024: (818, 13193), 2025: (406, 15754)},
    "IT": {2019: (21236, 121), 2020: (17886, 861), 2021: (18600, 378), 2022: (19580, 329), 2023: (20370, 149),
           2024: (20864, 470), 2025: (16088, 496)},
    "AT": {2019: (565, 4317), 2020: (1044, 3495), 2021: (421, 3384), 2022: (411, 4313), 2023: (696, 4628),
           2024: (1866, 2308), 2025: (2430, 2271)},
}
for b, years in SFS.items():
    for y, (exp, imp) in years.items():
        cmp(f"{y} CH --> {b}", exp, "greatest(net, 0)", b, y, 0.5)
        cmp(f"{y} {b} --> CH", imp, "greatest(-net, 0)", b, y, 0.5)
print(f"\n{ok} match, {bad} differ")
