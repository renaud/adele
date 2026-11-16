"""The fetch.py of the four datasets of WP5.2 on synthetic answers: entsoe_generation (A75),
entsoe_physical_flows (A11), entsoe_scheduled_exchanges (A09), entsoe_imbalance_volume (A86).
The parsers, the refusals, the two directions on one row, the sign of the imbalance, the split of
a cut answer, and that the token never appears in an error text.
No network: entsoe-py is replaced by a stub, the answers are written here."""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import sys
import types
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import requests

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
UTC = dt.timezone.utc
CH, DE, IT = "10YCH-SWISSGRIDZ", "10Y1001A1001A83F", "10YIT-GRTN-----B"


def _load(monkeypatch, name: str):
    entsoe = types.ModuleType("entsoe")
    exceptions = types.ModuleType("entsoe.exceptions")

    class NoMatchingDataError(Exception):
        pass

    class PaginationError(Exception):
        pass

    exceptions.NoMatchingDataError = NoMatchingDataError
    exceptions.PaginationError = PaginationError
    entsoe.EntsoeRawClient = object
    entsoe.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "entsoe", entsoe)
    monkeypatch.setitem(sys.modules, "entsoe.exceptions", exceptions)
    spec = importlib.util.spec_from_file_location(f"{name}_fetch", DATASETS / name / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "EntsoeRawClient", lambda **kw: None)
    monkeypatch.setenv("ENTSO_TOKEN", "SECRET-TOKEN")
    return mod


@pytest.fixture
def gen(monkeypatch):
    return _load(monkeypatch, "entsoe_generation")


@pytest.fixture
def flows(monkeypatch):
    return _load(monkeypatch, "entsoe_physical_flows")


@pytest.fixture
def sched(monkeypatch):
    return _load(monkeypatch, "entsoe_scheduled_exchanges")


@pytest.fixture
def imb(monkeypatch):
    return _load(monkeypatch, "entsoe_imbalance_volume")


def period(start: str, end: str, points: list[tuple], res: str = "PT60M") -> str:
    pts = ""
    for p in points:
        extra = f"<secondaryQuantity>{p[2]}</secondaryQuantity>" if len(p) > 2 else ""
        pts += f"<Point><position>{p[0]}</position><quantity>{p[1]}</quantity>{extra}</Point>"
    return (f"<Period><timeInterval><start>{start}</start><end>{end}</end></timeInterval>"
            f"<resolution>{res}</resolution>{pts}</Period>")


def series(fields: dict, *periods: str, unit: str = "MAW", curve: str = "A03") -> str:
    inner = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())
    return (f"<TimeSeries>{inner}<quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name>"
            f"<curveType>{curve}</curveType>{''.join(periods)}</TimeSeries>")


def gl_doc(*ts: str) -> str:
    return f'<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">{"".join(ts)}</GL_MarketDocument>'


def pub_doc(*ts: str) -> str:
    return f'<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">{"".join(ts)}</Publication_MarketDocument>'


def gen_ts(psr: str, *periods: str, zone: str = CH, extra: dict | None = None, **kw) -> str:
    fields = {"businessType": "A01", "inBiddingZone_Domain.mRID": zone, **(extra or {})}
    inner = "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())
    unit, curve = kw.get("unit", "MAW"), kw.get("curve", "A03")
    return (f"<TimeSeries>{inner}<quantity_Measure_Unit.name>{unit}</quantity_Measure_Unit.name>"
            f"<curveType>{curve}</curveType><MktPSRType><psrType>{psr}</psrType></MktPSRType>{''.join(periods)}</TimeSeries>")


def border_ts(out_eic: str, in_eic: str, *periods: str, contract: str | None = None) -> str:
    fields = {"businessType": "A66", "in_Domain.mRID": in_eic, "out_Domain.mRID": out_eic}
    if contract:
        fields["contract_MarketAgreement.type"] = contract
    return series(fields, *periods)


def imb_doc(*ts: str, status: str | None = "A02", area: str = CH) -> bytes:
    st = f"<docStatus><value>{status}</value></docStatus>" if status else ""
    return (f'<Balancing_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:balancingdocument:4:4">{st}'
            f"<controlArea_Domain.mRID>{area}</controlArea_Domain.mRID>{''.join(ts)}</Balancing_MarketDocument>").encode()


def imb_ts(direction: str, *periods: str) -> str:
    return series({"businessType": "A19", "flowDirection.direction": direction}, *periods, unit="MWH")


