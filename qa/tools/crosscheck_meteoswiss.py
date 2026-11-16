"""Check the MeteoSwiss station datasets against their reference lists (WP5.7).

Usage (from server/): uv run python -I ../qa/tools/crosscheck_meteoswiss.py <data_dir> <meta_dir>

<data_dir> holds the stored tables (data_nosync/). <meta_dir> holds the meta files of the three
STAC collections (ogd-{smn,nime,obs}_meta_{stations,parameters,datainventory}.csv) and
items_{smn,nime,obs}.json (the ids of the STAC items): the parameters and inventories of the manual
network and of the visual observations are not stored by adele.

Checks:
1. Station ids: every station of a data table is in its station list; the stations of each list
   and of each STAC collection; abbreviations shared by two networks name the same place.
2. Parameter codes: each code that a fetch reads is in the collection's parameter list, at the
   granularity and in the unit of the column that stores it.
3. Inventory: a (station, parameter) with values in adele is in the inventory and the reverse; the
   first and last values against data_since and data_till, in MeteoSwiss's own stamps.
"""
from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import sys

import duckdb
import pandas as pd
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
D = pathlib.Path(sys.argv[1]).resolve()
M = pathlib.Path(sys.argv[2]).resolve()
c = duckdb.connect()
c.execute("SET TimeZone='UTC'")


def pq(dataset: str, table: str) -> str:
    return f"read_parquet('{D}/{dataset}/{table}/*.parquet')"


def meta(coll: str, kind: str) -> pd.DataFrame:
    raw = (M / f"ogd-{coll}_meta_{kind}.csv").read_bytes()
    return pd.read_csv(io.BytesIO(raw), sep=";", encoding="cp1252", dtype=str, keep_default_na=False)


