"""Compare the stored METAR text of iem_metar with the archive of ogimet.com, an independent collection.

Usage (from server/): uv run --with requests python ../qa/tools/ogimet_compare_iem_metar.py <data_dir> [days]

One day per year of 2015, 2016, 2018, 2019, 2021, 2022, 2024 and 2026 (chosen with a fixed seed), three
requests per day (the prefixes LSZ, LSG and LSM of ogimet's getmetar, which takes one prefix), 22 s
apart: ogimet allows one query per 20 s. Compared by station and stamp:
reports that only one of the two has, and reports whose text differs. METAR, SPECI, COR and = are
left out of the comparison, the other text is compared as it is.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import random
import re
import sys
import time

import duckdb
import requests

D = pathlib.Path(sys.argv[1]).resolve()
STATIONS = {"LSZH", "LSGG", "LSZB", "LSMP", "LSZG", "LSME", "LSMD", "LSZR"}


def clean(t: str) -> str:
    t = t.replace("=", " ")
    return " ".join(re.sub(r"^(METAR |SPECI )?(COR )?", "", t.strip()).split())


def ogimet(day: dt.date) -> dict:
    out = {}
    for prefix in ("LSZ", "LSG", "LSM"):
        params = {"icao": prefix, "begin": f"{day:%Y%m%d}0000", "end": f"{day:%Y%m%d}2359"}
        r = requests.get("https://www.ogimet.com/cgi-bin/getmetar", timeout=(30, 180), params=params)
        if r.status_code == 501:  # the quota: wait and ask once more
            time.sleep(45)
            r = requests.get("https://www.ogimet.com/cgi-bin/getmetar", timeout=(30, 180), params=params)
        r.raise_for_status()
        time.sleep(22)
        for line in r.text.splitlines():
            p = line.split(",", 6)
            if len(p) == 7 and p[0] in STATIONS and "NIL" not in p[6]:
                key = (p[0], f"{p[1]}-{p[2]}-{p[3]} {p[4]}:{p[5]}")
                out.setdefault(key, set()).add(clean(p[6]))
    return out


def main() -> None:
    rnd = random.Random(20261123)
    days = [dt.date(y, rnd.randint(1, 12), rnd.randint(1, 28)) for y in (2015, 2016, 2018, 2019, 2021, 2022, 2024, 2026)]
    if days[-1] > dt.date(2026, 11, 20):
        days[-1] = dt.date(2026, 6, 15)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    rep = f"read_parquet('{D}/iem_metar/reports/*.parquet')"
    tot = {"both": 0, "same": 0, "differ": 0, "only_ogimet": 0, "only_iem": 0}
    examples, per_station = [], {}
    for day in days:
        og = ogimet(day)
        rows = con.execute(f"SELECT station, strftime(valid_at, '%Y-%m-%d %H:%M'), metar FROM {rep} "
                           f"WHERE valid_at >= TIMESTAMPTZ '{day} 00:00:00Z' AND valid_at < TIMESTAMPTZ '{day} 00:00:00Z' + INTERVAL 1 DAY").fetchall()
        iem = {(s, t): clean(m) for s, t, m in rows}
        for k in og.keys() | iem.keys():
            st = per_station.setdefault(k[0], {"both": 0, "same": 0, "differ": 0, "only_ogimet": 0, "only_iem": 0})
            if k in og and k in iem:
                kind = "same" if iem[k] in og[k] else "differ"
                tot["both"] += 1; st["both"] += 1
                if kind == "differ":
                    examples.append((k, iem[k], sorted(og[k])))
            else:
                kind = "only_ogimet" if k in og else "only_iem"
                examples.append((k, iem.get(k), sorted(og.get(k, []))))
            tot[kind] += 1; st[kind] += 1
        print(f"{day}: ogimet {len(og)}, iem {len(iem)}", flush=True)
    print("\ntotal", tot)
    for s, v in sorted(per_station.items()):
        print(s, v)
    print("\nall differences: ogimet cut the text (its text is the start of IEM's), other differences, one side only")
    for key, iem_text, og_texts in examples:
        kind = "only one side" if not iem_text or not og_texts else (
            "ogimet cut" if any(iem_text.startswith(o) for o in og_texts) else "text differs")
        print(f"{kind} | {key[0]} {key[1]} | iem: {iem_text} | ogimet: {' / '.join(og_texts)}")


main()
