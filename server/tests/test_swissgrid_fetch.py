"""datasets/swissgrid_*/fetch.py on synthetic files: the parsers of the three layouts, the cut of
the year files by the window, the URL found again after a 404. No network: `requests.get` is
replaced by a stub, the files are written here (the values are made up)."""
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


def answer(name: str, text: str) -> dict:
    return {"name": name, "url": f"https://example.org/{name}", "body": text.encode(),
            "received_at": dt.datetime(2026, 10, 10, 0, 5, tzinfo=UTC)}


class Resp:
    def __init__(self, status: int, content: bytes = b""):
        self.status_code, self.content, self.text = status, content, content.decode(errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# --- swissgrid_tsi --------------------------------------------------------------------------------

TSI = "timestamp_utc,total_system_imbalance\n2026-10-09T23:45:00Z,-16.00\n2026-10-09T23:50:00Z,6.97\n" \
      "2026-10-09T23:55:00Z,101.68\n"


def test_tsi_parse():
    m = load("swissgrid_tsi")
    df = m.parse([answer(m.NAME, TSI)])
    assert list(df.columns) == ["delivery_start", "tsi"]
    assert df["delivery_start"].tolist() == [pd.Timestamp(f"2026-10-09 23:{mm}:00Z") for mm in (45, 50, 55)]
    assert df["tsi"].tolist() == [-16.0, 6.97, 101.68]


def test_tsi_two_equal_answers_received_together_give_each_row_once():
    m = load("swissgrid_tsi")
    assert len(m.parse([answer(m.NAME, TSI), answer(m.NAME, TSI)])) == 3


@pytest.mark.parametrize("text, error", [
    ("time,tsi\n2026-10-09T23:45:00Z,1\n", "columns"),
    ("timestamp_utc,total_system_imbalance\n2026-10-09T23:46:00Z,1\n", "5-minute grid"),
    ("timestamp_utc,total_system_imbalance\n2026-10-09T23:45:00Z,n/a\n", "Unable to parse"),
])
def test_tsi_parse_refuses_a_changed_file(text, error):
    m = load("swissgrid_tsi")
    with pytest.raises(ValueError, match=error):
        m.parse([answer(m.NAME, text)])


def test_tsi_download_finds_a_moved_file(monkeypatch, capsys):
    m = load("swissgrid_tsi")
    page = '<a href="/dam/jcr:new-id/total-system-imbalance.csv">TSI</a>'.encode()
    calls = []

    def get(url, headers, timeout):
        calls.append(url)
        if url == m.SEED:
            return Resp(404)
        if url in m.PAGES:
            return Resp(200, page)
        return Resp(200, TSI.encode())

    monkeypatch.setattr(m.requests, "get", get)
    [a] = list(m.download(None, None))
    assert a["url"] == "https://www.swissgrid.ch/dam/jcr:new-id/total-system-imbalance.csv"
    assert a["body"] == TSI.encode() and a["name"] == "total-system-imbalance.csv"
    assert "update SEED" in capsys.readouterr().out


# --- swissgrid_balance_daily ----------------------------------------------------------------------

HEAD_2026 = ("Date Time [UTC];Abgedeckte Bedarf der aFRR+;Abgedeckte Bedarf der aFRR-;Abgedeckte Bedarf der SA mFRR+;"
             "Abgedeckte Bedarf der SA mFRR-;Abgedeckte Bedarf der DA mFRR+;Abgedeckte Bedarf der DA mFRR-;"
             "NRV+ (Import);NRV- (Export);FRCE+ (Import);FRCE- (Export);Total System Imbalance;AE-Preis\n")
DAILY = HEAD_2026 + ("09.10.2026 00:00;10;-2;0;0;0;0;3;-1;4;-5;-9;23.57\n"
                     "09.10.2026 00:15;;;;;;;;;;;-12.5;\n")  # a placeholder: only TSI


def test_daily_parse():
    m = load("swissgrid_balance_daily")
    df = m.parse([answer(m.NAME, DAILY)])
    assert df["delivery_start"].tolist() == [pd.Timestamp("2026-10-09 00:00Z"), pd.Timestamp("2026-10-09 00:15Z")]
    assert df.loc[0, "price_single"] == 235.7  # ct/kWh x 10
    assert df.loc[0, "afrr_dn"] == -2.0 and df.loc[0, "tsi"] == -9.0
    assert df.loc[1, ["afrr_up", "price_single"]].isna().all() and df.loc[1, "tsi"] == -12.5
    assert list(df.columns) == ["delivery_start"] + list(m.COLUMNS.values())


@pytest.mark.parametrize("text, error", [
    (DAILY.replace("Date Time [UTC]", "Date Time"), "first column"),
    (DAILY.replace(";AE-Preis", ";AE-Preis long"), "columns"),
    (DAILY.replace("23.57", "23.575"), "two decimals"),
    (DAILY.replace("00:15;", "00:10;"), "quarter-hour grid"),
])
def test_daily_parse_refuses_a_changed_file(text, error):
    m = load("swissgrid_balance_daily")
    with pytest.raises(ValueError, match=error):
        m.parse([answer(m.NAME, text)])


# --- swissgrid_balance: the year files --------------------------------------------------------------

HEAD_2025 = ("Date Time;Abgedeckte Bedarf der aFRR+;Abgedeckte Bedarf der aFRR-;NRV+ (Import);NRV- (Export);"
             "Abgedeckte Bedarf der SA mFRR+;Abgedeckte Bedarf der SA mFRR-;Abgedeckte Bedarf der DA mFRR+;"
             "Abgedeckte Bedarf der DA mFRR-;Abgedeckte Bedarf der RR+;Abgedeckte Bedarf der RR-;FRCE+ (Import);"
             "FRCE- (Export);Total System Imbalance (Positiv = long / Negativ = short);AE-Preis long;AE-Preis short;"
             "AE-Preis per 2026\n")
# 2025-10-26: the clocks go back at 03:00 CEST: 02:00 to 02:45 come twice, summer time first.
FALL_BACK = "".join(f"26.10.2025 {h}:{mm};1;0;0;0;0;0;0;0;0;0;0;0;-1;1.5;2.5;2\n"
                    for h in ("01", "02") for mm in ("00", "15", "30", "45")) + \
    "".join(f"26.10.2025 02:{mm};1;0;0;0;0;0;0;0;0;0;0;0;-1;1.5;2.5;2\n" for mm in ("00", "15", "30", "45")) + \
    "26.10.2025 03:00;1;0;0;0;0;0;0;0;0;0;0;0;-1;1.5;2.5;2\n;;;;;;;;;;;;;;;;\n"


def test_year_parse_local_time_with_the_repeated_hour():
    m = load("swissgrid_balance")
    df = m.parse((HEAD_2025 + FALL_BACK).encode(), "control-area-balance-2025.csv")
    got = df["delivery_start"].dt.strftime("%H:%M").tolist()
    # 01:00 CEST = 23:00 UTC ... 02:45 CEST = 00:45 UTC, then 02:00 CET = 01:00 UTC ... 03:00 CET = 02:00 UTC
    assert got == ["23:00", "23:15", "23:30", "23:45", "00:00", "00:15", "00:30", "00:45",
                   "01:00", "01:15", "01:30", "01:45", "02:00"]
    assert df["delivery_start"].is_unique
    assert df.loc[0, ["price_long", "price_short", "price_single_shadow"]].tolist() == [15.0, 25.0, 20.0]
    assert pd.isna(df.loc[0, "price_single"]) and df.loc[0, "rr_up"] == 0.0


def test_year_parse_the_utc_layout_of_2026():
    m = load("swissgrid_balance")
    df = m.parse(DAILY.encode(), "control-area-balance-2026.csv")
    assert df.loc[0, "delivery_start"] == pd.Timestamp("2026-10-09 00:00Z")
    assert df.loc[0, "price_single"] == 235.7 and df[["rr_up", "rr_dn", "price_long"]].isna().all().all()
    assert list(df.columns) == ["delivery_start"] + m.FIELDS


def test_year_parse_refuses_an_unknown_column():
    m = load("swissgrid_balance")
    with pytest.raises(ValueError, match="unknown columns"):
        m.parse(DAILY.replace("AE-Preis", "AE-Preis neu").encode(), "control-area-balance-2026.csv")


def test_year_parse_refuses_a_missing_column():
    """Review of 2026-11-15: a file without AE-Preis gave a null price, stored as a new version of every row."""
    m = load("swissgrid_balance")
    lines = [ln.rsplit(";", 1)[0] for ln in DAILY.splitlines()]
    with pytest.raises(ValueError, match="not a known layout"):
        m.parse(("\n".join(lines) + "\n").encode(), "control-area-balance-2026.csv")
    with pytest.raises(ValueError, match="not a known layout"):  # the RR columns of 2025 in a file in UTC
        m.parse((HEAD_2025.replace("Date Time;", "Date Time [UTC];") + FALL_BACK).encode(), "x.csv")


def test_year_parse_a_file_that_ends_inside_the_repeated_hour():
    """Review of 2026-11-15: 02:30 and 02:45 of summer time, alone, were read as winter time."""
    m = load("swissgrid_balance")
    row = ";1;0;0;0;0;0;0;0;0;0;0;0;-1;1.5;2.5;2\n"
    stamps = [f"01:{mm}" for mm in ("00", "15", "30", "45")] + [f"02:{mm}" for mm in ("00", "15", "30", "45")] \
        + ["02:00", "02:15"]
    df = m.parse((HEAD_2025 + "".join(f"26.10.2025 {s}{row}" for s in stamps)).encode(), "x.csv")
    assert df["delivery_start"].dt.strftime("%H:%M").tolist() == [
        "23:00", "23:15", "23:30", "23:45", "00:00", "00:15", "00:30", "00:45", "01:00", "01:15"]


def test_year_parse_refuses_local_rows_out_of_order():
    m = load("swissgrid_balance")
    row = ";1;0;0;0;0;0;0;0;0;0;0;0;-1;1.5;2.5;2\n"
    text = HEAD_2025 + "".join(f"01.06.2025 {s}{row}" for s in ("10:00", "09:45", "10:15"))
    with pytest.raises(ValueError, match="time order"):
        m.parse(text.encode(), "x.csv")


def test_the_window_chooses_the_local_years():
    m = load("swissgrid_balance")
    t = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    assert m.years(t("2026-11-15"), t("2026-11-16")) == [2026]
    assert m.years(t("2024-09-06"), t("2026-11-15")) == [2024, 2025, 2026]  # P800D before 2026-11-15
    assert m.years(t("2020-01-01"), t("2023-12-31 22:00")) == []  # before the first file: nothing
    assert m.years(t("2020-01-01"), t("2024-01-01")) == [2024]  # 00:00 UTC is 01:00 local, in 2024
    assert m.years(t("2025-12-31 22:30"), t("2025-12-31 23:30")) == [2025, 2026]  # 23:00 UTC is local midnight


def test_the_file_of_a_new_year_may_be_missing_for_a_week(monkeypatch):
    m = load("swissgrid_balance")
    monkeypatch.setattr(m.requests, "get", lambda url, headers, timeout: Resp(200, b"<html></html>"))
    jan3 = dt.datetime(2027, 1, 3, tzinfo=UTC)
    assert m.get_year(2027, jan3) is None
    with pytest.raises(RuntimeError, match="no page"):
        m.get_year(2027, dt.datetime(2027, 1, 20, tzinfo=UTC))
