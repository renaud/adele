"""The four datasets of WP5.2 (latest versions) against the swissgrid project's download of
2026-10-31 (`swissgrid_project/data/entsoe/*.parquet`): every common value, the keys that only one
side holds, and the differences per month. The same source, fetched 15 days apart: a difference is
a revision of ENTSO-E or an error of one of the two parsers.

Usage: python compare_sgp_entsoe_wp52.py <adele data_dir> <swissgrid_project/data/entsoe>
"""
import sys

import duckdb

d, sgp = sys.argv[1], sys.argv[2]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")


def latest(ds: str, table: str) -> str:
    return f"(SELECT * FROM read_parquet('{d}/{ds}/{table}/*.parquet') WHERE superseded_at IS NULL)"


TYPES = ("('B04','fossil_gas'),('B10','hydro_pumped_storage'),('B11','hydro_run_of_river'),('B12','hydro_reservoir'),"
         "('B14','nuclear'),('B16','solar'),('B19','wind_onshore')")
PAIRS = {
    "generation": (
        f"SELECT production_type AS k, delivery_start AS t, generation AS v FROM {latest('entsoe_generation', 'generation')}",
        f"SELECT m.name AS k, datetime AS t, value_mw AS v FROM read_parquet('{sgp}/generation.parquet') g "
        f"JOIN (VALUES {TYPES}) m(code, name) ON g.psr_type = m.code"),
    "imbalance": (
        f"SELECT 'CH' AS k, delivery_start AS t, imbalance AS v FROM {latest('entsoe_imbalance_volume', 'imbalance')}",
        f"SELECT 'CH' AS k, datetime AS t, imbalance_mw / 4 AS v FROM read_parquet('{sgp}/imbalance_volume.parquet')"),
    "imbalance mv_minus_sv": (
        f"SELECT 'CH' AS k, delivery_start AS t, mv_minus_sv AS v FROM {latest('entsoe_imbalance_volume', 'imbalance')} "
        "WHERE mv_minus_sv IS NOT NULL",
        f"SELECT 'CH' AS k, datetime AS t, mv_minus_sv_mwh AS v FROM read_parquet('{sgp}/imbalance_volume.parquet') "
        "WHERE mv_minus_sv_mwh IS NOT NULL"),
}
for col, frm in (("from_ch", "CH"), ("to_ch", None)):
    side = "from_area = 'CH'" if frm else "to_area = 'CH'"
    PAIRS[f"flows {col}"] = (
        f"SELECT border AS k, delivery_start AS t, {col} AS v FROM {latest('entsoe_physical_flows', 'flows')} "
        f"WHERE {col} IS NOT NULL",
        f"SELECT border AS k, datetime AS t, value_mw AS v FROM read_parquet('{sgp}/flows.parquet') "
        f"WHERE {side} AND border <> 'DE_LU'")
    for table, ct in (("day_ahead", "A01"), ("total", "A05")):
        PAIRS[f"scheduled {table} {col}"] = (
            f"SELECT border AS k, delivery_start AS t, {col} AS v FROM {latest('entsoe_scheduled_exchanges', table)} "
            f"WHERE {col} IS NOT NULL",
            f"SELECT border AS k, datetime AS t, value_mw AS v FROM read_parquet('{sgp}/scheduled.parquet') "
            f"WHERE contract = '{ct}' AND {side} AND border <> 'DE_LU'")

for name, (a, b) in PAIRS.items():
    # only times before the swissgrid project's download (2026-10-31 08:00 UTC)
    c.execute(f"CREATE OR REPLACE TEMP VIEW a AS SELECT * FROM ({a}) WHERE t < TIMESTAMPTZ '2026-10-31 00:00:00Z'")
    c.execute(f"CREATE OR REPLACE TEMP VIEW b AS SELECT * FROM ({b}) WHERE t < TIMESTAMPTZ '2026-10-31 00:00:00Z'")
    r = c.execute("""
        SELECT count(*) FILTER (WHERE a.v IS NOT NULL AND b.v IS NOT NULL) AS common,
               count(*) FILTER (WHERE a.v IS NOT NULL AND b.v IS NOT NULL AND abs(a.v - b.v) > 1e-6) AS diff,
               count(*) FILTER (WHERE b.v IS NULL) AS only_adele,
               count(*) FILTER (WHERE a.v IS NULL) AS only_sgp
        FROM a FULL JOIN b USING (k, t)""").fetchone()
    print(f"{name}: common {r[0]:,}, different {r[1]:,}, only adele {r[2]:,}, only swissgrid project {r[3]:,}")
    if r[1] or r[2] or r[3]:
        rows = c.execute("""
            SELECT strftime(t, '%Y-%m') AS month,
                   count(*) FILTER (WHERE a.v IS NOT NULL AND b.v IS NOT NULL AND abs(a.v - b.v) > 1e-6) AS diff,
                   count(*) FILTER (WHERE b.v IS NULL) AS only_adele, count(*) FILTER (WHERE a.v IS NULL) AS only_sgp,
                   max(abs(a.v - b.v)) AS max_abs
            FROM a FULL JOIN b USING (k, t)
            GROUP BY 1 HAVING diff > 0 OR only_adele > 0 OR only_sgp > 0 ORDER BY 1""").fetchall()
        for m in rows[:12]:
            print(f"   {m[0]}: different {m[1]}, only adele {m[2]}, only swissgrid project {m[3]}, max |diff| "
                  f"{m[4] if m[4] is None else round(m[4], 3)}")
        if len(rows) > 12:
            print(f"   ... {len(rows) - 12} more months")
