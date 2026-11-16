"""The fetch.py of the five ENTSO-E datasets of WP5.1 on synthetic answers: the parsers (curve
type A03 per series, units, codes), the signs, the choice between an intermediate and a final
document, the split of a refused or cut request, the years to come of the installed capacity.
No network: each module's `_get` is replaced, the answers are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
UTC = dt.timezone.utc
NS = 'xmlns="urn:iec62325.351:tc57wg16:451-6:balancingdocument:4:4"'


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_fetch", DATASETS / name / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def period(start: str, end: str, res: str, points: str) -> str:
    return (f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
            f"<resolution>{res}</resolution>{points}</Period>")


def doc(series: str, status: str | None = None) -> bytes:
    st = f"<docStatus><value>{status}</value></docStatus>" if status else ""
    return f"<Balancing_MarketDocument {NS}><type>A85</type>{st}{series}</Balancing_MarketDocument>".encode()


def price_series(cat: str, start: str, end: str, pts: list[tuple[int, float]], curve: str = "A03",
                 res: str = "PT15M", unit: str = "MWH") -> str:
    p = "".join(f"<Point><position>{i}</position><imbalance_Price.amount>{v}</imbalance_Price.amount>"
                f"<imbalance_Price.category>{cat}</imbalance_Price.category></Point>" for i, v in pts)
    return (f"<TimeSeries><businessType>A19</businessType><currency_Unit.name>EUR</currency_Unit.name>"
            f"<price_Measure_Unit.name>{unit}</price_Measure_Unit.name><curveType>{curve}</curveType>"
            f"{period(start, end, res, p)}</TimeSeries>")


def volume_series(direction: str, start: str, end: str, pts: list[tuple], business: str = "A19",
                  unit: str = "MWH", res: str = "PT15M") -> str:
    p = "".join(f"<Point><position>{pt[0]}</position><{'quantity'}>{pt[1]}</quantity>"
                + (f"<secondaryQuantity>{pt[2]}</secondaryQuantity>" if len(pt) > 2 else "") + "</Point>" for pt in pts)
    return (f"<TimeSeries><businessType>{business}</businessType><flowDirection.direction>{direction}"
            f"</flowDirection.direction><quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name>"
            f"<curveType>A03</curveType>{period(start, end, res, p)}</TimeSeries>")


# --- imbalance prices ------------------------------------------------------------------------

@pytest.fixture
def ip():
    return load("entsoe_imbalance_prices")


def test_prices_a03_is_expanded_per_category_and_put_side_by_side(ip):
    d = doc(price_series("A04", "2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 10.0), (3, 30.0)])
            + price_series("A05", "2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 11.0), (2, 21.0)]), "A02")
    df = ip.wide(ip._frame([d]).assign(area="CH"))
    assert df["price_long"].tolist() == [10.0, 10.0, 30.0, 30.0]
    assert df["price_short"].tolist() == [11.0, 21.0, 21.0, 21.0]
    assert df["delivery_start"].iloc[-1] == pd.Timestamp("2026-03-01T00:45Z")


def test_prices_without_a_status_are_kept_and_a_final_value_wins(ip):
    none = doc(price_series("A04", "2016-03-01T00:00Z", "2016-03-01T00:15Z", [(1, 5.0)]))
    inter = doc(price_series("A04", "2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 1.0)]), "A01")
    final = doc(price_series("A04", "2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 2.0)]), "A02")
    df = ip.wide(ip._frame([none, inter, final]).assign(area="AT"))
    assert df["price_long"].tolist() == [5.0, 2.0]
    assert df["price_short"].isna().all()


def test_prices_two_values_of_one_status_or_a_wrong_unit_are_refused(ip):
    a = doc(price_series("A04", "2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 1.0)]), "A01")
    b = doc(price_series("A04", "2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 2.0)]), "A01")
    with pytest.raises(RuntimeError, match="two prices of the same status"):
        ip.wide(ip._frame([a, b]).assign(area="AT"))
    with pytest.raises(RuntimeError, match="expected EUR/MWH"):
        ip.parse(doc(price_series("A04", "2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 1.0)], unit="KWH")))


def test_prices_fetch_cuts_to_the_window_and_splits_a_refused_request(ip, monkeypatch):
    calls = []

    def fake_get(session, token, label, params, s, e):
        calls.append((params["controlArea_Domain"], s, e))
        if params["controlArea_Domain"] != ip.AREAS["CH"]:
            return None
        if e - s > dt.timedelta(days=1):
            raise ip.TooLarge("The amount of requested data exceeds allowed limit")
        n = int((e - s) / dt.timedelta(minutes=15))
        start = s.strftime("%Y-%m-%dT%H:%MZ")
        end = e.strftime("%Y-%m-%dT%H:%MZ")
        return [doc(price_series("A04", start, end, [(1, 7.0)]) + price_series("A05", start, end, [(1, 8.0)]), "A02")]

    monkeypatch.setenv("ENTSO_TOKEN", "x")
    monkeypatch.setattr(ip, "_get", fake_get)
    df = ip.fetch(dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 3, 3, 12, tzinfo=UTC))
    assert set(df["area"]) == {"CH"}
    assert len(df) == 2.5 * 96 and df["delivery_start"].max() == pd.Timestamp("2026-03-03T11:45Z")
    assert (df["price_long"] == 7.0).all() and (df["price_short"] == 8.0).all()
    ch = [c for c in calls if c[0] == ip.AREAS["CH"]]
    # 2.5 days refused --> two halves of 1.25 days refused --> four quarters of 0.625 days answered
    assert len(ch) == 7 and sum(e - s <= dt.timedelta(days=1) for _, s, e in ch) == 4


# --- activated balancing prices --------------------------------------------------------------

def activated_series(business: str, psr: str, direction: str, pts: list[tuple[int, float, str]],
                     product: str | None = None) -> str:
    prod = (f"<standard_MarketProduct.marketProductType>{product}</standard_MarketProduct.marketProductType>"
            if product else "")
    p = "".join(f"<Point><position>{i}</position><activation_Price.amount>{v}</activation_Price.amount>"
                f"<imbalance_Price.category>{c}</imbalance_Price.category></Point>" for i, v, c in pts)
    return (f"<TimeSeries><businessType>{business}</businessType>{prod}<mktPSRType.psrType>{psr}</mktPSRType.psrType>"
            f"<flowDirection.direction>{direction}</flowDirection.direction><currency_Unit.name>EUR</currency_Unit.name>"
            f"<price_Measure_Unit.name>MWH</price_Measure_Unit.name><curveType>A03</curveType>"
            f"{period('2026-03-01T00:00Z', '2026-03-01T00:45Z', 'PT15M', p)}</TimeSeries>")


def test_activated_prices_codes_become_names_and_a03_is_expanded():
    ap = load("entsoe_activated_balancing_prices")
    d = doc(activated_series("A96", "A04", "A01", [(1, 50.0, "A06"), (3, 70.0, "A06")])
            + activated_series("A98", "A03", "A02", [(1, -5.0, "A08")], product="A01"))
    df = ap._frame([d])
    afrr = df[df["reserve"] == "aFRR"]
    assert afrr["price"].tolist() == [50.0, 50.0, 70.0]
    assert set(afrr["direction"]) == {"up"} and set(afrr["resource"]) == {"generation"}
    assert afrr["product"].isna().all()
    rr = df[df["reserve"] == "RR"]
    assert rr[["resource", "direction", "product", "category"]].iloc[0].tolist() == ["mixed", "down", "A01", "A08"]
    assert len(rr) == 3
    with pytest.raises(RuntimeError, match="business type 'A99'"):
        ap.parse(doc(activated_series("A99", "A04", "A01", [(1, 1.0, "A06")])))


# --- balancing state -------------------------------------------------------------------------

def test_balancing_state_sign_comes_from_the_direction():
    bs = load("entsoe_balancing_state")
    d = doc(volume_series("A01", "2024-01-01T00:00Z", "2024-01-01T00:02Z", [(1, 20.0)], business="B33",
                          unit="MAW", res="PT1M")
            + volume_series("A02", "2024-01-01T00:02Z", "2024-01-01T00:03Z", [(1, 30.0)], business="B33",
                            unit="MAW", res="PT1M")
            + volume_series("A03", "2024-01-01T00:03Z", "2024-01-01T00:04Z", [(1, 0.0)], business="B33",
                            unit="MAW", res="PT1M"))
    df = bs._frame([d]).sort_values("delivery_start")
    assert df["control_error"].tolist() == [-20.0, -20.0, 30.0, 0.0]
    assert df["direction"].tolist() == ["A01", "A01", "A02", "A03"]
    with pytest.raises(RuntimeError, match="negative quantity"):
        bs.parse(doc(volume_series("A01", "2024-01-01T00:00Z", "2024-01-01T00:01Z", [(1, -1.0)], business="B33",
                                   unit="MAW", res="PT1M")))


# --- imbalance volumes of the neighbours -----------------------------------------------------

def test_volumes_austria_sign_before_december_2024_unless_a_second_value_is_served():
    iv = load("entsoe_imbalance_volume_neighbours")
    old = "2024-11-30T21:00Z", "2024-11-30T21:30Z"     # before 2024-12-01 00:00 local
    new = "2024-11-30T23:00Z", "2024-11-30T23:15Z"     # from 2024-12-01 00:00 local
    at = iv._frame([doc(volume_series("A01", *old, [(1, 10.0), (2, 12.0, 3.0)])),
                    doc(volume_series("A01", *new, [(1, 5.0)]))]).assign(area="AT")
    assert iv.signed(at).tolist() == [-10.0, 12.0, 5.0]
    fr = iv._frame([doc(volume_series("A01", *old, [(1, 10.0)]))]).assign(area="FR")
    assert iv.signed(fr).tolist() == [10.0, 10.0]


def test_volumes_one_row_per_key_prefers_final_and_keeps_documents_without_status():
    iv = load("entsoe_imbalance_volume_neighbours")
    a = doc(volume_series("A01", "2025-01-01T00:00Z", "2025-01-01T00:15Z", [(1, 1.0)]), "A01")
    b = doc(volume_series("A02", "2025-01-01T00:00Z", "2025-01-01T00:15Z", [(1, 2.0)]), "A02")
    c = doc(volume_series("A01", "2015-01-01T00:00Z", "2015-01-01T00:15Z", [(1, 4.0)]))
    df = iv.one_per_key(iv._frame([a, b, c]).assign(area="FR")).sort_values("delivery_start")
    assert df["volume"].tolist() == [4.0, 2.0]
    with pytest.raises(RuntimeError, match="same status"):
        iv.one_per_key(iv._frame([a, doc(volume_series("A02", "2025-01-01T00:00Z", "2025-01-01T00:15Z",
                                                         [(1, 9.0)]), "A01")]).assign(area="FR"))


# --- installed capacity ----------------------------------------------------------------------

def capacity_answer(year: int, values: dict[str, float]) -> bytes:
    start = dt.datetime(year - 1, 12, 31, 23, tzinfo=UTC).strftime("%Y-%m-%dT%H:%MZ")
    end = dt.datetime(year, 12, 31, 23, tzinfo=UTC).strftime("%Y-%m-%dT%H:%MZ")
    ts = "".join(f"<TimeSeries><businessType>A37</businessType><quantity_Measure_Unit.name>MAW"
                 f"</quantity_Measure_Unit.name><curveType>A03</curveType><MktPSRType><psrType>{k}</psrType>"
                 f"</MktPSRType>{period(start, end, 'P1Y', f'<Point><position>1</position><quantity>{v}</quantity></Point>')}"
                 f"</TimeSeries>" for k, v in values.items())
    return f'<GL_MarketDocument xmlns="urn:x">{ts}</GL_MarketDocument>'.encode()


def test_capacity_asks_each_year_alone_and_never_a_year_to_come(monkeypatch):
    ic = load("entsoe_installed_capacity")
    asked = []

    def fake_get(session, token, label, params, s, e):
        year = (s + dt.timedelta(hours=2)).year
        asked.append(year)
        return capacity_answer(year, {"B14": 3000.0 + year})

    monkeypatch.setenv("ENTSO_TOKEN", "x")
    monkeypatch.setattr(ic, "_get", fake_get)
    this_year = dt.datetime.now(UTC).year
    df = ic.fetch(dt.datetime(this_year - 1, 6, 1, tzinfo=UTC), dt.datetime(this_year + 3, 1, 1, tzinfo=UTC))
    assert asked == [this_year - 1, this_year]
    assert df["delivery_year"].tolist() == [dt.date(this_year - 1, 1, 1), dt.date(this_year, 1, 1)]
    assert df["capacity"].tolist() == [3000.0 + this_year - 1, 3000.0 + this_year]


def test_capacity_refuses_a_period_that_is_not_the_year_asked():
    ic = load("entsoe_installed_capacity")
    with pytest.raises(RuntimeError, match="expected 1 January 2026"):
        ic.parse(capacity_answer(2025, {"B10": 1.0}), 2026)
