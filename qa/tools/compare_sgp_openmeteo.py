"""Compare what adele stored for the openmeteo_* datasets with what the swissgrid project (SGP)
downloaded from the same APIs before (WP5.10, 2026-11-16). Not a check of published figures (D12):
a check that fetch.py reads the answers as SGP did (stamps, units, keys), value by value.

    uv run --project server python -I qa/tools/compare_sgp_openmeteo.py previous-runs [--data data_nosync]
    uv run --project server python -I qa/tools/compare_sgp_openmeteo.py single-runs [--data data_nosync]

previous-runs: SGP's raw answers of the Previous Runs API (`data/nwp/raw_nosync/t1..t5/<abbr>.json.gz`,
one per station and tier, 2024-01 to 2026-10-30), read here on their own (keys
`<variable>[_<lead>]_<model>`, radiation and snowfall moved to the start of the hour, snow depth
m --> cm), joined with adele's rows on station, model, lead and time.
single-runs: SGP's table of ECMWF IFS 00 UTC runs at 10 stations
(`data/nwp/parts_nosync/single-runs/<abbr>.parquet`, long: abbr, run, datetime, lead_h, variable, value).
"""
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import duckdb
import pandas as pd

SGP = Path("/Users/ren/switchdrive/backup/_EnTr/projects/swissgrid_project/data/nwp")
HOURLY = ("shortwave_radiation", "diffuse_radiation", "snowfall")
INSTANT = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "temperature_2m", "snow_depth")
LEADS = ("previous_day1", "previous_day2")
MODELS = ("ecmwf_ifs025", "icon_eu", "gfs_global", "meteofrance_arpege_europe", "gem_global",
          "ecmwf_aifs025_single", "meteoswiss_icon_ch2", "icon_d2")


def split_key(key: str, alone: str | None = None) -> tuple[str, str, str] | None:
    """`cloud_cover_previous_day1_icon_eu` --> (cloud_cover, previous_day1, icon_eu). `alone`: the
    model of a request that named one model, whose keys have no model suffix (SGP tier t5)."""
    model = alone or next((m for m in MODELS if key.endswith("_" + m)), None)
    if model is None:
        return None
    rest = key if alone else key[: -len(model) - 1]
    lead = next((ld for ld in LEADS if rest.endswith("_" + ld)), "day0")
    var = rest[: -len(lead) - 1] if lead != "day0" else rest
    return (var, lead, model) if var in HOURLY + INSTANT else None


def sgp_previous_runs(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for tier in ("t1", "t2", "t3", "t4", "t5"):
        for f in sorted((SGP / "raw_nosync" / tier).glob("*.json.gz")):
            a = json.loads(gzip.decompress(f.read_bytes()))
            t = pd.to_datetime(pd.Series(a["hourly"]["time"])).dt.tz_localize("UTC")
            for key, values in a["hourly"].items():
                parts = split_key(key, "icon_d2" if tier == "t5" else None)
                if parts is None:
                    continue
                var, lead, model = parts
                v = pd.to_numeric(pd.Series(values, dtype="object")).astype("float64")
                ts = t - pd.Timedelta(hours=1) if var in HOURLY else t
                if var == "snow_depth":
                    v = v * 100
                keep = v.notna() & (ts >= start) & (ts < end)
                if keep.any():
                    rows.append(pd.DataFrame({"station": f.name.split(".")[0], "model": model, "lead": lead,
                                              "time": ts[keep].to_numpy(), "variable": var, "sgp": v[keep].to_numpy()}))
    return pd.concat(rows, ignore_index=True)


def adele_long(con, data: Path, ds: str, start: pd.Timestamp, end: pd.Timestamp, keys: list[str]) -> pd.DataFrame:
    out = []
    for table, time_col, names in (("hourly", "delivery_start", HOURLY), ("instant", "valid_at", INSTANT)):
        files = sorted((data / ds / table).glob("*.parquet"))
        if not files:
            continue
        df = con.execute(f"SELECT * FROM read_parquet({[str(f) for f in files]}) WHERE {time_col} >= $s AND "
                         f"{time_col} < $e", {"s": start, "e": end}).fetchdf()
        cols = [c for c in names if c in df.columns]
        long = df.melt(id_vars=keys + [time_col], value_vars=cols, var_name="variable", value_name="adele")
        out.append(long.rename(columns={time_col: "time"}).dropna(subset=["adele"]))
    return pd.concat(out, ignore_index=True)


def report(m: pd.DataFrame, by: list[str]) -> None:
    both = m.dropna(subset=["sgp", "adele"])
    both = both.assign(diff=(both["adele"] - both["sgp"]).abs())
    g = both.groupby(by).agg(pairs=("diff", "size"), equal_pct=("diff", lambda d: round(100 * (d < 1e-6).mean(), 2)),
                             max_abs=("diff", "max")).reset_index()
    with pd.option_context("display.max_rows", 200, "display.width", 200):
        print(g.to_string(index=False))
    only_sgp = m["adele"].isna() & m["sgp"].notna()
    only_adele = m["sgp"].isna() & m["adele"].notna()
    print(f"pairs {len(both):,}, equal {100 * (both['diff'] < 1e-6).mean():.3f} %, max abs diff {both['diff'].max()}; "
          f"values only in SGP {only_sgp.sum():,}, only in adele {only_adele.sum():,}")
    if only_sgp.any():
        print(m[only_sgp].groupby(["model", "lead", "variable"]).size().to_string())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["previous-runs", "single-runs"])
    p.add_argument("--data", default="data_nosync", type=Path)
    p.add_argument("--start", default="2026-10-24")
    p.add_argument("--end", default="2026-10-30T22:00", help="SGP's last radiation hour is 2026-10-30 22:00 UTC")
    a = p.parse_args()
    start, end = pd.Timestamp(a.start, tz="UTC"), pd.Timestamp(a.end, tz="UTC")
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    if a.what == "previous-runs":
        sgp = sgp_previous_runs(start, end)
        ad = adele_long(con, a.data, "openmeteo_previous_runs", start, end, ["station", "model", "lead"])
        m = sgp.merge(ad, on=["station", "model", "lead", "time", "variable"], how="outer")
        report(m, ["model", "lead", "variable"])
    else:
        files = [str(f) for f in sorted((SGP / "parts_nosync" / "single-runs").glob("*.parquet"))]
        sgp = con.execute(f"SELECT * FROM read_parquet({files})").fetchdf().rename(columns={"abbr": "station", "run": "init_time", "value": "sgp"})
        sgp = sgp[(sgp["init_time"] >= start) & (sgp["init_time"] < end)]
        sgp["time"] = sgp["datetime"]  # SGP: radiation at the start of the hour, as adele
        sgp["model"] = "ecmwf_ifs"
        ad = adele_long(con, a.data, "openmeteo_single_runs", pd.Timestamp("2000-01-01", tz="UTC"),
                        pd.Timestamp("2100-01-01", tz="UTC"), ["init_time", "station", "model"])
        ad = ad[(ad["model"] == "ecmwf_ifs") & ad["station"].isin(sgp["station"].unique())
                & (ad["init_time"] >= start) & (ad["init_time"] < end)]
        m = sgp[["init_time", "station", "model", "time", "variable", "sgp"]].merge(
            ad, on=["init_time", "station", "model", "time", "variable"], how="outer")
        report(m, ["variable"])


if __name__ == "__main__":
    main()
