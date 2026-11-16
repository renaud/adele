"""Published figures against energy_charts_intraday_prices; qa/published_figures_energy_charts_intraday_prices.md.
Usage: <data_dir>

EPEX SPOT's monthly "Power Trading Results": monthly means of the intraday indices (continuous ID Full, ID3, ID1)
and of the intraday auctions (base: every hour of the month; peak: Monday to Friday 08:00-20:00), months in local
time. Energy-Charts' series are EPEX data, so the means must agree to the cent where the definitions agree.
"""
import sys

import duckdb

d = sys.argv[1]
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")
c.execute(f"CREATE VIEW prices AS SELECT * FROM read_parquet('{d}/energy_charts_intraday_prices/prices/*.parquet')")

ok = bad = 0


def cmp(label, published, got, tol, src):
    global ok, bad
    match = got is not None and abs(float(got) - published) <= tol
    ok += match
    bad += not match
    print(f"{'ok  ' if match else 'DIFF'} {label}: published {published}, adele {got if got is None else round(float(got), 3)} ({src})")


def month_mean(zone, col, month, peak=False):
    a, b = f"{month}-01", f"{month[:4]}-{int(month[5:]) + 1:02d}-01" if month[5:] != "12" else f"{int(month[:4]) + 1}-01-01"
    peak_sql = (" AND isodow(delivery_start AT TIME ZONE 'Europe/Zurich') <= 5"
                " AND hour(delivery_start AT TIME ZONE 'Europe/Zurich') BETWEEN 8 AND 19") if peak else ""
    return c.execute(f"""SELECT avg({col}) FROM prices WHERE bidding_zone = '{zone}'
        AND delivery_start >= timezone('Europe/Zurich', TIMESTAMP '{a}') AND delivery_start < timezone('Europe/Zurich', TIMESTAMP '{b}')
        {peak_sql}""").fetchone()[0]


DEC = "EPEX Power Trading Results 12-2025 (2026-01-06)"
SEP = "EPEX Power Trading Results 09-2025 (2025-10-02)"
FIGURES = [  # (zone, column, month, peak, published, page, source)
    ("DE_LU", "id_avg", "2025-12", False, 92.39, "p. 8, ID Full DE (60 min)", DEC),
    ("DE_LU", "id3", "2025-12", False, 92.16, "p. 8, ID3 DE (60 min)", DEC),
    ("DE_LU", "id1", "2025-12", False, 92.13, "p. 8, ID1 DE (60 min)", DEC),
    ("CH", "id_avg", "2025-12", False, 112.89, "p. 8, ID Full CH (60 min)", DEC),
    ("CH", "ida1", "2025-12", False, 187.33, "p. 6, CH IDA1 base", DEC),
    ("CH", "ida1", "2025-12", True, 125.90, "p. 6, CH IDA1 peak", DEC),
    ("CH", "ida2", "2025-12", False, 127.93, "p. 6, CH IDA2 base", DEC),
    ("CH", "ida2", "2025-12", True, 124.20, "p. 6, CH IDA2 peak", DEC),
    ("DE_LU", "id3", "2025-09", False, 86.12, "p. 7, ID3 DE (60 min)", SEP),
    ("CH", "ida1", "2025-09", False, 93.46, "p. 5, CH IDA1 base", SEP),
    ("CH", "ida1", "2025-09", True, 101.89, "p. 5, CH IDA1 peak", SEP),
    ("CH", "ida2", "2025-09", False, 556.97, "p. 5, CH IDA2 base", SEP),
    ("CH", "ida2", "2025-09", True, 596.67, "p. 5, CH IDA2 peak", SEP),
]
for zone, col, month, peak, published, page, src in FIGURES:
    cmp(f"{month} {zone} {col} {'peak' if peak else 'base'}", published, month_mean(zone, col, month, peak), 0.015,
        f"{src}, {page}")

# Why CH ID Full differs: EPEX's index takes the day-ahead price in an hour with less than 10 MW traded; Energy-Charts'
# average keeps the traded price (SED notes/swiss_intraday.md section 6). Hours of 2025-12 by state:
print("\nCH 2025-12: hours with a single trade price (low = high), and without a price:")
print(c.execute("""SELECT count(*) FILTER (WHERE id_low = id_high) AS one_price, count(*) FILTER (WHERE id_avg IS NULL) AS no_price
    FROM prices WHERE bidding_zone = 'CH' AND delivery_start >= TIMESTAMPTZ '2025-12-01 00:00:00+01'
    AND delivery_start < TIMESTAMPTZ '2026-01-01 00:00:00+01'""").fetchall())
# CH IDA1 of 2025-09: the source has no IDA1 on 2025-09-09 (SED); EPEX's mean includes that day.
print("CH ida1, 2025-09: days without a value:")
print(c.execute("""SELECT CAST(delivery_start AT TIME ZONE 'Europe/Zurich' AS DATE) AS day, count(*) FILTER (WHERE ida1 IS NULL) AS null_hours
    FROM prices WHERE bidding_zone = 'CH' AND delivery_start >= TIMESTAMPTZ '2025-09-01 00:00:00+02'
    AND delivery_start < TIMESTAMPTZ '2025-10-01 00:00:00+02' GROUP BY 1 HAVING null_hours > 0 ORDER BY 1""").fetchall())
print(f"\n{ok} match, {bad} differ")
