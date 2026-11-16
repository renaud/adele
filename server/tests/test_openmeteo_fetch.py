"""The fetch.py files of WP5.10 (openmeteo_*, ecmwf_ifs_ens) on synthetic answers: the stamps
(radiation moved to the start of the hour), the units, the keys of the answers, the requests per
window, the pacing, the runs that are not whole yet. No network: `get` or the store is replaced."""
from __future__ import annotations

import datetime as dt
import importlib.util
import re
from pathlib import Path

import pandas as pd
import pytest

DATASETS = Path(__file__).resolve().parents[2] / "datasets"
OPENMETEO = ["openmeteo_previous_runs", "openmeteo_single_runs", "openmeteo_era5", "openmeteo_cams",
             "openmeteo_stations"]
UTC = dt.timezone.utc


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_fetch", DATASETS / name / "fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def hours(start: str, n: int) -> list[str]:
    t0 = dt.datetime.fromisoformat(start)
    return [(t0 + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n)]


def answer(times: list[str], series: dict[str, list], units: dict[str, str], location_id: int | None = None) -> dict:
    a = {"latitude": 46.75, "longitude": 7.0, "elevation": 489.0, "utc_offset_seconds": 0, "timezone": "GMT",
         "hourly_units": {"time": "iso8601", **units}, "hourly": {"time": times, **series}}
    if location_id is not None:
        a["location_id"] = location_id
    return a


# --- shared ---------------------------------------------------------------------------------------

def client_block(name: str) -> str:
    s = (DATASETS / name / "fetch.py").read_text()
    return s[s.index("# --- the Open-Meteo client"):s.index("# --- this dataset")]


def test_the_client_is_the_same_in_every_openmeteo_dataset():
    blocks = {name: client_block(name) for name in OPENMETEO}
    assert len(set(blocks.values())) == 1, [n for n in OPENMETEO if blocks[n] != blocks[OPENMETEO[0]]]


def test_the_points_are_the_same_in_every_dataset():
    files = {name: (DATASETS / name / "stations.csv").read_text() for name in OPENMETEO + ["ecmwf_ifs_ens"]}
    assert len(set(files.values())) == 1
    rows = files["openmeteo_stations"].strip().splitlines()
    assert rows[0] == "station,region,lat,lon,height" and len(rows) == 80


def test_weight_follows_the_pricing_rule():
    pr = load("openmeteo_previous_runs")
    assert pr.weight(5, 3, 1) == 1.0  # under 10 series and 14 days: one call
    assert pr.weight(15, 14, 1) == 1.5  # the example of the pricing page
    assert pr.weight(10, 28, 1) == 2.0
    assert pr.weight(48, 9, 40) == pytest.approx(192.0)


def test_answers_are_paired_with_points_by_location_id():
    pr = load("openmeteo_previous_runs")
    chunk = [{"station": "PAY"}, {"station": "BER"}]
    a0, a1 = answer([], {}, {}), answer([], {}, {}, location_id=1)
    assert [p["station"] for p, _ in pr.answers_by_point([a0, a1], chunk)] == ["PAY", "BER"]
    with pytest.raises(RuntimeError, match="location_id"):
        pr.answers_by_point([a1, a0], chunk)
    with pytest.raises(RuntimeError, match="2 points"):
        pr.answers_by_point([a0], chunk)


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_a_429_of_the_minute_waits_and_one_of_the_day_fails(monkeypatch):
    pr = load("openmeteo_previous_runs")
    slept = []
    monkeypatch.setattr(pr.time, "sleep", slept.append)
    replies = [FakeResponse(429, {"error": True, "reason": "Minutely API request limit exceeded. Please try again "
                                                            "in one minute."}),
               FakeResponse(200, {"hourly": {}})]
    monkeypatch.setattr(pr._SESSION, "get", lambda *a, **k: replies.pop(0))
    assert pr.get("u", {}, 1.0) == [{"hourly": {}}]
    assert slept == [65]
    monkeypatch.setattr(pr._SESSION, "get", lambda *a, **k: FakeResponse(
        429, {"error": True, "reason": "Daily API request limit exceeded. Please try again tomorrow."}))
    with pytest.raises(RuntimeError, match="Daily"):
        pr.get("u", {}, 1.0)
    monkeypatch.setattr(pr._SESSION, "get", lambda *a, **k: FakeResponse(400, {"error": True, "reason": "no run"}))
    with pytest.raises(pr.SourceError, match="no run"):
        pr.get("u", {}, 1.0)


