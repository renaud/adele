"""datasets/pronovo_production/fetch.py on synthetic files in Pronovo's formats: the end stamps,
the units, the capacity of the month's last quarter-hour (kVA, then kW), the choice between the
definitive and the provisional file, the archive CSVs of 2020-2022 (the fall-back night, the
Excel serials), the empty window. No network: the listings and the downloads are replaced."""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

FETCH = Path(__file__).resolve().parents[2] / "datasets" / "pronovo_production" / "fetch.py"
UTC = dt.timezone.utc
ZRH = ZoneInfo("Europe/Zurich")
QH = dt.timedelta(minutes=15)


@pytest.fixture
def pf():
    spec = importlib.util.spec_from_file_location("pronovo_fetch", FETCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def month_ends(y: int, m: int) -> list[dt.datetime]:
    """The end stamps (UTC) of the quarter-hours of a local month."""
    lo = dt.datetime(y, m, 1, tzinfo=ZRH).astimezone(UTC)
    hi = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=ZRH).astimezone(UTC)
    n = int((hi - lo) / QH)
    return [lo + (i + 1) * QH for i in range(n)]


def zip_csv(title: str, ends: list[dt.datetime], techs: dict[str, tuple[str, str]], unit: str = "kVA",
            cap: tuple[str, str] = ("1000", "7"), local_shift: dt.timedelta = dt.timedelta(0)) -> bytes:
    """A CSV of a zip: techs = {name: (+A cell, -A cell)} for every row; the capacity in the last
    quarter-hour of each local month (it ends at local 00:00 on day 1)."""
    head1 = f"{title};Erstellt: 13.03.2026 02:00:00;" + ";".join(f"{t};;;" for t in techs)
    head2 = "Koordinierte Weltzeit (UTC);Mitteleuropäische Zeit (CET/CEST);" + ";".join(
        f"+A.{t} [kWh];-A.{t} [kWh];Leistung.{t} [{unit}];Anzahl.{t}" for t in techs)
    lines = [head1, head2]
    for e in ends:
        loc = (e + local_shift).astimezone(ZRH)
        e_loc = e.astimezone(ZRH)
        last = (e_loc.day, e_loc.hour, e_loc.minute) == (1, 0, 0)
        cells = [f"{e:%d.%m.%Y %H:%M}", f"{loc:%d.%m.%Y %H:%M}"]
        for p, mns in techs.values():
            cells += [p, mns, cap[0] if last else "", cap[1] if last else ""]
        lines.append(";".join(cells))
    return "\r\n".join(lines).encode("latin-1")


def make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def serve(pf, monkeypatch, files: dict[str, dict[str, bytes]]):
    """files = {folder ("" or "Archiv/2021/DE/"): {name: bytes}}."""
    def listing(url):
        folder = url[len(pf.BASE):]
        return {n: f"mem://{folder}{n}" for n in files.get(folder, {})}

    def download(url):
        path = url[len("mem://"):]
        folder, name = path.rsplit("/", 1) if "/" in path else ("", path)
        return files[folder + "/" if folder else ""][name]

    monkeypatch.setattr(pf, "listing", listing)
    monkeypatch.setattr(pf, "download", download)


def a_zip(y: int, m: int, kind: str, pv: str = "100", cantons: dict[str, list] | None = None,
          unit: str = "kVA") -> tuple[str, bytes]:
    """A zip of one month (Monat_prov) or of the quarter of `m` (Quartal_def, named by the last month)."""
    if kind == "prov":
        name, ms = f"{y}{m:02d}_CH_Total_Monat_prov", [m]
    else:
        q = (m - 1) // 3 * 3 + 3
        name, ms = f"{y}{q:02d}_CH_Total_Quartal_def", [q - 2, q - 1, q]
    ends = [e for mm in ms for e in month_ends(y, mm)]
    members = {f"{name}.csv": zip_csv(f"CH_Total_{kind}", ends,
                                      {"Photovoltaik": ("1", pv), "Kernenergie": ("2", "800"), "Geothermie": ("", "")},
                                      unit=unit)}
    for c, c_ends in (cantons if cantons is not None else {"ZH": ends}).items():
        members[f"{name[:6]}_CH_PV_{c}_{kind}.csv"] = zip_csv(f"CH_PV_{c}", c_ends, {"Photovoltaik": ("1", pv)},
                                                               unit=unit)
    return f"{name}.zip", make_zip(members)