def codes(dataset: str, *names: str) -> dict[str, str]:
    spec = importlib.util.spec_from_file_location(dataset, ROOT / "datasets" / dataset / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out: dict[str, str] = {}
    for n in names:
        out.update(getattr(mod, n))
    return out


def units(dataset: str, table: str) -> dict[str, str]:
    dp = yaml.safe_load((ROOT / "datasets" / dataset / "datapackage.yaml").read_text())
    res = next(r for r in dp["resources"] if r["name"] == table)
    return {f["name"]: f.get("unit", "") for f in res["schema"]["fields"]}


def head(title: str) -> None:
    print(f"\n## {title}\n")


def show(df: pd.DataFrame, n: int = 40) -> None:
    print(df.head(n).to_string(index=False) if len(df) else "(none)")
    if len(df) > n:
        print(f"... {len(df)} rows")


# Tables: (dataset, table, station list, code map names, how a stored row maps to MeteoSwiss's stamp)
# The stamp of MeteoSwiss: end of the interval for t and h, start (00:00) for d.
# Hourly: before 2018 delivery_start = T - 20 min, from 2018 T - 60 min: trunc to the hour + 1 h = T.
# Snow: valid_at = T + 40 min before 2018, T from 2018: trunc to the hour = T.
TABLES = [
    ("meteoswiss_smn_hourly", "measurements", "smn", ["MEASUREMENTS"], "delivery_start",
     "date_trunc('hour', {x}) + INTERVAL 1 HOUR"),
    ("meteoswiss_smn_hourly", "snow_depth", "smn", ["SNOW"], "valid_at", "date_trunc('hour', {x})"),
    ("meteoswiss_smn_tenmin", "measurements", "smn", ["MEASUREMENTS"], "delivery_start", "{x} + INTERVAL 10 MINUTE"),
    ("meteoswiss_smn_daily", "measurements", "smn", ["MEASUREMENTS"], "reference_date", "CAST({x} AS TIMESTAMPTZ)"),
    ("meteoswiss_nime_daily", "measurements", "nime", ["MEASUREMENTS"], "reference_date", "CAST({x} AS TIMESTAMPTZ)"),
    ("meteoswiss_obs_daily", "measurements", "obs", ["CLOUD", "FLAGS"], "delivery_date", "CAST({x} AS TIMESTAMPTZ)"),
]
GRAN = {"meteoswiss_smn_hourly": "H", "meteoswiss_smn_tenmin": "T", "meteoswiss_smn_daily": "D",
        "meteoswiss_nime_daily": "D", "meteoswiss_obs_daily": "D"}

lists = {
    "smn": set(c.sql(f"SELECT station FROM {pq('meteoswiss_smn_stations', 'stations')}").df().station),
    "nime": set(c.sql(f"SELECT station FROM {pq('meteoswiss_nime_daily', 'stations')}").df().station),
    "obs": set(meta("obs", "stations").station_abbr.str.strip()),
}
items = {k: {i.upper() for i in json.loads((M / f"items_{k}.json").read_text())} for k in ["smn", "nime", "obs"]}

# 1. Station ids ---------------------------------------------------------------------------------
head("1. Station ids")
rows = []
for ds, tb, coll, *_ in TABLES:
    st = set(c.sql(f"SELECT DISTINCT station FROM {pq(ds, tb)}").df().station)
    rows.append({"table": f"{ds}.{tb}", "list": coll, "stations": len(st),
                 "not in list": " ".join(sorted(st - lists[coll])) or "-",
                 "not in STAC items": " ".join(sorted(st - items[coll])) or "-",
                 "list stations without rows": len(lists[coll] - st)})
show(pd.DataFrame(rows))
for k in ["smn", "nime", "obs"]:
    print(f"\n{k}: {len(lists[k])} stations in the list, {len(items[k])} STAC items; "
          f"items not in the list: {' '.join(sorted(items[k] - lists[k])) or '-'}; "
          f"list not in items: {' '.join(sorted(lists[k] - items[k])) or '-'}")
stored_smn = c.sql(f"SELECT * FROM {pq('meteoswiss_smn_stations', 'stations')}").df()
live_smn = meta("smn", "stations")
print(f"\nsmn station list: stored {len(stored_smn)}, live {len(live_smn)}; "
      f"live not stored: {' '.join(sorted(set(live_smn.station_abbr) - set(stored_smn.station))) or '-'}")
for ds, coll in [("meteoswiss_obs_daily", "obs"), ("meteoswiss_nime_daily", "nime")]:
    rows_st = set(c.sql(f"SELECT DISTINCT station FROM {pq(ds, 'measurements')}").df().station)
    print(f"{coll}: stations with rows in neither its list nor the SwissMetNet list: "
          f"{' '.join(sorted(rows_st - lists[coll] - lists['smn'])) or '-'}")

# Same abbreviation in two lists: same place? (distance in m from LV95, height, name)
nime_st = c.sql(f"SELECT * FROM {pq('meteoswiss_nime_daily', 'stations')}").df()
obs_st = meta("obs", "stations").rename(columns={
    "station_abbr": "station", "station_name": "name", "station_height_masl": "height",
    "station_coordinates_lv95_east": "lv95_east", "station_coordinates_lv95_north": "lv95_north"})
for col in ["height", "lv95_east", "lv95_north"]:
    obs_st[col] = pd.to_numeric(obs_st[col])
for other, label in [(nime_st, "nime"), (obs_st, "obs")]:
    j = stored_smn.merge(other, on="station", suffixes=("_smn", "_o"))
    j["dist_m"] = ((j.lv95_east_smn - j.lv95_east_o) ** 2 + (j.lv95_north_smn - j.lv95_north_o) ** 2) ** 0.5
    j["dh_m"] = (j.height_smn - j.height_o).abs()
    j["same_name"] = j.name_smn == j.name_o
    print(f"\nsmn and {label}: {len(j)} shared abbreviations; same name {int(j.same_name.sum())}, "
          f"within 100 m {int((j.dist_m <= 100).sum())}, within 1 km {int((j.dist_m <= 1000).sum())}, "
          f"height within 10 m {int((j.dh_m <= 10).sum())}")
    far = j[(j.dist_m > 100) | (j.dh_m > 10) | ~j.same_name]
    show(far[["station", "name_smn", "name_o", "dist_m", "dh_m"]].round(0).sort_values("dist_m", ascending=False))

# 2. Parameter codes -----------------------------------------------------------------------------
head("2. Parameter codes")
stored_par = c.sql(f"SELECT * FROM {pq('meteoswiss_smn_stations', 'parameters')}").df().set_index("parameter")
par = {"smn": stored_par,
       "nime": meta("nime", "parameters").rename(columns={
           "parameter_shortname": "parameter", "parameter_description_en": "description",
           "parameter_granularity": "granularity", "parameter_unit": "unit"}).set_index("parameter"),
       "obs": meta("obs", "parameters").rename(columns={
           "parameter_shortname": "parameter", "parameter_description_en": "description",
           "parameter_granularity": "granularity", "parameter_unit": "unit"}).set_index("parameter")}
rows = []
cmap: dict[tuple[str, str], dict[str, str]] = {}
for ds, tb, coll, names, *_ in TABLES:
    m = codes(ds, *names)
    cmap[(ds, tb)] = m
    u = units(ds, tb)
    for code, col in m.items():
        p = par[coll].loc[code] if code in par[coll].index else None
        rows.append({"table": f"{ds.removeprefix('meteoswiss_')}.{tb}", "code": code, "column": col,
                     "listed": p is not None,
                     "gran": "" if p is None else p.granularity,
                     "gran ok": p is not None and p.granularity == GRAN[ds],
                     "unit MeteoSwiss": "" if p is None else p.unit, "unit adele": u.get(col, ""),
                     "description MeteoSwiss": "" if p is None else p.description})
pt = pd.DataFrame(rows)
pd.set_option("display.max_colwidth", 70)
pd.set_option("display.width", 250)
show(pt, 80)

# 3. Inventory against the stored values ---------------------------------------------------------
head("3. Inventory against the stored values")
inv = {"smn": c.sql(f"SELECT station, parameter, data_since, data_till FROM "
                    f"{pq('meteoswiss_smn_stations', 'inventory')}").df()}
for k in ["nime", "obs"]:
    i = meta(k, "datainventory")
    inv[k] = pd.DataFrame({
        "station": i.station_abbr.str.strip(), "parameter": i.parameter_shortname.str.strip(),
        "data_since": pd.to_datetime(i.data_since.str.strip(), format="%d.%m.%Y %H:%M", utc=True),
        "data_till": pd.to_datetime(i.data_till.str.strip().replace("", None), format="%d.%m.%Y %H:%M", utc=True)})
# The manual network's inventory splits a series in two when its owner changed (MeteoSwiss until
# 2013-12-31 23:59, then SLF from 2014-01-01): one period per (station, parameter), from the first
# start to the last end (open if one period is open). Gaps between the periods are counted.
for k, v in inv.items():
    v = v.sort_values(["station", "parameter", "data_since"])
    prev_till = v.groupby(["station", "parameter"]).data_till.shift()
    v["gap"] = prev_till.notna() & (v.data_since - prev_till > pd.Timedelta(days=1))
    g = v.groupby(["station", "parameter"])
    inv[k] = pd.DataFrame({
        "data_since": g.data_since.min(),
        "data_till": g.data_till.max().where(~g.data_till.apply(lambda s: s.isna().any())),
        "periods": g.size(), "gaps": g.gap.sum()}).reset_index()
    print(f"{k} inventory: {len(v)} rows, {len(inv[k])} (station, parameter), "
          f"{int((inv[k].periods > 1).sum())} split into periods, {int(inv[k].gaps.sum())} gaps between them")
summary = []
details = []
for ds, tb, coll, names, tcol, stamp in TABLES:
    m = cmap[(ds, tb)]
    ts = stamp.format(x=tcol)  # monotone: the first and last stamps are the stamps of the first and last rows
    aggs = ", ".join(
        f"min({ts}) FILTER ({col} IS NOT NULL) AS \"f_{col}\", max({ts}) FILTER ({col} IS NOT NULL) AS \"l_{col}\""
        for col in m.values())
    w = c.sql(f"SELECT min({ts}) lo, max({ts}) hi FROM {pq(ds, tb)}").fetchall()[0]
    lo, hi = pd.Timestamp(w[0]).tz_convert("UTC"), pd.Timestamp(w[1]).tz_convert("UTC")
    firsts = c.sql(f"SELECT station, {aggs} FROM {pq(ds, tb)} GROUP BY station").df()
    have = []
    for code, col in m.items():
        f = firsts[["station", f"f_{col}", f"l_{col}"]].dropna()
        for st, a, b in f.itertuples(index=False):
            have.append({"station": st, "parameter": code, "first": a, "last": b})
    have = pd.DataFrame(have)
    for x in ["first", "last"]:
        have[x] = pd.to_datetime(have[x], utc=True)
    iv = inv[coll][inv[coll].parameter.isin(m.keys())]
    j = have.merge(iv, on=["station", "parameter"], how="outer", indicator=True)
    overl = j.data_since.le(hi) & (j.data_till.isna() | j.data_till.ge(lo))
    only_adele = j[j._merge == "left_only"]
    only_inv = j[(j._merge == "right_only") & overl]
    both = j[j._merge == "both"].copy()
    if tcol in ("reference_date", "delivery_date"):  # daily: the inventory may end a day at 23:59
        for x in ["data_since", "data_till"]:
            both[x] = both[x].dt.floor("D")
    # first value against data_since when the inventory starts inside the stored window
    s_in = both[both.data_since > lo]
    s_ok = (s_in["first"] == s_in.data_since)
    t_in = both[both.data_till.notna() & (both.data_till < hi)]
    t_ok = (t_in["last"] == t_in.data_till)
    open_ = both[both.data_till.isna()]
    stale = open_[open_["last"] < hi - pd.Timedelta(days=30)]
    after = both[both.data_till.notna() & (both["last"] > both.data_till)]
    before = both[both["first"] < both.data_since]
    summary.append({"table": f"{ds.removeprefix('meteoswiss_')}.{tb}", "window": f"{lo:%Y-%m-%d} to {hi:%Y-%m-%d}",
                    "pairs with values": len(have), "in inventory": len(both),
                    "values, not in inventory": len(only_adele), "inventory, no values": len(only_inv),
                    "first = data_since": f"{int(s_ok.sum())}/{len(s_in)}",
                    "last = data_till": f"{int(t_ok.sum())}/{len(t_in)}",
                    "values before data_since": len(before), "values after data_till": len(after),
                    "open, last value > 30 d old": len(stale)})
    for label, df in [("values, not in inventory", only_adele), ("inventory, no values", only_inv),
                      ("first != data_since", s_in[~s_ok]), ("last != data_till", t_in[~t_ok]),
                      ("values before data_since", before), ("values after data_till", after),
                      ("open, last value > 30 d old", stale)]:
        if len(df):
            d2 = df[["station", "parameter", "first", "last", "data_since", "data_till"]].copy()
            d2.insert(0, "issue", label)
            d2.insert(0, "table", f"{ds.removeprefix('meteoswiss_')}.{tb}")
            details.append(d2)
show(pd.DataFrame(summary).T.reset_index(), 20)
det = pd.concat(details) if details else pd.DataFrame()
out = ROOT / "qa" / "crosscheck_meteoswiss.csv"
det.to_csv(out, index=False)
print(f"\n{len(det)} rows of details --> {out.relative_to(ROOT)}")
for (t, issue), g in det.groupby(["table", "issue"], sort=False):
    print(f"\n### {t}: {issue} ({len(g)})")
    show(g.drop(columns=["table", "issue"]), 15)