def zipped(*docs: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, d in enumerate(docs):
            z.writestr(f"doc{i}.xml", d)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------- generation
def test_generation_types_and_a03(gen):
    xml = gl_doc(gen_ts("B16", period("2026-03-01T00:00Z", "2026-03-01T04:00Z", [(1, 0.0), (3, 50.5)])),
                 gen_ts("B14", period("2026-03-01T00:00Z", "2026-03-01T02:00Z", [(1, 2900.0)])))
    df = gen.parse(xml)
    solar = df[df["production_type"] == "solar"]
    assert solar["generation"].tolist() == [0.0, 0.0, 50.5, 50.5]
    assert df[df["production_type"] == "nuclear"]["generation"].tolist() == [2900.0, 2900.0]
    assert (df["resolution"] == pd.Timedelta(hours=1)).all()


@pytest.mark.parametrize("ts, msg", [
    (lambda: gen_ts("B20", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)])), "production type"),
    (lambda: gen_ts("B16", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)]), zone=DE), "bidding zone"),
    (lambda: gen_ts("B10", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)]),
                    extra={"outBiddingZone_Domain.mRID": CH}), "consumption"),
    (lambda: gen_ts("B16", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)]), unit="MWH"), "unit"),
    (lambda: gen_ts("B16", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)], res="P1D")), "resolution"),
])
def test_generation_refuses_what_it_does_not_know(gen, ts, msg):
    with pytest.raises(RuntimeError, match=msg):
        gen.parse(gl_doc(ts()))


def test_generation_fetch_whole_hours_and_window(gen, monkeypatch):
    asked = []

    def fake(client, zone, s, e):
        asked.append((s, e))
        return gen.parse(gl_doc(gen_ts("B16", period("2026-03-01T00:00Z", "2026-03-01T03:00Z",
                                                        [(1, 1.0), (2, 2.0), (3, 3.0)]), curve="A01")))

    monkeypatch.setattr(gen, "_request", fake)
    out = gen.fetch(dt.datetime(2026, 3, 1, 0, 30, tzinfo=UTC), dt.datetime(2026, 3, 1, 2, 10, tzinfo=UTC))
    assert asked == [(dt.datetime(2026, 3, 1, 0, tzinfo=UTC), dt.datetime(2026, 3, 1, 3, tzinfo=UTC))]
    assert out["delivery_start"].dt.strftime("%H:%M").tolist() == ["01:00", "02:00"]  # 00:00 is before the start
    assert list(out.columns) == ["bidding_zone", "production_type", "delivery_start", "resolution", "generation"]
    assert out["bidding_zone"].unique().tolist() == ["CH"]


def test_a_cut_answer_is_split(gen, monkeypatch):
    """A one-year request whose answer ends after 30 days is asked again in halves."""
    asked = []

    def fake(client, zone, s, e):
        asked.append((s, e))
        stop = min(e, s + dt.timedelta(days=30))
        n = int((stop - s) / dt.timedelta(hours=1))
        return pd.DataFrame({"production_type": "solar", "delivery_start": pd.date_range(s, periods=n, freq="h"),
                             "resolution": pd.Timedelta(hours=1), "generation": 1.0})

    monkeypatch.setattr(gen, "_request", fake)
    start, end = dt.datetime(2025, 1, 1, tzinfo=UTC), dt.datetime(2025, 3, 2, tzinfo=UTC)
    out = gen._one(None, "CH", start, end)
    assert len(asked) > 1
    assert out["delivery_start"].max() == pd.Timestamp("2025-03-01T23:00Z")
    assert not out["delivery_start"].duplicated().any()


def test_the_token_is_not_in_the_error_text(gen):
    class Client:
        def query_generation(self, *a, **kw):
            r = requests.Response()
            r.status_code = 400
            raise requests.HTTPError("400 Client Error: Bad Request for url: "
                                     "https://web-api.tp.entsoe.eu/api?securityToken=SECRET-TOKEN&documentType=A75",
                                     response=r)

    with pytest.raises(RuntimeError) as err:
        gen._request(Client(), "CH", dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert "SECRET-TOKEN" not in str(err.value) and "***" in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_a_transient_error_is_retried(gen, monkeypatch):
    monkeypatch.setattr(gen.time, "sleep", lambda s: None)
    calls = []

    class Client:
        def query_generation(self, *a, **kw):
            calls.append(1)
            if len(calls) < 3:
                raise requests.ConnectionError("reset")
            return gl_doc(gen_ts("B16", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 5.0)])))

    df = gen._request(Client(), "CH", dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 3, 1, 1, tzinfo=UTC))
    assert len(calls) == 3 and df["generation"].tolist() == [5.0]