def test_end_stamps_units_and_capacity(pf, monkeypatch):
    name, data = a_zip(2026, 2, "prov", pv="250")
    serve(pf, monkeypatch, {"": {name: data}})
    out = pf.fetch(dt.datetime(2026, 1, 31, 23, tzinfo=UTC), dt.datetime(2026, 2, 28, 23, tzinfo=UTC))
    bt = out["by_technology"]
    pv = bt[bt["technology"] == "pv"].sort_values("delivery_start")
    assert len(pv) == 28 * 96
    # the first row of the file ends at local 00:15 on 1 Feb: it starts at local 00:00 = 2026-01-31 23:00 UTC
    assert pv["delivery_start"].iloc[0] == pd.Timestamp("2026-01-31 23:00", tz="UTC")
    assert pv["production_mwh"].iloc[0] == pytest.approx(0.25)
    assert pv["production_mw"].iloc[0] == pytest.approx(1.0)
    assert pv["auxiliary_mwh"].iloc[0] == pytest.approx(0.001)
    assert set(pv["version"]) == {"prov"} and pv["suspect"].isna().all()
    assert set(bt["technology"]) == {"pv", "nuclear"}  # Geothermie is empty all month: no row
    cap = out["capacity_by_technology"].set_index("technology")
    assert cap.loc["pv", "delivery_month"] == dt.date(2026, 2, 1)
    assert cap.loc["pv", "capacity_mva"] == pytest.approx(1.0) and pd.isna(cap.loc["pv", "capacity_mw"])
    assert cap.loc["pv", "units"] == 7
    assert len(out["pv_by_canton"]) == 28 * 96 and set(out["pv_by_canton"]["canton"]) == {"ZH"}
    assert out["pv_capacity_by_canton"]["canton"].tolist() == ["ZH"]


def test_capacity_in_kw_goes_to_its_own_column(pf, monkeypatch):
    name, data = a_zip(2026, 2, "prov", unit="kW")
    serve(pf, monkeypatch, {"": {name: data}})
    cap = pf.fetch(dt.datetime(2026, 2, 10, tzinfo=UTC), dt.datetime(2026, 2, 11, tzinfo=UTC))["capacity_by_technology"]
    assert cap["capacity_mw"].notna().all() and cap["capacity_mva"].isna().all()


def test_the_complete_definitive_file_wins(pf, monkeypatch):
    p_name, p_data = a_zip(2026, 2, "prov", pv="100")
    d_name, d_data = a_zip(2026, 2, "def", pv="120")
    serve(pf, monkeypatch, {"": {p_name: p_data, d_name: d_data}})
    out = pf.fetch(dt.datetime(2026, 2, 10, tzinfo=UTC), dt.datetime(2026, 2, 11, tzinfo=UTC))
    assert set(out["by_technology"]["version"]) == {"def"}
    assert out["by_technology"].query("technology == 'pv'")["production_mwh"].iloc[0] == pytest.approx(0.12)


def test_a_canton_missing_from_the_definitive_file_comes_from_the_provisional_one(pf, monkeypatch):
    feb = month_ends(2026, 2)
    q1 = month_ends(2026, 1) + feb + month_ends(2026, 3)
    d_name, d_data = a_zip(2026, 2, "def", cantons={"ZH": q1, "GL": [e for e in q1 if e not in feb[:-1]]})
    p_name, p_data = a_zip(2026, 2, "prov", cantons={"ZH": feb, "GL": feb})
    serve(pf, monkeypatch, {"": {p_name: p_data, d_name: d_data}})
    out = pf.fetch(dt.datetime(2026, 2, 10, tzinfo=UTC), dt.datetime(2026, 2, 11, tzinfo=UTC))
    versions = out["pv_by_canton"].groupby("canton")["version"].agg(set).to_dict()
    assert versions == {"ZH": {"def"}, "GL": {"prov"}}


def test_a_local_stamp_that_is_not_the_utc_one_fails(pf, monkeypatch):
    ends = month_ends(2026, 2)
    raw = zip_csv("CH_Total", ends, {"Photovoltaik": ("1", "2")}, local_shift=dt.timedelta(hours=1))
    with pytest.raises(RuntimeError, match="local stamp"):
        pf.read_zip_csv(raw, "x.csv")


def test_an_unknown_technology_fails(pf):
    raw = zip_csv("CH_Total", month_ends(2026, 2)[:4], {"Wasserstoff": ("1", "2")})
    with pytest.raises(RuntimeError, match="unknown technology"):
        pf.read_zip_csv(raw, "x.csv")


