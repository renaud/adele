"""datasets/meteoswiss_*/fetch.py on synthetic station files: which files a window reads, MeteoSwiss's
stamps converted (SYNOP hours before 2018, clock hours, the reading time of the snow depth, the UTC day
that starts 20 minutes early before 2018, the days of 06 to 06 UTC), the visual flags as booleans, and the
stops (rows of another station, a value that is not a number, a flag that is not 0 or 1). No network:
_items and _get are replaced, the files are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
UTC = dt.timezone.utc


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_fetch", DATASETS / name / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


def csv_file(abbr: str, columns: list[str], rows: list[tuple]) -> bytes:
    """A station file as MeteoSwiss writes it: Windows-1252, ';', CRLF, empty field = missing."""
    lines = [";".join(["station_abbr", "reference_timestamp", *columns])]
    lines += [";".join([abbr, stamp, *("" if v is None else str(v) for v in values)]) for stamp, *values in rows]
    return ("\r\n".join(lines) + "\r\n").encode("cp1252")


def item(abbr: str, prefix: str, assets: dict[str, str]) -> dict:
    """A STAC item: asset kind (h_recent, h_historical_2010-2019, ...) --> its `updated` field."""
    return {"id": abbr, "assets": {f"{prefix}_{abbr}_{k}.csv": {"href": f"mem://{abbr}/{k}", "updated": u}
                                   for k, u in assets.items()}}


def serve(mod, monkeypatch, items: list[dict], files: dict[str, bytes]) -> list[str]:
    """Replace the network: _items returns `items`, _get the file of an href (None if unknown)."""
    asked = []
    monkeypatch.setattr(mod, "_items", lambda: items)

    def get(url):
        asked.append(url)
        return files.get(url)

    monkeypatch.setattr(mod, "_get", get)
    return asked


HOURLY_ITEM = item("abc", "ogd-smn", {"h_recent": "2026-11-15T03:33:20Z",
                                      "h_historical_2010-2019": "2026-02-18T21:06:17Z",
                                      "h_historical_2020-2029": "2026-02-18T21:04:29Z"})


def plan(mod, it, start, end):
    lo, hi = mod._stamps(t(start), t(end))
    recent, hist = mod._plan(it, lo, hi)
    return (recent or "").rsplit("/", 1)[-1], [h[0].rsplit("/", 1)[-1] for h in hist]


def test_hourly_plan_reads_only_the_files_of_the_window():
    m = load("meteoswiss_smn_hourly")
    assert plan(m, HOURLY_ITEM, "2016-03-01", "2016-04-01") == ("", ["h_historical_2010-2019"])
    assert plan(m, HOURLY_ITEM, "2026-09-01", "2026-11-16") == ("h_recent", [])
    # the decade boundaries of the backfill: each window reads one decade file
    assert plan(m, HOURLY_ITEM, "2015-01-01", "2019-12-31T23:00") == ("", ["h_historical_2010-2019"])
    assert plan(m, HOURLY_ITEM, "2020-01-01T00:00", "2025-12-31T23:00")[1] == ["h_historical_2020-2029"]
    # the hour 23:00-24:00 of 31 December: its mean is stamped 00:00 (new file), its snow reading 23:00 (old)
    assert plan(m, HOURLY_ITEM, "2019-12-31T23:00", "2020-01-01T00:00") == (
        "", ["h_historical_2010-2019", "h_historical_2020-2029"])


def test_hourly_plan_before_the_yearly_rewrite_reads_the_recent_file():
    """In January, before MeteoSwiss rewrites the decade file (2026: 18 February), it ends a year early."""
    m = load("meteoswiss_smn_hourly")
    old = item("abc", "ogd-smn", {"h_recent": "2026-01-10T03:00:00Z", "h_historical_2020-2029": "2025-02-18T21:00:00Z"})
    assert plan(m, old, "2025-11-01", "2026-01-10") == ("h_recent", [])


def test_hourly_stamps_synop_and_clock_hours_and_snow_reading(monkeypatch):
    m = load("meteoswiss_smn_hourly")
    cols = ["gre000h0", "tre200h0", "htoauths"]
    hist = csv_file("ABC", cols, [("31.12.2017 22:00", 0, -1.5, 10), ("31.12.2017 23:00", 0, -1.6, 11),
                                  ("01.01.2018 00:00", 0, -1.7, 12), ("01.01.2018 01:00", 0, -1.8, None)])
    serve(m, monkeypatch, [HOURLY_ITEM], {"mem://abc/h_historical_2010-2019": hist})
    out = m.fetch(t("2017-12-31T21:00"), t("2018-01-01T01:00"))
    meas = out["measurements"].sort_values("delivery_start")
    # SYNOP hours (stamp T covers T - 20 min to T + 40 min) start at minute 40; clock hours at T - 60 min
    assert [str(x) for x in meas["delivery_start"]] == [
        "2017-12-31 21:40:00+00:00", "2017-12-31 22:40:00+00:00", "2017-12-31 23:00:00+00:00", "2018-01-01 00:00:00+00:00"]
    assert list(meas["temperature"]) == [-1.5, -1.6, -1.7, -1.8]
    assert meas["diffuse_radiation"].isna().all()  # a parameter the station does not publish: empty
    snow = out["snow_depth"].sort_values("valid_at")
    # the reading belongs to the end of MeteoSwiss's hour: T + 40 min before 2018, T after
    assert [str(x) for x in snow["valid_at"]] == [
        "2017-12-31 22:40:00+00:00", "2017-12-31 23:40:00+00:00", "2018-01-01 00:00:00+00:00"]
    assert list(snow["snow_depth"]) == [10, 11, 12]


def test_recent_file_wins_and_cuts_the_historical_part(monkeypatch):
    m = load("meteoswiss_smn_hourly")
    cols = ["gre000h0"]
    it = item("abc", "ogd-smn", {"h_recent": "2026-01-10T03:00:00Z", "h_historical_2020-2029": "2025-02-18T21:00:00Z"})
    recent = csv_file("ABC", cols, [("31.12.2025 23:00", 5), ("01.01.2026 00:00", 6)])
    asked = serve(m, monkeypatch, [it], {"mem://abc/h_recent": recent})
    out = m.fetch(t("2025-12-31T21:00"), t("2025-12-31T23:00"))
    assert list(out["measurements"]["global_radiation"]) == [5]
    assert asked == ["mem://abc/h_recent"]  # the decade file ends a year early: not read


def test_parse_stops_on_another_station_and_on_text(monkeypatch):
    m = load("meteoswiss_smn_hourly")
    for bad in (csv_file("XYZ", ["gre000h0"], [("01.06.2026 12:00", 500)]),
                csv_file("ABC", ["gre000h0"], [("01.06.2026 12:00", "n/a")])):
        serve(m, monkeypatch, [HOURLY_ITEM], {"mem://abc/h_recent": bad})
        with pytest.raises((RuntimeError, ValueError)):
            m.fetch(t("2026-06-01T10:00"), t("2026-06-01T12:00"))


def test_tenmin_stamp_is_the_end_of_the_10_minutes(monkeypatch):
    m = load("meteoswiss_smn_tenmin")
    it = item("abc", "ogd-smn", {"t_recent": "2026-11-15T03:00:00Z", "t_historical_2020-2029": "2026-02-18T21:00:00Z"})
    recent = csv_file("ABC", ["gre000z0", "sre000z0"], [("01.06.2026 12:00", 800, 10), ("01.06.2026 12:10", 790, None)])
    serve(m, monkeypatch, [it], {"mem://abc/t_recent": recent})
    out = m.fetch(t("2026-06-01T11:50"), t("2026-06-01T12:10"))
    assert [str(x) for x in out["delivery_start"]] == ["2026-06-01 11:50:00+00:00", "2026-06-01 12:00:00+00:00"]
    assert out["sunshine"].isna().tolist() == [False, True]
    assert m._stamps(t("2025-12-31T23:50"), t("2026-01-01T00:00"))[0] == t("2026-01-01T00:00")


def test_daily_day_starts_20_minutes_early_before_2018(monkeypatch):
    m = load("meteoswiss_smn_daily")
    it = item("abc", "ogd-smn", {"d_recent": "2026-11-15T03:00:00Z", "d_historical": "2026-02-18T21:00:00Z"})
    hist = csv_file("ABC", ["tre200d0", "rre150d0"], [("31.12.2017 00:00", 1.0, 2.0), ("01.01.2018 00:00", 3.0, 4.0)])
    serve(m, monkeypatch, [it], {"mem://abc/d_historical": hist})
    out = m.fetch(t("2017-12-30T23:00"), t("2018-01-02"))
    assert [str(x) for x in out["delivery_start"]] == ["2017-12-30 23:40:00+00:00", "2018-01-01 00:00:00+00:00"]
    assert list(out["reference_date"]) == [dt.date(2017, 12, 31), dt.date(2018, 1, 1)]
    assert list(out["precipitation_06utc"]) == [2.0, 4.0]


def test_nime_day_starts_at_06_utc_and_stations_come_whole(monkeypatch):
    m = load("meteoswiss_nime_daily")
    it = item("abc", "ogd-nime", {"d_recent": "2026-11-15T03:00:00Z", "d_historical": "2026-02-18T21:00:00Z"})
    recent = csv_file("ABC", ["rre150d0", "hns000d0", "hto000d0"], [("14.11.2026 00:00", 1.2, 3, 10)])
    meta = ("station_abbr;station_name;station_canton;station_wigos_id;station_type_en;station_dataowner;"
            "station_data_since;station_height_masl;station_height_barometer_masl;station_coordinates_lv95_east;"
            "station_coordinates_lv95_north;station_coordinates_wgs84_lat;station_coordinates_wgs84_lon;"
            "station_exposition_en;station_url_en\r\n"
            "ABC;Château-d'Oex;VD;0-756-0-ABC;Manual;MeteoSchweiz;01.01.1931;985;;2577000;1147000;46.48;7.14;plain;https://x\r\n"
            ).encode("cp1252")
    serve(m, monkeypatch, [it], {"mem://abc/d_recent": recent, m.STATIONS: meta})
    out = m.fetch(t("2026-11-14"), t("2026-11-15"))
    meas = out["measurements"]
    assert [str(x) for x in meas["delivery_start"]] == ["2026-11-14 06:00:00+00:00"]
    assert list(meas["reference_date"]) == [dt.date(2026, 11, 14)]
    st = out["stations"]
    assert list(st["name"]) == ["Château-d'Oex"] and st["barometer_height"].isna().all()
    assert list(st["data_since"]) == [dt.date(1931, 1, 1)]


def test_obs_flags_are_booleans_and_empty_stays_empty(monkeypatch):
    m = load("meteoswiss_obs_daily")
    it = item("abc", "ogd-obs", {"d_recent": "2026-11-15T03:00:00Z", "d_historical": "2026-01-01T00:00:00Z"})
    cols = ["nto000d0", "w5p002d0", "nto002d0", "nto008d0", "est000d0", "w1p012d0", "w2p002d0", "w2p001d0", "w3p002d0"]
    recent = csv_file("ABC", cols, [("13.11.2026 00:00", 96, None, 0, 1, 0, 1, 0, 0, 0)])
    serve(m, monkeypatch, [it], {"mem://abc/d_recent": recent})
    out = m.fetch(t("2026-11-12T23:00"), t("2026-11-13T23:00"))  # the local day 2026-11-13 (CET)
    row = out.iloc[0]
    assert row["delivery_date"] == dt.date(2026, 11, 13)
    assert pd.isna(row["fog_day"]) and bool(row["dark_day"]) is True and bool(row["serene_day"]) is False
    bad = csv_file("ABC", cols, [("13.11.2026 00:00", 96, 2, 0, 1, 0, 1, 0, 0, 0)])
    serve(m, monkeypatch, [it], {"mem://abc/d_recent": bad})
    with pytest.raises(RuntimeError, match="w5p002d0"):
        m.fetch(t("2026-11-12T23:00"), t("2026-11-13T23:00"))
