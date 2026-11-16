"""Published figures against swissgrid_imbalance_prices; qa/published_figures_swissgrid_imbalance_prices.md.
Usage: <data_dir> [<SED store>]   (with the SED store, the 2026 weeks are also computed with the TSI of Swissgrid's
control-area file, SED's control_area_balance_15min: the definition that ElCom states)

ElCom's weekly market reports ("Marktbericht", one per Tuesday; the week is Monday to Sunday, local), table
"Ausgleichsenergiepreis", whole EUR/MWh:
- 2025: "AE+ (short)" and "AE- (long)", "ungewichtetes Mittel": the plain mean of the dual prices of the week.
- 2026: "AE short" / "AE long", in August "AE für RZ short / long": "Ausgleichsenergiepreis für den Fall, dass die
  Regelzone short (negative Unausgeglichenheit) oder long (positive U.) ist": the mean of the single price over the
  quarter-hours with TSI < 0, resp. > 0. adele has no TSI (it is in the control-area file, WP4); without it, the
  quarter-hours where the single price is above, resp. at or below, the CH day-ahead price stand in for them.
"""
import sys

import duckdb

d = sys.argv[1]
sed = sys.argv[2] if len(sys.argv) > 2 else None
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute(f"CREATE VIEW prices AS SELECT * FROM read_parquet('{d}/swissgrid_imbalance_prices/prices/*.parquet')")
c.execute(f"CREATE VIEW da AS SELECT * FROM read_parquet('{d}/entsoe_day_ahead_prices/prices/*.parquet') WHERE bidding_zone = 'CH'")
if sed:
    c.execute(f"CREATE VIEW cab AS SELECT datetime AS delivery_start, tsi FROM "
              f"read_parquet('{sed}/tables/ch_swissgrid/control_area_balance_15min.parquet')")

ok = bad = 0


def cmp(label, published, got, tol, src):
    global ok, bad
    match = got is not None and abs(float(got) - published) <= tol
    ok += match
    bad += not match
    print(f"{'ok  ' if match else 'DIFF'} {label}: published {published}, adele {got if got is None else round(float(got), 2)} ({src})")
    return match


# week (Monday, local) --> (AE short, AE long, report of ElCom and its column)
ELCOM = {
    "2025-10-27": (249, -33, "2025-11-11 Vorwoche"),
    "2025-11-03": (218, -56, "2025-11-11 Aktuell"),
    "2025-11-10": (234, -14, "2025-11-18 Aktuell"),
    "2025-11-17": (244, 38, "2025-11-25 Aktuell"),
    "2025-12-01": (217, 36, "2025-12-16 Vorwoche"),
    "2025-12-08": (208, 7, "2025-12-16 Aktuell"),
    "2025-12-29": (157, -15, "2026-01-13 Vorwoche"),
    "2026-01-05": (246, 31, "2026-01-13 Aktuell"),
    "2026-01-12": (210, 56, "2026-01-27 Vorwoche"),
    "2026-01-19": (223, 77, "2026-01-27 Aktuell"),
    "2026-01-26": (214, 83, "2026-02-03 Aktuell"),
    "2026-02-02": (193, 65, "2026-02-10 Aktuell"),
    "2026-02-09": (172, 25, "2026-02-24 Vorwoche"),
    "2026-02-16": (179, 31, "2026-02-24 Aktuell"),
    "2026-02-23": (161, 34, "2026-03-03 Aktuell"),
    "2026-03-02": (179, 57, "2026-03-10 Aktuell"),
    "2026-03-09": (211, 68, "2026-03-24 Vorwoche"),
    "2026-03-16": (215, 35, "2026-03-24 Aktuell"),
    "2026-03-23": (227, -63, "2026-03-31 Aktuell"),
    "2026-03-30": (220, -76, "2026-04-07 Aktuell"),
    "2026-04-06": (153, -68, "2026-04-14 Aktuell"),
    "2026-04-13": (191, -20, "2026-04-28 Vorwoche"),
    "2026-04-20": (143, -46, "2026-04-28 Aktuell"),
    "2026-04-27": (153, -43, "2026-05-05 Aktuell"),
    "2026-05-04": (208, 40, "2026-05-12 Aktuell"),
    "2026-05-11": (194, 3, "2026-05-19 Aktuell"),
    "2026-05-18": (190, -40, "2026-05-26 Aktuell"),
    "2026-05-25": (186, 25, "2026-06-02 Aktuell"),
    "2026-06-01": (165, -28, "2026-06-09 Aktuell"),
    "2026-08-03": (221, 33, "2026-08-18 Vorwoche"),
    "2026-08-10": (244, 15, "2026-08-18 Aktuell"),
}
WEEK = ("p.delivery_start >= timezone('Europe/Zurich', CAST($m AS TIMESTAMP)) "
        "AND p.delivery_start < timezone('Europe/Zurich', CAST($m AS TIMESTAMP) + INTERVAL 7 DAY)")
