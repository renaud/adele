"""datasets/iem_metar/fetch.py on synthetic answers of IEM: the parser of one METAR, and which rows of
an answer are kept (rebuilt rows dropped, a correction replaces its report, a cut answer stops). No
network: _get is replaced."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
UTC = dt.timezone.utc


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("iem_metar_fetch", DATASETS / "iem_metar" / "fetch.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_layers_cb_and_the_trend_is_not_read(mod):
    p = mod.parse_metar("LSZH 010020Z 17005G15KT 340V080 6000 -SHRA SCT004 BKN009CB OVC050 10/M01 Q1015 TEMPO 4500 BKN012")
    assert (p["cover_1"], p["base_1"], p["type_1"]) == ("SCT", 400, None)
    assert (p["cover_2"], p["base_2"], p["type_2"]) == ("BKN", 900, "CB")
    assert p["cover_3"] == "OVC" and p["base_3"] == 5000 and p["cover_4"] is None
    assert (p["ceiling"], p["lowest_base"], p["cloud_report"]) == (900, 400, "layers")
    assert p["visibility"] == 6000  # 4500 belongs to the trend
    assert (p["wind_direction"], p["wind_speed"], p["wind_gust"], p["wind_from"], p["wind_to"]) == (170, 5, 15, 340, 80)
    assert (p["temperature"], p["dew_point"], p["qnh"], p["weather"]) == (10, -1, 1015, "-SHRA")
    assert p["trend"] == "TEMPO 4500 BKN012" and p["unknown"] == 0


@pytest.mark.parametrize("text, report", [
    ("LSZH 010020Z AUTO 12003KT CAVOK 18/16 Q1014 NOSIG", "cavok"),
    ("LSMP 010020Z AUTO 12003KT 9999NDV NCD 18/16 Q1014 RMK", "ncd"),
    ("LSZH 010020Z 12003KT 9999 NSC 18/16 Q1014", "nsc"),
    ("LSZH 010020Z 12003KT 0200 FG VV001 M02/M02 Q1030", "vv"),
    ("LSZH 010020Z 12003KT 9999 ////// 18/16 Q1014", "unknown"),
    ("LSZH 010020Z 12003KT 9999 18/16 Q1014", "none"),
])
def test_what_an_empty_layer_column_means(mod, text, report):
    p = mod.parse_metar(text)
    assert p["cloud_report"] == report and p["cover_1"] in (None, "///") and p["ceiling"] is None


def test_a_layer_without_base_and_a_cb_without_cover(mod):
    p = mod.parse_metar("LSZG 010020Z 12003KT 9999 BKN/// FEW/// //////TCU 18/16 Q1014")
    assert (p["cover_1"], p["base_1"], p["cover_2"], p["base_2"]) == ("BKN", None, "FEW", None)
    assert (p["cover_3"], p["base_3"], p["type_3"]) == ("///", None, "TCU")
    assert p["cloud_report"] == "layers" and p["ceiling"] is None


def test_visibility(mod):
    assert mod.parse_metar("LSZH 010020Z 00000KT 9999 18/16 Q1014")["visibility"] == 10000
    p = mod.parse_metar("LSZH 010020Z 00000KT 3000 1200NE 18/16 Q1014")
    assert (p["visibility"], p["visibility_min"], p["visibility_min_direction"]) == (3000, 1200, "NE")
    assert mod.parse_metar("LSMP 010020Z 00000KT ////NDV 18/16 Q1014")["visibility"] is None


def test_calm_and_variable_wind_and_missing_values(mod):
    p = mod.parse_metar("LSZH 010020Z 00000KT CAVOK ///// Q////")
    assert p["wind_speed"] == 0 and p["wind_direction"] is None and p["qnh"] is None and p["temperature"] is None
    p = mod.parse_metar("LSZH 010020Z VRB03KT CAVOK M05/M07 Q0998")
    assert p["wind_variable"] and p["wind_direction"] is None and p["temperature"] == -5 and p["qnh"] == 998


def test_corrections_runway_groups_and_a_closing_equals_sign(mod):
    p = mod.parse_metar("COR LSGG 020450Z 20004KT 1300NE R04/1000D R22/0900U BCFG VV/// M01/M01 Q1025 R88/29//// RERA NOSIG=")
    assert p["corrected"] and p["rvr"] == "R04/1000D R22/0900U" and p["cloud_report"] == "vv"
    assert p["vertical_visibility"] is None and p["weather_recent"] == "RA" and p["trend"] == "NOSIG" and p["unknown"] == 0
    assert mod.parse_metar("LSGG 020450Z 20004KT 9999 18/16 Q1025 NOSIG BOGUS")["trend"] == "NOSIG BOGUS"
    assert mod.parse_metar("LSGG 020450Z AUTO 20004KT 9999 BOGUS 18/16 Q1025")["unknown"] == 1


CSV_HEAD = "station,valid,metar\n"


def test_rows_drops_rebuilt_reports_and_prefers_the_correction(mod):
    text = (CSV_HEAD + "LSGG,2023-07-04 04:00,LSGG 040400Z AUTO 20004KT 18/16 RMK IEM_GHCNH\n"
            "LSGG,2023-07-04 04:20,LSGG 040420Z 20004KT 9999 18/16 Q1025\n"
            "LSGG,2023-07-04 04:20,COR LSGG 040420Z 20004KT 8000 18/16 Q1025\n"
            "LSGG,2023-07-04 04:50,LSGG 040450Z 20004KT 9999 18/16 Q1025\n")
    rows = mod._rows(text, ["LSGG"])
    assert [v.strftime("%H:%M") for _, v, _ in rows] == ["04:20", "04:50"]
    assert rows[0][2].startswith("COR ")


def test_a_cut_answer_and_another_station_stop_the_fetch(mod):
    with pytest.raises(RuntimeError, match="cut"):
        mod._rows(CSV_HEAD + "LSGG,2023-07-04 04:20,LSGG 040420Z 2", ["LSGG"])
    with pytest.raises(RuntimeError, match="unexpected row"):
        mod._rows(CSV_HEAD + "KJFK,2023-07-04 04:20,KJFK 040420Z\n", ["LSGG"])


def half_hours(start, end, codes):
    out = [CSV_HEAD]
    for c in codes:
        v = start
        while v < end:
            if v.minute in (20, 50):
                out.append(f"{c},{v:%Y-%m-%d %H:%M},{c} {v:%d%H%M}Z AUTO 20004KT 9999 FEW030 18/16 Q1025\n")
            v += dt.timedelta(minutes=10)
    return "".join(out)


def test_fetch_returns_both_tables_and_stops_when_a_civil_station_is_missing(mod, monkeypatch):
    codes = [s["station"] for s in mod.stations()]
    assert len(codes) == 8
    monkeypatch.setattr(mod, "_get", lambda lo, hi, cs: half_hours(lo, hi, cs))
    out = mod.fetch(t("2024-01-01"), t("2024-01-03"))
    assert len(out["reports"]) == 8 * 96 and out["stations"]["station"].tolist() == sorted(codes)
    assert str(out["reports"]["qnh"].dtype) == "Int64" and out["reports"]["type_1"].isna().all()
    assert out["reports"]["valid_at"].dt.tz is not None
    monkeypatch.setattr(mod, "_get", lambda lo, hi, cs: half_hours(lo, hi, [c for c in cs if c != "LSZH"]))
    with pytest.raises(RuntimeError, match="LSZH"):
        mod.fetch(t("2024-01-01"), t("2024-01-03"))


def test_fetch_stops_when_an_answer_ends_early(mod, monkeypatch):
    monkeypatch.setattr(mod, "_get", lambda lo, hi, cs: half_hours(lo, lo + dt.timedelta(days=2), cs))
    with pytest.raises(RuntimeError, match="the answer is cut"):
        mod.fetch(t("2024-01-01"), t("2024-01-09"))


def test_long_windows_are_split(mod, monkeypatch):
    asked = []
    monkeypatch.setattr(mod, "_get", lambda lo, hi, cs: (asked.append((lo, hi)), half_hours(lo, hi, cs))[1])
    monkeypatch.setattr(mod, "MAX_DAYS", 3)
    mod.fetch(t("2024-01-01"), t("2024-01-08"))
    assert len(asked) == 3 and asked[-1][1] == t("2024-01-08")