# ------------------------------------------------------------------------------------------- flows
def test_flows_two_directions_on_one_row(flows, monkeypatch):
    answers = {
        ("CH", "DE"): pub_doc(border_ts(CH, DE, period("2026-03-01T00:00Z", "2026-03-01T00:30Z", [(1, 10.0), (2, 0.0)],
                                                       res="PT15M"))),
        ("DE", "CH"): pub_doc(border_ts(DE, CH, period("2026-03-01T00:00Z", "2026-03-01T00:30Z", [(1, 900.0)],
                                                       res="PT15M"))),
        ("CH", "IT"): pub_doc(border_ts(CH, IT, period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 5.0)]))),
    }
    asked = []

    def fake(client, frm, to, s, e):
        asked.append((frm, to))
        xml = answers.get((frm, to))
        return None if xml is None else flows.parse(xml, frm, to)

    monkeypatch.setattr(flows, "_request", fake)
    out = flows.fetch(dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 3, 1, 1, tzinfo=UTC))
    assert sorted(set(asked)) == sorted({("CH", nb) for nb in ("DE", "FR", "IT", "AT")} |
                                        {(nb, "CH") for nb in ("DE", "FR", "IT", "AT")})  # DE_LU never
    de = out[out["border"] == "DE"]
    assert de["from_ch"].tolist() == [10.0, 0.0] and de["to_ch"].tolist() == [900.0, 900.0]
    it = out[out["border"] == "IT"]
    assert it["from_ch"].tolist() == [5.0] and it["to_ch"].isna().all()  # no answer for IT --> CH
    assert list(out.columns) == ["border", "delivery_start", "resolution", "from_ch", "to_ch"]


@pytest.mark.parametrize("module", ["flows", "sched"])
def test_an_hourly_direction_is_repeated_where_the_other_has_quarter_hours(module, request):
    """IT day-ahead, 2025: in one hour CH --> IT is hourly and IT --> CH quarter-hourly. The hourly
    value holds for the four quarter-hours (same energy, same hourly mean); the next hour, hourly on
    both sides, stays one row."""
    m = request.getfixturevalue(module)
    ct = {"contract": "A01"} if module == "sched" else {}
    args = (("A01",) if module == "sched" else ())
    a = m.parse(pub_doc(border_ts(CH, IT, period("2025-01-11T00:00Z", "2025-01-11T02:00Z", [(1, 100.0), (2, 50.0)]),
                                  **ct)), "CH", "IT", *args)
    b = m.parse(pub_doc(border_ts(IT, CH,
                                  period("2025-01-11T00:00Z", "2025-01-11T01:00Z", [(1, 1.0), (2, 2.0), (3, 3.0), (4, 4.0)],
                                         res="PT15M"),
                                  period("2025-01-11T01:00Z", "2025-01-11T02:00Z", [(1, 7.0)]), **ct)), "IT", "CH", *args)
    w = m.wide({"from_ch": [a], "to_ch": [b]}, "IT")
    assert w["delivery_start"].dt.strftime("%H:%M").tolist() == ["00:00", "00:15", "00:30", "00:45", "01:00"]
    assert w["from_ch"].tolist() == [100.0, 100.0, 100.0, 100.0, 50.0]
    assert w["to_ch"].tolist() == [1.0, 2.0, 3.0, 4.0, 7.0]
    assert w["resolution"].tolist() == [pd.Timedelta(minutes=15)] * 4 + [pd.Timedelta(hours=1)]
    energy = (w["from_ch"] * w["resolution"].dt.total_seconds() / 3600).sum()
    assert energy == 150.0  # 100 MW for one hour + 50 MW for one hour


def test_flows_refuse_an_interval_served_twice_with_two_values(flows):
    a = flows.parse(pub_doc(border_ts(CH, DE, period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)]))), "CH", "DE")
    a2 = a.assign(flow=9.0)  # the same hour in a second answer, with another value
    with pytest.raises(RuntimeError, match="share a delivery_start"):
        flows.wide({"from_ch": [a, a2], "to_ch": []}, "DE")


def test_flows_refuse_another_border(flows):
    xml = pub_doc(border_ts(CH, "10Y1001A1001A82H", period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)])))
    with pytest.raises(RuntimeError, match="domains"):
        flows.parse(xml, "CH", "DE")