def archive_csv(rows: list[tuple[str, str]]) -> bytes:
    head = ["# Datum der Auswertung: 13.11.2021", "# Zeitraum der Auswertung: 01.10.2021 - 31.10.2021",
            "Datum Zeit;Photovoltaik (kWh);Wasser (kWh);"]
    return "\r\n".join(head + [f"{s};{v};1'000.5;" for s, v in rows]).encode("latin-1")


def local_end_stamps(y: int, m: int) -> list[str]:
    """The local end stamps of a month as Pronovo writes them: the repeated hour comes twice."""
    return [f"{e.astimezone(ZRH):%d.%m.%Y %H:%M}" for e in month_ends(y, m)]


def archive_month(pf, monkeypatch, y: int, m: int, rows: list[tuple[str, str]]) -> dict[str, list]:
    """The rows of one month of 2020-2022, below fetch(): its tables of capacity are empty, and an
    empty table of dates needs pyarrow (see _frame)."""
    data = archive_csv(rows)
    serve(pf, monkeypatch, {f"Archiv/{y}/DE/": {f"Lastgangprofile_{m:02d}.{y}.csv": data}})
    return pf.month_rows(pf.choose(pf.Files(), y, m), y, m)


def test_archive_csv_reads_the_repeated_hour_as_summer_time_first(pf, monkeypatch):
    stamps = local_end_stamps(2021, 10)
    assert len(stamps) == 2980 and len(set(stamps)) == 2976  # 02:00-02:45 come twice
    rows = archive_month(pf, monkeypatch, 2021, 10, [(s, str(i)) for i, s in enumerate(stamps)])
    bt = pf._frame("by_technology", rows["by_technology"])
    pv = bt.query("technology == 'pv'").sort_values("delivery_start")
    assert len(pv) == 2980 and pv["delivery_start"].is_unique
    assert pv["delivery_start"].iloc[0] == pd.Timestamp("2021-09-30 22:00", tz="UTC")
    # the value follows the file order, so it increases with the UTC start only if the first 02:00 is CEST
    assert pv["production_mwh"].is_monotonic_increasing
    assert set(pv["version"]) == {"archive"} and pv["auxiliary_mwh"].isna().all()
    hydro = bt.query("technology == 'hydro_total'")
    assert hydro["production_mwh"].iloc[0] == pytest.approx(1.0005)  # the thousands mark
    assert rows["capacity_by_technology"] == [] and rows["pv_by_canton"] == []


def test_archive_csv_recovers_a_stamp_written_as_an_excel_serial(pf):
    stamps = local_end_stamps(2021, 3)[:40]
    rows = [(s, "5") for s in stamps]
    # 01.03.2021 08:30 local, written as its serial with a thousands mark
    i = stamps.index("01.03.2021 08:30")
    rows[i] = ("44'256.35", "5")
    end, techs = pf.read_archive_csv(archive_csv(rows), "Lastgangprofile_03.2021.csv")
    assert end.iloc[i] == pd.Timestamp("2021-03-01 07:30", tz="UTC")
    rows[i] = ("44'256.10", "5")  # a serial that is not the stamp of its position
    with pytest.raises(RuntimeError, match="serial"):
        pf.read_archive_csv(archive_csv(rows), "Lastgangprofile_03.2021.csv")


def test_known_problems_are_marked(pf, monkeypatch):
    rows = archive_month(pf, monkeypatch, 2021, 8, [(s, "5") for s in local_end_stamps(2021, 8)])
    bt = pf._frame("by_technology", rows["by_technology"])
    flagged = bt[bt["suspect"].notna()]
    assert set(flagged["technology"]) == {"pv"} and len(flagged) == 7 * 96
    assert set(flagged["suspect"]) == {"pv_level_2021_08"}


def test_a_late_month_without_a_file_fails(pf, monkeypatch):
    serve(pf, monkeypatch, {})
    with pytest.raises(RuntimeError, match="no file for 2024-05"):
        pf.fetch(dt.datetime(2024, 5, 10, tzinfo=UTC), dt.datetime(2024, 5, 11, tzinfo=UTC))


def test_an_empty_window_returns_typed_empty_tables(pf, monkeypatch):
    pytest.importorskip("pyarrow")  # fetch.py declares it; the server's environment doesn't have it
    serve(pf, monkeypatch, {})
    now = dt.datetime.now(UTC)
    out = pf.fetch(now - dt.timedelta(days=1), now + dt.timedelta(days=1))
    assert set(out) == {"by_technology", "pv_by_canton", "capacity_by_technology", "pv_capacity_by_canton"}
    assert all(df.empty for df in out.values())
    assert str(out["capacity_by_technology"]["delivery_month"].dtype) == "date32[day][pyarrow]"
