# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "requests>=2.31"]
# ///
"""Fetch the three reference tables of SwissMetNet (MeteoSwiss open data, STAC collection
ch.meteoschweiz.ogd-smn): the stations, the parameters, and the data inventory (which station
measures which parameter, from when to when). Tables without a time column (D22): each fetch
returns them whole, whatever the window, and the server replaces the stored ones.

Files: the three assets of the collection, https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/
ogd-smn_meta_stations.csv, ogd-smn_meta_parameters.csv, ogd-smn_meta_datainventory.csv.

Measured 2026-11-15 (WP5.7):

- Windows-1252, ";" separated, CRLF. Rewritten each day (Last-Modified 2026-11-15 04:20 UTC).
- stations: 158 rows, one per station_abbr, while the collection has 159 STAC items (the
  swissgrid project counted 159 rows on 2026-10-31). Text in four languages: only the English
  columns are kept. station_height_barometer_masl is empty for 19 stations.
- parameters: 181 rows, one per parameter_shortname; granularity T, H, D, M, Y (10 minutes,
  hour, day, month, year).
- datainventory: 19,546 rows, unique on (station_abbr, parameter_shortname); meas_cat_nr is 1 on
  every row; data_till is empty on 19,017 rows (the parameter is still measured). Stamps
  "dd.mm.yyyy HH:MM", UTC like every MeteoSwiss stamp. 19,554 rows on 2026-10-31.
"""
from __future__ import annotations

import datetime as dt
import io
import sys
import time

import pandas as pd
import requests

BASE = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "adele-fetch/1 (open data)"


def say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _csv(name: str) -> pd.DataFrame:
    url = f"{BASE}/{name}"
    for attempt in range(4):
        try:
            r = SESSION.get(url, timeout=(30, 300))
            r.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    return pd.read_csv(io.BytesIO(r.content), sep=";", encoding="cp1252", dtype=str)


def _need(df: pd.DataFrame, name: str, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"{name}: columns {missing} are missing (got {list(df.columns)})")
    if df.empty:
        raise RuntimeError(f"{name}: no rows")


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.strip(), errors="raise").astype("float64")


def _stamp(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.str.strip(), format="%d.%m.%Y %H:%M", utc=True)


def stations(name: str = "ogd-smn_meta_stations.csv") -> pd.DataFrame:
    s = _csv(name)
    _need(s, name, ["station_abbr", "station_name", "station_canton", "station_wigos_id", "station_type_en",
                    "station_dataowner", "station_data_since", "station_height_masl", "station_height_barometer_masl",
                    "station_coordinates_lv95_east", "station_coordinates_lv95_north",
                    "station_coordinates_wgs84_lat", "station_coordinates_wgs84_lon", "station_exposition_en",
                    "station_url_en"])
    return pd.DataFrame({
        "station": s["station_abbr"].str.strip(),
        "name": s["station_name"],
        "canton": s["station_canton"],
        "wigos_id": s["station_wigos_id"],
        "station_type": s["station_type_en"],
        "data_owner": s["station_dataowner"],
        "data_since": pd.to_datetime(s["station_data_since"].str.strip(), format="%d.%m.%Y").dt.date,
        "height": _num(s["station_height_masl"]),
        "barometer_height": _num(s["station_height_barometer_masl"]),
        "lv95_east": _num(s["station_coordinates_lv95_east"]),
        "lv95_north": _num(s["station_coordinates_lv95_north"]),
        "lat": _num(s["station_coordinates_wgs84_lat"]),
        "lon": _num(s["station_coordinates_wgs84_lon"]),
        "exposition": s["station_exposition_en"],
        "url": s["station_url_en"],
    })


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    st = stations()
    p = _csv("ogd-smn_meta_parameters.csv")
    _need(p, "parameters", ["parameter_shortname", "parameter_description_en", "parameter_group_en",
                            "parameter_granularity", "parameter_decimals", "parameter_datatype", "parameter_unit"])
    par = pd.DataFrame({
        "parameter": p["parameter_shortname"].str.strip(),
        "description": p["parameter_description_en"],
        "parameter_group": p["parameter_group_en"],
        "granularity": p["parameter_granularity"].str.strip(),
        "decimals": pd.to_numeric(p["parameter_decimals"], errors="raise").astype("int64"),
        "datatype": p["parameter_datatype"],
        "unit": p["parameter_unit"],
    })
    i = _csv("ogd-smn_meta_datainventory.csv")
    _need(i, "inventory", ["station_abbr", "parameter_shortname", "meas_cat_nr", "data_since", "data_till", "owner"])
    inv = pd.DataFrame({
        "station": i["station_abbr"].str.strip(),
        "parameter": i["parameter_shortname"].str.strip(),
        "meas_cat_nr": pd.to_numeric(i["meas_cat_nr"], errors="raise").astype("int64"),
        "data_since": _stamp(i["data_since"]),
        "data_till": _stamp(i["data_till"]),
        "owner": i["owner"],
    })
    say(f"{len(st)} stations, {len(par)} parameters, {len(inv)} inventory rows")
    return {"stations": st, "parameters": par, "inventory": inv}