@pytest.fixture(autouse=True)
def own_ledger(tmp_path, monkeypatch):
    """Every test writes its calls in its own ledger, never in ~/.local/state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def fake_clock(monkeypatch, *mods, start: float = 1_800_000_000.0) -> list[float]:
    clock = [start]

    def sleep(s):
        clock[0] += s

    for m in mods:
        monkeypatch.setattr(m.time, "time", lambda: clock[0])
        monkeypatch.setattr(m.time, "sleep", sleep)
    return clock


def test_the_pace_waits_when_the_minute_is_full(monkeypatch):
    pr = load("openmeteo_previous_runs")
    clock = fake_clock(monkeypatch, pr)
    pr._pace(300)
    pr._pace(200)
    assert clock[0] == 1_800_000_000.0  # 500 calls in the minute: no wait
    pr._pace(100)
    assert clock[0] >= 1_800_000_060.0  # the next one waits until the first calls leave the minute
    assert [ln.split("\t")[1:] for ln in pr.ledger().read_text().splitlines()] == [
        ["300", "openmeteo_previous_runs"], ["200", "openmeteo_previous_runs"], ["100", "openmeteo_previous_runs"]]


def test_the_datasets_share_one_budget(monkeypatch):
    pr, era5 = load("openmeteo_previous_runs"), load("openmeteo_era5")
    clock = fake_clock(monkeypatch, pr, era5)
    pr._pace(400)
    era5._pace(100)
    assert clock[0] == 1_800_000_000.0
    era5._pace(50)  # the calls of the other dataset count: the minute is full
    assert clock[0] >= 1_800_000_060.0


def test_a_day_without_room_fails_with_the_time_from_which_it_has_room(monkeypatch):
    pr = load("openmeteo_previous_runs")
    clock = fake_clock(monkeypatch, pr)
    t0 = clock[0]
    pr.ledger().parent.mkdir(parents=True)
    # 7,400 calls 5 hours ago, as 37 requests of 200 calls, one per minute
    pr.ledger().write_text("".join(f"{t0 - 5 * 3600 + 60 * i:.0f}\t200\tx\n" for i in range(37)))
    pr.for_window(dt.datetime.now(UTC) - dt.timedelta(days=30))  # a backfill: cap 7,500
    with pytest.raises(pr.BudgetSpent, match=r"budget spent until \d{4}-\d\d-\d\dT\d\d:\d\dZ") as e:
        pr._pace(200)
    until = dt.datetime.strptime(re.search(r"until (\S+):", str(e.value)).group(1), "%Y-%m-%dT%H:%MZ")
    first_leaves = dt.datetime.fromtimestamp(t0 - 5 * 3600 + 86400, UTC).replace(tzinfo=None)
    assert first_leaves - dt.timedelta(minutes=1) <= until <= first_leaves  # when the oldest request leaves the 24 h
    pr.for_window(dt.datetime.now(UTC))  # a scheduled fetch: cap 9,000, room left
    pr._pace(200)
    assert clock[0] == t0


def test_the_ledger_drops_lines_older_than_a_day(monkeypatch):
    pr = load("openmeteo_previous_runs")
    clock = fake_clock(monkeypatch, pr)
    pr.ledger().parent.mkdir(parents=True)
    pr.ledger().write_text("".join(f"{clock[0] - 2 * 86400 + i:.0f}\t1\tx\n" for i in range(1500)))
    pr._pace(1)
    assert len(pr.ledger().read_text().splitlines()) == 1


# --- openmeteo_previous_runs --------------------------------------------------------------------

def test_requests_group_models_with_the_same_series_and_skip_models_without_data():
    pr = load("openmeteo_previous_runs")
    t = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    reqs = pr.requests_for(t("2026-10-01"), t("2026-10-15"))
    models = sorted(m for ms, _ in reqs for m in ms)
    assert models == sorted(pr.MODELS)
    by_model = {m: params for ms, params in reqs for m in ms}
    assert by_model["ecmwf_ifs025"] == by_model["icon_eu"] == by_model["gfs_global"]
    assert "shortwave_radiation_previous_day2" not in by_model["icon_d2"]  # ICON-D2 has previous_day1 only
    early = pr.requests_for(t("2022-01-01"), t("2022-01-15"))  # only the day0 of GFS before ICON-EU's
    assert early == [(["gfs_global"], pr.DAY0_FULL)]


def test_previous_runs_parse_moves_radiation_to_the_start_and_converts_snow_depth():
    pr = load("openmeteo_previous_runs")
    times = hours("2026-10-01T00:00", 3)
    params = ["shortwave_radiation_previous_day1", "cloud_cover_previous_day1", "cloud_cover_low", "snow_depth"]
    a = answer(times, {
        "shortwave_radiation_previous_day1_icon_eu": [0.0, 10.0, None],
        "cloud_cover_previous_day1_icon_eu": [50, None, None],
        "cloud_cover_low_icon_eu": [20, 30, 40],
        "snow_depth_icon_eu": [0.12, 0.10, None],
        "shortwave_radiation_previous_day1_gfs_global": [None, None, None],
        "cloud_cover_previous_day1_gfs_global": [None, None, None],
        "cloud_cover_low_gfs_global": [None, None, None],
        "snow_depth_gfs_global": [None, None, None],
    }, {k: u for k, u in [("shortwave_radiation_previous_day1_icon_eu", "W/m²"),
                          ("cloud_cover_previous_day1_icon_eu", "%"), ("cloud_cover_low_icon_eu", "%"),
                          ("snow_depth_icon_eu", "m"), ("shortwave_radiation_previous_day1_gfs_global", "W/m²"),
                          ("cloud_cover_previous_day1_gfs_global", "%"), ("cloud_cover_low_gfs_global", "%"),
                          ("snow_depth_gfs_global", "m")]})
    h, i = pr.parse(a, "PAY", ["icon_eu", "gfs_global"], params)
    assert h["delivery_start"].tolist() == [pd.Timestamp("2026-09-30T23:00Z"), pd.Timestamp("2026-10-01T00:00Z")]
    assert h["shortwave_radiation"].tolist() == [0.0, 10.0] and set(h["lead"]) == {"previous_day1"}
    assert h["diffuse_radiation"].isna().all()  # not asked: an empty column
    day0 = i[i["lead"] == "day0"].sort_values("valid_at")
    assert day0["cloud_cover_low"].tolist() == [20.0, 30.0, 40.0]
    assert day0["snow_depth"].tolist()[:2] == pytest.approx([12.0, 10.0])  # m --> cm
    assert set(i["model"]) == {"icon_eu"}  # rows where every value is null are dropped
    assert str(h["delivery_start"].dt.tz) == "UTC"


def test_a_unit_change_fails_and_a_single_model_answer_has_no_suffix():
    pr = load("openmeteo_previous_runs")
    times = hours("2026-10-01T00:00", 2)
    a = answer(times, {"cloud_cover_low": [1, 2]}, {"cloud_cover_low": "%"})
    _, i = pr.parse(a, "PAY", ["icon_d2"], ["cloud_cover_low"])
    assert i["cloud_cover_low"].tolist() == [1.0, 2.0]
    bad = answer(times, {"cloud_cover_low": [1, 2]}, {"cloud_cover_low": "fraction"})
    with pytest.raises(RuntimeError, match="unit"):
        pr.parse(bad, "PAY", ["icon_d2"], ["cloud_cover_low"])


# --- openmeteo_single_runs ----------------------------------------------------------------------

def run_answer(init: str, models: list[str], n_rad: dict[str, int]) -> dict:
    sm = load("openmeteo_single_runs")
    times = hours(init, 72)
    series, units = {}, {}
    for m in models:
        suffix = "" if len(models) == 1 else f"_{m}"
        for v in sm.HOURLY + sm.INSTANT:
            n = n_rad[m] if v in sm.HOURLY else n_rad[m] + 1
            values = [None] + [100.0] * (n) + [None] * (71 - n) if v in sm.HOURLY else [50.0] * n + [None] * (72 - n)
            series[v + suffix] = values
            units[v + suffix] = sm.UNITS[v]
    return answer(times, series, units)


def test_single_runs_lead_and_stamps():
    sm = load("openmeteo_single_runs")
    init = dt.datetime(2026, 11, 14, tzinfo=UTC)
    a = run_answer("2026-11-14T00:00", ["ecmwf_ifs", "meteoswiss_icon_ch1"], {"ecmwf_ifs": 71, "meteoswiss_icon_ch1": 33})
    h, i = sm.parse(a, "PAY", ["ecmwf_ifs", "meteoswiss_icon_ch1"], init)
    ifs = h[h["model"] == "ecmwf_ifs"]
    assert len(ifs) == 71 and ifs["lead_h"].min() == 1 and ifs["lead_h"].max() == 71
    assert ifs["delivery_start"].min() == pd.Timestamp("2026-11-14T00:00Z")
    assert len(h[h["model"] == "meteoswiss_icon_ch1"]) == 33
    assert i[i["model"] == "ecmwf_ifs"]["lead_h"].tolist() == list(range(72))


@pytest.fixture
def single(monkeypatch):
    sm = load("openmeteo_single_runs")
    calls = []

    def fake_ask(init, models, chunk):
        calls.append((init, tuple(models), len(chunk)))
        missing = [m for m in models if m in fake_ask.missing]
        if missing:
            raise sm.SourceError(f"The requested model run is not available. Model: {missing[0]}")
        n = {m: (10 if m in fake_ask.partial else sm.EXPECTED[m]) for m in models}
        return [run_answer(f"{init:%Y-%m-%dT%H:%M}", list(models), n) for _ in chunk]

    fake_ask.missing, fake_ask.partial = set(), set()
    monkeypatch.setattr(sm, "_ask", fake_ask)
    return sm, fake_ask, calls


def test_a_run_before_april_2026_asks_ifs_only(single):
    sm, _, calls = single
    points = [{"station": "PAY", "lat": "46.8", "lon": "6.9"}]
    got = sm.fetch_run(dt.datetime(2025, 6, 1, tzinfo=UTC), points, dt.datetime(2026, 11, 16, tzinfo=UTC))
    assert set(got[0]["model"]) == {"ecmwf_ifs"}
    assert all(models == ("ecmwf_ifs",) for _, models, _ in calls)


def test_a_young_run_without_a_model_is_skipped_and_an_old_one_kept_without_it(single):
    sm, fake, _ = single
    init = dt.datetime(2026, 11, 16, tzinfo=UTC)
    points = [{"station": "PAY", "lat": "46.8", "lon": "6.9"}]
    fake.missing = {"meteoswiss_icon_ch2"}
    assert sm.fetch_run(init, points, init + dt.timedelta(hours=5)) is None
    got = sm.fetch_run(init, points, init + dt.timedelta(hours=30))
    assert set(got[0]["model"]) == {"ecmwf_ifs", "meteoswiss_icon_ch1"}
    fake.missing, fake.partial = set(), {"ecmwf_ifs"}  # served, but not every hour yet
    assert sm.fetch_run(init, points, init + dt.timedelta(hours=5)) is None
    fake.missing, fake.partial = set(sm.MODELS), set()
    with pytest.raises(RuntimeError, match="no model"):
        sm.fetch_run(init, points, init + dt.timedelta(hours=30))


def test_runs_are_the_00_utc_inits_in_the_window():
    sm = load("openmeteo_single_runs")
    t = lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=UTC)  # noqa: E731
    assert sm.runs(t("2026-11-14T01:00"), t("2026-11-16T00:00")) == [t("2026-11-15")]
    assert sm.runs(t("2024-03-01"), t("2024-03-16")) == [t("2024-03-14"), t("2024-03-15")]


# --- openmeteo_era5, openmeteo_cams ---------------------------------------------------------------

def test_era5_joins_the_two_models_and_moves_radiation():
    e5 = load("openmeteo_era5")
    times = hours("2026-11-01T00:00", 2)
    era5 = answer(times, {v: [1.0, 2.0] for v in e5.REQUESTS["era5"]}, {v: e5.UNITS[v] for v in e5.REQUESTS["era5"]})
    land = answer(times, {"temperature_2m": [5.0, None], "snow_depth": [0.3, None]},
                  {"temperature_2m": "°C", "snow_depth": "m"})
    t = e5.tables({"era5": e5.parse(era5, "PAY", "era5"), "era5_land": e5.parse(land, "PAY", "era5_land")})
    assert t["hourly"]["delivery_start"].tolist() == [pd.Timestamp("2026-10-31T23:00Z"), pd.Timestamp("2026-11-01T00:00Z")]
    first = t["instant"].iloc[0]
    assert first["temperature_2m"] == 1.0 and first["temperature_2m_land"] == 5.0 and first["snow_depth"] == pytest.approx(30.0)
    assert pd.isna(t["instant"].iloc[1]["snow_depth"])


def test_cams_keeps_optical_depth_of_the_global_domain_only():
    cm = load("openmeteo_cams")
    times = hours("2026-11-01T00:00", 3)
    g = answer(times, {"dust": [1.0, None, 3.0], "aerosol_optical_depth": [0.1, None, 0.3]},
               {"dust": "μg/m³", "aerosol_optical_depth": ""})
    e = answer(times, {"dust": [2.0, 2.5, None]}, {"dust": "μg/m³"})
    dg, de = cm.parse(g, "PAY", "cams_global"), cm.parse(e, "PAY", "cams_europe")
    assert len(dg) == 2 and dg["aerosol_optical_depth"].tolist() == [0.1, 0.3]
    assert len(de) == 2 and de["aerosol_optical_depth"].isna().all()
    assert set(de["domain"]) == {"cams_europe"}


# --- openmeteo_stations ---------------------------------------------------------------------------

def test_cells_count_the_stations_that_share_one(monkeypatch):
    st = load("openmeteo_stations")
    monkeypatch.setattr(st, "MODELS", {"ecmwf_ifs025": st.MODELS["ecmwf_ifs025"]})

    def fake_get(url, params, w):
        n = len(params["latitude"].split(","))
        # the first two points in one cell, the others each in their own
        return [answer([], {}, {}, location_id=i if i else None) | {"latitude": 46.75 if i < 2 else 40 + i,
                                                                     "longitude": 7.0}
                for i in range(n)]

    monkeypatch.setattr(st, "get", fake_get)
    out = st.fetch(dt.datetime(2026, 1, 1, tzinfo=UTC), dt.datetime(2026, 1, 2, tzinfo=UTC))
    cells = out["cells"]
    assert len(out["stations"]) == 79 and len(cells) == 79
    assert cells["stations_in_cell"].tolist()[:3] == [2, 2, 1]
    assert re.fullmatch(r"[A-Z]{3}", cells["station"].iloc[0])


# --- ecmwf_ifs_ens --------------------------------------------------------------------------------

def test_ens_skips_a_young_run_that_is_not_whole_and_fails_on_an_old_one(monkeypatch):
    ens = load("ecmwf_ifs_ens")

    class Store:
        init_time = type("C", (), {"values": pd.to_datetime(["2026-11-14", "2026-11-15"]).values})()

    monkeypatch.setattr(ens, "open_store", lambda: Store())
    monkeypatch.setattr(ens, "grid_points", lambda ds, pts: pts.assign(cell_lat=0.0, cell_lon=0.0, cell_distance_km=0.0))
    monkeypatch.setattr(ens, "read_run", lambda ds, init, pts: None)  # not whole
    now = dt.datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    young = ens.fetch(now, now + dt.timedelta(days=1))  # today's run: not in the store, young
    assert young["three_hourly"].empty and len(young["stations"]) == 79
    with pytest.raises(RuntimeError, match="not whole"):
        ens.fetch(dt.datetime(2026, 11, 14, tzinfo=UTC), dt.datetime(2026, 11, 15, tzinfo=UTC))


def ens_arrays(ens, nan_at=None) -> dict:
    """One run: leads 0, 3, 6 h, 2 members, 2 grid cells. Every variable is 1.0 (pressure 95,000 Pa,
    precipitation type 2); the averaged ones are null at lead 0, like the source."""
    import numpy as np

    out = {}
    for v in ens.VARS:
        x = np.full((3, 2, 2), 95000.0 if v == "pressure_surface" else
                    2.0 if v == "categorical_precipitation_type_surface" else 1.0)
        if v in ens.THREE_HOURLY:
            x[0] = np.nan
        out[v] = x
    if nan_at:
        out[nan_at[0]][nan_at[1]] = np.nan
    return out


def test_ens_stamps_units_and_isolated_nulls():
    import numpy as np

    ens = load("ecmwf_ifs_ens")
    cells = pd.DataFrame({"i": [10, 11], "j": [20, 21]})
    pts = pd.DataFrame({"station": ["AAA", "BBB", "CCC"], "i": [10, 11, 11], "j": [20, 21, 21]})  # BBB, CCC share a cell
    init, lh, members = dt.datetime(2025, 12, 1, tzinfo=UTC), np.array([0, 3, 6]), np.array([0, 1])
    arrays = ens_arrays(ens, nan_at=(ens.GHI, (1, 0, 1)))  # one null of radiation at lead 3, member 0, cell 1
    three, inst = ens.tables(arrays, lh, members, cells, pts, init)
    assert three["delivery_start"].min() == pd.Timestamp("2025-12-01T00:00Z")  # lead 3 covers [00:00, 03:00)
    assert sorted(three["lead_h"].unique()) == [3, 6] and len(three) == 2 * 2 * 3  # leads x members x stations
    assert three["precipitation"].iloc[0] == 10800.0  # a rate of 1 mm/s over 3 h
    assert three["shortwave_radiation"].isna().sum() == 2  # the isolated null stays null, at both stations of its cell
    assert inst["valid_at"].min() == pd.Timestamp("2025-12-01T00:00Z") and len(inst) == 3 * 2 * 3
    assert inst["pressure_surface"].iloc[0] == 950.0 and str(inst["precipitation_type"].dtype) == "Int64"
    assert list(three.columns) == list(ens.empty()[0].columns) and list(inst.columns) == list(ens.empty()[1].columns)
    no_t = ens_arrays(ens, nan_at=(ens.T2M, (2, 1, 1)))  # one temperature missing: not written yet
    assert ens.tables(no_t, lh, members, cells, pts, init) is None
    no_ghi = ens_arrays(ens, nan_at=(ens.GHI, 2))  # no radiation at all at lead 6: not written yet
    assert ens.tables(no_ghi, lh, members, cells, pts, init) is None


# --- deploy/backfill_by_window.py ------------------------------------------------------------------

def test_the_driver_waits_for_the_budget_and_the_lock_and_tries_the_same_window_again(tmp_path):
    spec = importlib.util.spec_from_file_location("bbw", DATASETS.parent / "deploy" / "backfill_by_window.py")
    bbw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bbw)
    later = (dt.datetime.now(UTC) + dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:%MZ")
    replies = [  # (exit code, stdout) of adele-server backfill, in order
        (0, "x: 1 windows, 10 rows, 0 failed; status ok"),
        (1, f"x: 1 windows, 0 rows, 1 failed\n  failed [...]: fetch.py exited with code 1: | "
            f"BudgetSpent: Open-Meteo budget spent until {later}: 7,400 calls"),
        (1, "error: another fetch of x is running"),
        (0, "x: 1 windows, 10 rows, 0 failed; status ok"),
        (1, "x: 1 windows, 0 rows, 1 failed\n  failed [...]: KeyError: 'hourly'"),
        (1, "KeyError: 'hourly'"), (1, "KeyError: 'hourly'"),
    ]
    cmds, slept = [], []

    def run(cmd, **kw):
        cmds.append(cmd)
        rc, out = replies.pop(0)
        return type("R", (), {"returncode": rc, "stdout": out, "stderr": ""})()

    plan = ["x,2024-01-01,2024-01-27,13", "y,2024-01-01,2024-01-02,1"]
    done = str(tmp_path / "done.tsv")
    rc = bbw.main(["--bin", "adele-server", "--done", done, *plan], sleep=slept.append, run=run)
    assert rc == 1  # the window of y failed 3 times
    starts = [c[c.index("--start") + 1][:10] for c in cmds]
    assert starts == ["2024-01-01", "2024-01-14", "2024-01-14", "2024-01-14", "2024-01-01", "2024-01-01", "2024-01-01"]
    assert 3 * 3600 - 60 <= slept[0] <= 3 * 3600 + 120 and slept[1:] == [120.0, 600, 600]
    assert cmds[0][-2:] == ["--step-days", "13"] and cmds[1][cmds[1].index("--end") + 1].startswith("2024-01-27")
    # a restart skips the two windows of x that are done, and tries y again
    cmds.clear()
    replies.append((0, "y: 1 windows, 5 rows, 0 failed; status ok"))
    assert bbw.main(["--bin", "adele-server", "--done", done, *plan], sleep=slept.append, run=run) == 0
    assert [c[c.index("backfill") + 1] for c in cmds] == ["y"]
