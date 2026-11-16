"""MeteoSwiss's climate bulletins against the WP5.7 datasets; qa/published_figures_meteoswiss.md.

Each published figure (a monthly or yearly mean temperature, precipitation or sunshine at a
station) is computed on the stored data in every way that could be meant: from the daily, hourly
and 10-minute tables, and precipitation over UTC days or over days of 06 to 06 UTC, also from the
manual network. A variant matches when it is within half a unit of the last published digit.

Usage: python -I published_check_meteoswiss.py <data_dir> [--list]
  --list  print one line per figure and variant (else only the summary and the differences)
Writes qa/published_figures_meteoswiss_matched.csv: each figure with the value of each variant.
"""
import csv
import sys
from pathlib import Path

import duckdb

QA = Path(__file__).resolve().parents[1]
d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
for name, path in {
    "daily": "meteoswiss_smn_daily/measurements/*.parquet",
    "hourly": "meteoswiss_smn_hourly/measurements/*.parquet",
    "tenmin": "meteoswiss_smn_tenmin/measurements/*.parquet",
    "nime": "meteoswiss_nime_daily/measurements/*.parquet",
    "smn_stations": "meteoswiss_smn_stations/stations/table.parquet",
    "nime_stations": "meteoswiss_nime_daily/stations/table.parquet",
}.items():
    c.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{d}/{path}')")

# the tables printed as images name the station by its town
SHORT = {"Bern": "BER", "Zürich": "SMA", "Genève": "GVE", "Basel": "BAS", "Engelberg": "ENG", "Sion": "SIO",
         "Lugano": "LUG", "Samedan": "SAM"}
nime_names = dict(c.execute("SELECT name, station FROM nime_stations").fetchall())
names = nime_names | dict(c.execute("SELECT name, station FROM smn_stations").fetchall())  # SwissMetNet first


def abbr(name: str, kind: str) -> str | None:
    if kind == "fresh_snow_max_cm":  # fresh snow is measured only in the manual network
        return nime_names.get(name)
    return SHORT.get(name) or names.get(name)


def bounds(period: str) -> tuple[str, str]:
    if len(period) == 4:
        return f"{period}-01-01", f"{int(period) + 1}-01-01"
    y, m = map(int, period.split("-"))
    return f"{y}-{m:02d}-01", (f"{y + 1}-01-01" if m == 12 else f"{y}-{m + 1:02d}-01")


# variant --> SQL of one number; $s station, $a and $b the first and the next day (dates)
DAY = "station = $s AND reference_date >= CAST($a AS DATE) AND reference_date < CAST($b AS DATE)"
HOUR = "station = $s AND delivery_start >= CAST($a AS TIMESTAMPTZ) AND delivery_start < CAST($b AS TIMESTAMPTZ)"
HOUR6 = ("station = $s AND delivery_start >= CAST($a AS TIMESTAMPTZ) + INTERVAL 6 HOUR "
         "AND delivery_start < CAST($b AS TIMESTAMPTZ) + INTERVAL 6 HOUR")
VARIANTS = {
    "temperature_mean_c": {
        "daily": f"SELECT avg(temperature) FROM daily WHERE {DAY}",
        "hourly": f"SELECT avg(temperature) FROM hourly WHERE {HOUR}",
    },
    "sunshine_h": {
        "daily": f"SELECT sum(sunshine) / 60 FROM daily WHERE {DAY}",
        "hourly": f"SELECT sum(sunshine) / 60 FROM hourly WHERE {HOUR}",
        "tenmin": f"SELECT sum(sunshine) / 60 FROM tenmin WHERE {HOUR}",
    },
    "precipitation_mm": {
        "daily_utc": f"SELECT sum(precipitation) FROM daily WHERE {DAY}",
        "daily_06utc": f"SELECT sum(precipitation_06utc) FROM daily WHERE {DAY}",
        "hourly": f"SELECT sum(precipitation) FROM hourly WHERE {HOUR}",
        "hourly_06utc": f"SELECT sum(precipitation) FROM hourly WHERE {HOUR6}",
        "nime": f"SELECT sum(precipitation) FROM nime WHERE {DAY}",
    },
    "fresh_snow_max_cm": {  # the largest fresh snow of one day (06 to 06 UTC) in the period
        "nime_max": f"SELECT max(fresh_snow) FROM nime WHERE {DAY}",
    },
}
COUNT = {"daily": f"SELECT count(*) FROM daily WHERE {DAY}", "tenmin": f"SELECT min(delivery_start) FROM tenmin"}

figures = []
for f in ("published_figures_meteoswiss_typed.csv", "published_figures_meteoswiss_text.csv"):
    with open(QA / f, encoding="utf-8") as fh:
        figures += list(csv.DictReader(fh))

tenmin_from = str(c.execute(COUNT["tenmin"]).fetchone()[0])[:10]
rows, stats = [], {}
for fig in figures:
    s = abbr(fig["station_name"], fig["kind"])
    value = float(fig["value"])
    tol = 0.05 if "." in fig["value"] else 0.5
    a, b = bounds(fig["period"])
    out = {**fig, "station": s, "tolerance": tol}
    for v, sql in VARIANTS[fig["kind"]].items():
        if s is None or (v == "tenmin" and a < tenmin_from):
            out[v] = None
            continue
        got = c.execute(sql, {"s": s, "a": a, "b": b}).fetchone()[0]
        out[v] = None if got is None else round(float(got), 3)
        ok = got is not None and abs(float(got) - value) <= tol + 1e-9
        key = (fig["kind"], v, "year" if len(fig["period"]) == 4 else "month")
        n, k = stats.get(key, (0, 0))
        stats[key] = (n + 1, k + ok)
        if "--list" in sys.argv:
            print(f"{'ok  ' if ok else 'DIFF'} {fig['period']} {fig['kind']} {fig['station_name']} ({s}) {v}: "
                  f"published {value}, adele {out[v]}")
    rows.append(out)

unmapped = sorted({r["station_name"] for r in rows if r["station"] is None})
print(f"{len(figures)} figures; stations without an abbreviation: {unmapped}")
print("kind, variant, period: matches / figures computed")
for (kind, v, per), (n, k) in sorted(stats.items()):
    print(f"  {kind:20s} {v:12s} {per:6s} {k:4d} / {n:4d}")
cols = ["period", "kind", "station_name", "station", "value", "tolerance", "file", "page"] + sorted(
    {v for vs in VARIANTS.values() for v in vs})
with open(QA / "published_figures_meteoswiss_matched.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
