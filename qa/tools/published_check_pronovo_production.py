"""Published figures against pronovo_production (latest versions); qa/published_figures_pronovo_production.md.
Usage: <data_dir>"""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
for t in ("by_technology", "pv_by_canton", "capacity_by_technology", "pv_capacity_by_canton"):
    c.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{d}/pronovo_production/{t}/*.parquet') "
              "WHERE superseded_at IS NULL")


def one(sql):
    return c.execute(sql).fetchone()[0]


ok = bad = 0


def cmp(label, published, got, tol, src):
    global ok, bad
    match = got is not None and abs(float(got) - published) <= tol
    ok += match
    bad += not match
    print(f"{'ok  ' if match else 'DIFF'} {label}: published {published}, adele {got if got is None else round(float(got), 6)} ({src})")


# Pronovo, Lastgangprofile_11.2020.csv (Archiv/2020/DE/), its last row: the sum of each column over
# the file, kWh to 0.01 ("Zeitraum der Auswertung: 01.11.2020 - 01.12.2020", local end stamps
# 01.11.2020 00:15 to 01.12.2020 00:00, so the local month of November 2020).
NOV_2020_KWH = {
    "pv": 43_641_532.89, "biogas": 21_661_585.33, "biomass_energy_crops": 3_758_469.82,
    "biomass_forest_agri_waste": 36_123_148.64, "waste_renewable": 74_632_833.63, "sewage_gas": 8_901_888.54,
    "hydro_total": 2_567_842_038.51, "wind": 9_591_835.92,
}
SRC = "Pronovo, Lastgangprofile_11.2020.csv, row of column sums"
for tech, kwh in NOV_2020_KWH.items():
    got = one(f"""SELECT sum(production_mwh) FROM by_technology WHERE technology = '{tech}'
                  AND delivery_start >= TIMESTAMPTZ '2020-11-01 00:00:00+01'
                  AND delivery_start <  TIMESTAMPTZ '2020-12-01 00:00:00+01'""")
    cmp(f"{tech}, local Nov 2020, MWh", kwh / 1000, got, 0.000005, SRC)
    # the same sum on the UTC month: the end stamps put an hour in the wrong month if read as UTC
    utc = one(f"""SELECT sum(production_mwh) FROM by_technology WHERE technology = '{tech}'
                  AND delivery_start >= TIMESTAMPTZ '2020-11-01 00:00:00Z'
                  AND delivery_start <  TIMESTAMPTZ '2020-12-01 00:00:00Z'""")
    if utc is not None and abs(utc - kwh / 1000) > 0.000005:
        print(f"     (UTC month instead: {utc:.6f}, differs by {utc - kwh / 1000:+.3f} MWh)")

print(f"\n{ok} match, {bad} differ")

# BFE, "Elektrizitätsbilanz der Schweiz - Monatswerte, in GWh" (updated 30.10.2026, revised values
# 2020-2025), https://pubdb.bfe.admin.ch/de/publication/download/5634, sheet Tabelle1: nuclear,
# wind and PV per calendar month, whole GWh, net production. Not computed from these files: the
# nuclear comes from the operators; the monthly PV and wind "from Pronovo AG's certificate of
# origin database" (BFE factsheet https://pubdb.bfe.admin.ch/en/publication/download/12194, p. 2),
# and the yearly PV is scaled to Statistik Sonnenenergie. So these are comparisons, not checks.
BFE = {  # month: (nuclear, wind, pv)
    "2023-01": (2202, 16, 76), "2023-02": (1983, 10, 231), "2023-03": (2191, 19, 343), "2023-04": (2119, 12, 460),
    "2023-05": (1021, 10, 595), "2023-06": (1337, 7, 768), "2023-07": (2124, 11, 695), "2023-08": (1884, 11, 593),
    "2023-09": (1961, 8, 557), "2023-10": (2180, 16, 353), "2023-11": (2126, 26, 143), "2023-12": (2206, 23, 100),
    "2024-01": (2204, 22, 123), "2024-02": (2056, 17, 270), "2024-03": (2194, 15, 440), "2024-04": (2013, 18, 615),
    "2024-05": (808, 10, 740), "2024-06": (1251, 11, 771), "2024-07": (2142, 8, 920), "2024-08": (2003, 7, 882),
    "2024-09": (2067, 17, 548), "2024-10": (1917, 14, 328), "2024-11": (2124, 16, 196), "2024-12": (2204, 16, 128),
    "2025-01": (2201, 25, 200), "2025-02": (1970, 11, 274), "2025-03": (2180, 10, 647), "2025-04": (1883, 11, 950),
    "2025-05": (1124, 10, 1004), "2025-06": (1351, 12, 1189), "2025-07": (1140, 11, 1063), "2025-08": (1147, 8, 1049),
    "2025-09": (1117, 10, 689), "2025-10": (1407, 22, 450), "2025-11": (1404, 15, 269), "2025-12": (1455, 16, 164),
    "2026-01": (1454, 18, 200), "2026-02": (1315, 20, 358), "2026-03": (1466, 14, 771), "2026-04": (1848, 10, 1116),
    "2026-05": (1127, 11, 1285), "2026-06": (1221, 9, 1331), "2026-07": (1810, 10, 1461), "2026-08": (1728, 9, 1216),
}
ours = {(m, t): (gwh, cap) for m, t, gwh, cap in c.execute("""
    SELECT strftime(p.delivery_start AT TIME ZONE 'Europe/Zurich', '%Y-%m') AS m, p.technology,
           sum(p.production_mwh) / 1000 AS gwh, any_value(coalesce(k.capacity_mva, k.capacity_mw)) AS cap
    FROM by_technology p LEFT JOIN capacity_by_technology k
      ON k.technology = p.technology AND k.delivery_month = date_trunc('month', p.delivery_start AT TIME ZONE 'Europe/Zurich')
    WHERE p.technology IN ('nuclear', 'wind', 'pv')  -- every row: the rows marked suspect are the point here
      AND p.delivery_start >= TIMESTAMPTZ '2023-01-01 00:00:00+01'
    GROUP BY ALL""").fetchall()}
print("\nBFE monthly balance (net, whole GWh) against Pronovo (local months), GWh; capacity in the file, MW or MVA")
print("month    | nuclear BFE  ours   ratio  cap  | wind BFE  ours  ratio | pv BFE  ours   ratio")
for m, (nu, wi, pv) in BFE.items():
    on, ocap = ours.get((m, "nuclear"), (None, None))
    ow, _ = ours.get((m, "wind"), (None, None))
    op, _ = ours.get((m, "pv"), (None, None))
    pv_text = f"{pv:5d} {op:6.0f} {op / pv:6.3f}" if op is not None else f"{pv:5d}      - (suspect)"
    print(f"{m}  | {nu:5d} {on:7.0f} {on / nu:6.3f} {ocap:5.0f} | {wi:3d} {ow:6.1f} {ow / wi:5.2f}  | {pv_text}")
for y in ("2023", "2024", "2025"):
    sums = [sum(v[i] for m, v in BFE.items() if m.startswith(y)) for i in range(3)]
    mine = [sum(ours.get((m, t), (0, None))[0] for m in BFE if m.startswith(y)) for t in ("nuclear", "wind", "pv")]
    print(f"{y}: nuclear BFE {sums[0]} ours {mine[0]:.0f} ({mine[0] / sums[0]:.3f}); wind BFE {sums[1]} ours "
          f"{mine[1]:.1f} ({mine[1] / sums[1]:.3f}); pv BFE {sums[2]} ours {mine[2]:.0f} ({mine[2] / sums[2]:.3f})")
