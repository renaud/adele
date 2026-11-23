"""METAR temperature of iem_metar against the 10-minute temperature of SwissMetNet (MeteoSwiss open data).

Usage (from server/): uv run --with requests python ../qa/tools/crosscheck_iem_metar_smn.py <data_dir>

Pairs of aerodrome and SwissMetNet station at (or next to) it: LSZH-KLO, LSGG-GVE, LSMP-PAY, LSZG-GRE.
Reads the recent 10-minute files (t_recent, this year), column tre200s0 (air temperature 2 m, current
value, 0.1 degC, UTC). For lags -60 to +60 min (10-min steps): mean difference METAR - SMN (bias) and the
standard deviation of the difference, for METAR rounded to 1 degC. The right lag is the one with the
smallest standard deviation.
"""
from __future__ import annotations

import io
import pathlib
import sys

import duckdb
import pandas as pd
import requests

D = pathlib.Path(sys.argv[1]).resolve()
PAIRS = [("LSZH", "klo"), ("LSGG", "gve"), ("LSMP", "pay"), ("LSZG", "gre")]
con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")
for icao, smn in PAIRS:
    url = f"https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/{smn}/ogd-smn_{smn}_t_recent.csv"
    r = requests.get(url, timeout=(30, 300))
    r.raise_for_status()
    s = pd.read_csv(io.BytesIO(r.content), sep=";", encoding="cp1252", usecols=["reference_timestamp", "tre200s0"])
    s["t"] = pd.to_datetime(s["reference_timestamp"], format="%d.%m.%Y %H:%M", utc=True)
    smn_t = s.set_index("t")["tre200s0"]
    m = con.execute(f"SELECT valid_at, temperature FROM read_parquet('{D}/iem_metar/reports/*.parquet') "
                    f"WHERE station = '{icao}' AND temperature IS NOT NULL AND minute(valid_at) IN (20, 50) "
                    f"AND valid_at >= TIMESTAMPTZ '{smn_t.index.min()}'").df()
    m["valid_at"] = pd.to_datetime(m["valid_at"], utc=True)
    best = {}
    for lag in range(-60, 61, 10):
        x = smn_t.reindex(m["valid_at"] + pd.Timedelta(minutes=lag))
        d = m["temperature"].to_numpy() - x.to_numpy()
        ok = ~pd.isna(d)
        best[lag] = (d[ok].mean(), d[ok].std(), int(ok.sum()))
    lag0 = best[0]
    winner = min(best, key=lambda k: best[k][1])
    print(f"{icao}-{smn.upper()}: {lag0[2]} pairs; lag 0: bias {lag0[0]:+.2f}, sd {lag0[1]:.2f} degC; smallest sd at lag {winner} min ({best[winner][1]:.2f})")