# ------------------------------------------------------------------------------------------- schedules
def test_schedules_two_tables_and_the_contract_is_checked(sched, monkeypatch):
    def fake(client, contract, frm, to, s, e):
        if (frm, to) != ("CH", "IT"):
            return None
        q = 100.0 if contract == "A01" else 150.0
        return sched.parse(pub_doc(border_ts(CH, IT, period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, q)]),
                                             contract=contract)), frm, to, contract)

    monkeypatch.setattr(sched, "_request", fake)
    out = sched.fetch(dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 3, 1, 1, tzinfo=UTC))
    assert set(out) == {"day_ahead", "total"}
    assert out["day_ahead"]["from_ch"].tolist() == [100.0] and out["total"]["from_ch"].tolist() == [150.0]
    with pytest.raises(RuntimeError, match="contract type"):
        sched.parse(pub_doc(border_ts(CH, IT, period("2026-03-01T00:00Z", "2026-03-01T01:00Z", [(1, 1.0)]),
                                      contract="A05")), "CH", "IT", "A01")


# ------------------------------------------------------------------------------------------- imbalance
def test_imbalance_sign_status_and_secondary(imb):
    final = imb_doc(imb_ts("A01", period("2026-03-01T00:00Z", "2026-03-01T00:30Z", [(1, 25.0, 3.5)], res="PT15M")),
                    imb_ts("A02", period("2026-03-01T00:30Z", "2026-03-01T00:45Z", [(1, 10.0, -1.0)], res="PT15M")),
                    status="A02")
    interm = imb_doc(imb_ts("A03", period("2015-04-01T00:00Z", "2015-04-01T00:15Z", [(1, 0.0)], res="PT15M")),
                     status="A01")
    none = imb_doc(imb_ts("A02", period("2015-03-25T23:00Z", "2015-03-25T23:15Z", [(1, 4.0)], res="PT15M")),
                   status=None)
    df = imb.parse(zipped(final, interm, none)).sort_values("delivery_start", ignore_index=True)
    assert df["imbalance"].tolist() == [-4.0, 0.0, 25.0, 25.0, -10.0]  # A03 holds the first point for 00:15
    assert df["mv_minus_sv"].tolist()[2:] == [3.5, 3.5, -1.0]
    assert df["mv_minus_sv"].isna().tolist()[:2] == [True, True]
    assert df["status"].isna().tolist() == [True, False, False, False, False]
    assert df["status"].tolist()[1:] == ["intermediate", "final", "final", "final"]
    assert str(df["imbalance"].iloc[1]) == "0.0"  # not -0.0


def test_imbalance_refuses_a_balanced_volume_and_another_area(imb):
    with pytest.raises(RuntimeError, match="A03"):
        imb.parse(imb_doc(imb_ts("A03", period("2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 2.0)], res="PT15M"))))
    with pytest.raises(RuntimeError, match="control area"):
        imb.parse(imb_doc(imb_ts("A01", period("2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 2.0)], res="PT15M")),
                          area=DE))


def test_imbalance_refuses_a_quarter_hour_served_twice(imb, monkeypatch):
    both = imb_doc(imb_ts("A01", period("2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 2.0)], res="PT15M")),
                   imb_ts("A02", period("2026-03-01T00:00Z", "2026-03-01T00:15Z", [(1, 3.0)], res="PT15M")))
    monkeypatch.setattr(imb, "_request", lambda client, area, s, e: imb.parse(both))
    with pytest.raises(RuntimeError, match="share a quarter-hour"):
        imb.fetch(dt.datetime(2026, 3, 1, tzinfo=UTC), dt.datetime(2026, 3, 1, 1, tzinfo=UTC))


def test_imbalance_fetch_writes_none_for_a_missing_status(imb, monkeypatch):
    """pandas 3 turns None into NaN in a column of strings; the table must get a null, not a float."""
    doc = imb_doc(imb_ts("A02", period("2015-03-25T23:00Z", "2015-03-25T23:30Z", [(1, 4.0)], res="PT15M")), status=None)
    monkeypatch.setattr(imb, "_request", lambda client, area, s, e: imb.parse(doc))
    out = imb.fetch(dt.datetime(2015, 3, 25, 23, tzinfo=UTC), dt.datetime(2015, 3, 26, tzinfo=UTC))
    assert out["status"].tolist() == [None, None]