proxy_ok = []
for monday, (short, long_, report) in ELCOM.items():
    src = f"ElCom Marktbericht {report}"
    if monday < "2025-12-29":  # dual price: plain means
        s, l = c.execute(f"SELECT avg(price_short), avg(price_long) FROM prices p WHERE {WEEK}", {"m": monday}).fetchone()
        cmp(f"week {monday} AE short, mean of price_short", short, s, 0.5, src)
        cmp(f"week {monday} AE long, mean of price_long", long_, l, 0.5, src)
        continue
    s, l = c.execute(f"""SELECT avg(p.price_single) FILTER (WHERE p.price_single > da.price),
                                avg(p.price_single) FILTER (WHERE p.price_single <= da.price)
        FROM prices p JOIN da ON p.delivery_start >= da.delivery_start AND p.delivery_start < da.delivery_start + da.resolution
        WHERE {WEEK}""", {"m": monday}).fetchone()
    a = cmp(f"week {monday} AE short, price above the day-ahead price", short, s, 0.5, src)
    b = cmp(f"week {monday} AE long, price at or below the day-ahead price", long_, l, 0.5, src)
    if a and b:
        proxy_ok.append(monday)
    if sed:
        s, l = c.execute(f"""SELECT avg(p.price_single) FILTER (WHERE cab.tsi < 0), avg(p.price_single) FILTER (WHERE cab.tsi > 0)
            FROM prices p JOIN cab ON cab.delivery_start = p.delivery_start WHERE {WEEK}""", {"m": monday}).fetchone()
        cmp(f"week {monday} AE short, TSI < 0 (control-area file)", short, s, 0.5, src)
        cmp(f"week {monday} AE long, TSI > 0 (control-area file)", long_, l, 0.5, src)

# ElCom Marktbericht 2026-05-26: on Tuesday (2026-05-19), control area long by more than 400 MW, activation costs at
# 12:45 above 450,000 EUR per quarter-hour, "ein Ausgleichsenergiepreis von über 3'300 EUR/MWh" (in absolute value).
low = c.execute("""SELECT strftime(delivery_start AT TIME ZONE 'Europe/Zurich', '%H:%M'), price_single FROM prices
    WHERE delivery_start >= TIMESTAMPTZ '2026-05-19 00:00:00+02' AND delivery_start < TIMESTAMPTZ '2026-05-20 00:00:00+02'
    ORDER BY price_single LIMIT 1""").fetchone()
print(f"{'ok  ' if low[0] == '12:45' and low[1] < -3300 else 'DIFF'} 2026-05-19 lowest price at {low[0]} local: "
      f"{low[1]} EUR/MWh (ElCom Marktbericht 2026-05-26: 12:45, over 3,300 EUR/MWh)")
print(f"\n{ok} match, {bad} differ; 2026 weeks where the stand-in matches both figures: {proxy_ok}")
