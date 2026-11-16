# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.2", "pyarrow>=15", "requests>=2.31"]
# ///
"""Fetch Pronovo's "Lastgangprofile nach Technologien": the measured production of Swiss plants
per technology at 15 minutes (table by_technology), the PV per canton (pv_by_canton), and the
installed capacity and number of units at the end of each month (capacity_by_technology,
pv_capacity_by_canton).

Draft by Claude, 2026-11-15 (WP5.5). The facts below come from the swissgrid project
(`swissgrid_project/data/pronovo/README.md`, files read on 2026-10-31 and 2026-11-01), unless
marked as measured here.

Source: https://pronovo.ch/de/services/berichte/ ("Lastgangprofile nach Technologien"),
directory listings without login: https://pronovo.ch/downloads/Lastgangprofile_nach_Technologien/
(current year) and `.../Archiv/<year>/` (the years before).

Files, and which one gives each month:

- From 2023, two zips: `YYYYMM_CH_Total_Monat_prov.zip`, one local month, provisional, a median
  of 11 days after the month (1 to 22); and `YYYYMM_CH_Total_Quartal_def.zip`, the three months
  of a quarter, definitive ("Messmengen aus nachträglicher Lieferung der letzten drei Monate"),
  about 11 days after the quarter (60 days for Q4 2025). The provisional files of 2023-03,
  2023-06 and 2023-09 don't exist. Each zip holds one national CSV with every technology and
  26 CSVs of PV, one per canton (in a sub-folder in 2023).
- 2020 to 2022: one CSV per local month in `Archiv/<year>/DE/Lastgangprofile_MM.YYYY.csv`,
  national only, no auxiliary supply, no capacity. Their values equal the annual file
  `Total_Jahr_<year>.xlsx` in all 1,165,418 common pairs of quarter-hour and technology, and the
  CSV of March 2021 holds 1,093 quarter-hours that the xlsx lacks; so the xlsx is not read.
  `version` is `archive` for these rows: no definitive file exists for these years.

For each local month and each CSV (the national one, or one canton), the definitive file is
used when its CSV covers the whole month; otherwise the file (definitive or provisional) whose
CSV has more quarter-hours in that month. So the provisional zip is downloaded only when the
definitive one is missing or incomplete. With `revisions: append-only`, the move from the
provisional to the definitive file is a new version of each row: adele keeps both. A backfill
stores only the file that is best at that time.

Format of a CSV in a zip: latin-1, `;`. Row 1: a title and "Erstellt: dd.mm.yyyy hh:mm:ss".
Row 2: the header: "Koordinierte Weltzeit (UTC)", "Mitteleuropäische Zeit (CET/CEST)", then 4
columns per technology: `+A.<t> [kWh]` (energy drawn by the plants, auxiliary supply),
`-A.<t> [kWh]` (energy delivered), `Leistung.<t> [kVA]` (`[kW]` in the files of 2026) and
`Anzahl.<t>`. The capacity and the number are filled only in the last quarter-hour of each
local month (a few zeros elsewhere in empty technologies are ignored).

Conventions and checks:

- The UTC stamp marks the END of the quarter-hour: `delivery_start` = stamp - 15 min. Evidence
  (swissgrid project): each monthly file runs from local 00:15 of day 1 to local 00:00 of day 1
  of the next month; averaged into hours with this reading, Pronovo's PV is proportional to
  ENTSO-E's Swiss PV inside each month (ENTSO-E rescales Pronovo), with a spread of 0.0009
  against 0.22 with the other reading.
- The local column must be the same instant in Europe/Zurich, and the stamps must increase by
  15 minutes without a repeat: otherwise the fetch fails (0 mismatches in 1,539 CSVs).
- 2020 to 2022 carry local end stamps only, in time order. A stamp written twice (02:00 to
  02:45 of the fall-back night) is summer time the first time (smoother totals in 3 of 3 years,
  and the same values as the xlsx at the same instants). In `Lastgangprofile_03.2021.csv`,
  1,093 rows hold an Excel serial number in place of the stamp: the stamp is the previous one
  plus 15 minutes, checked against the serial (0.005 day) and against the next written stamp.
- kWh per quarter-hour: `production_mwh` = -A / 1000, `production_mw` = -A x 4 / 1000 (the
  mean power of the quarter-hour), `auxiliary_mwh` = +A / 1000.
- A technology whose -A and +A are both empty in a whole month of a CSV gives no row for that
  month (geothermal, fossil_other and four machine types are always empty). A single empty
  cell is a null.
- An unknown name of technology, of CSV in a zip, or of unit of capacity fails the fetch: a
  person maps it first (TECH below, and the descriptor's categories).
- A month that ended more than 40 days ago without any file fails the fetch: Pronovo publishes
  within 1 to 22 days.
- `suspect` marks the known problems of the national rows (SUSPECT_* below; the swissgrid
  project's QA, sections 8b, 8c and 9 of its README, and the comparison with BFE's monthly
  balance). The values are kept as published.

Measured on 2026-11-15 (WP5.5):

- On the swissgrid project's copies of the files (98 files of 2026-10-31 and 2026-11-01), this
  file gives the same values as that project's parquet tables for every row of the same file:
  1,180,720 rows of 2020-2022 and 2,251,608 of 2023-2026 (national), 3,414,040 (cantons), 771
  capacities; largest difference 0.0005 MW (that project stored float32). It reads all files in
  28 s.
- Every local month of 2023 to 2026-09 comes from the definitive file, for the national CSV and
  for every canton. Glarus has no PV for June 2023: the definitive file of 2023-Q2 has 5,857 of
  8,736 rows (April, May and one empty row in June), and no provisional file of 2023-06 exists.
- The scheme by machine type covers the files of 2023-01 to 2023-03 (definitive of Q1), the one
  by energy source the files from 2023-04 (definitive of Q2). No file maps two columns to one
  technology. The capacity is in kVA up to the files of December 2025 and in kW from January
  2026.
- Backfill from 2020 on the Mac (7 windows of 365 days, 6 to 10 minutes, about 70 MB): by_technology
  3,485,968 rows, pv_by_canton 3,491,520, capacity_by_technology 789, pv_capacity_by_canton
  1,196. 92 and 100 quarter-hours on the 7 spring and 7 autumn days of the clock change, no gap
  in the series of PV, wind, nuclear, run-of-river and biogas. October 2026 is provisional
  (published by 2026-11-15). PV of the local year 2025: 4,071 GWh, as in the swissgrid project.
- A second fetch of the same window stores nothing. A scheduled run (400 days back) reads
  1,601,827 rows in about 1 minute and stores nothing.
- Pronovo's own sums in the last row of Lastgangprofile_11.2020.csv match the local month to
  0.005 kWh for all 8 technologies (checks.yaml); on the UTC month they differ (hydro by -931 MWh).
- Against BFE's monthly balance (net, whole GWh; qa/published_figures_pronovo_production.md):
  nuclear 1.000 to 1.014 of BFE in each month of 2023-01 to 2026-08, except 0.66 in 2024-09,
  2025-02 and 2025-03, where the file lists 1,980 instead of 3,015 MW (one unit missing; marked
  nuclear_missing_unit). In 2025-09 the file lists 1,980 MW too, but its energy matches: the
  missing unit was off. Hydro 0.76 to 0.94 of BFE, except 0.59 to 0.68 in 2024-09, 2025-02,
  2025-03 and 2025-09.

Measured on 2026-11-16: BFE computes the volumes of its reference market prices (Art. 15 EnFV)
from these files, as -A minus +A. All 156 monthly volumes of 2023-07 to 2026-09 (PV, wind, hydro
in five categories, biomass in five) match the stored data within 0.5 MWh, their rounding
(checks.yaml).
"""
from __future__ import annotations

import datetime as dt
import io
import re
import time
import zipfile
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd
import requests

UTC = dt.timezone.utc
ZRH = ZoneInfo("Europe/Zurich")
BASE = "https://pronovo.ch/downloads/Lastgangprofile_nach_Technologien/"
FIRST_MONTH = (2020, 1)
ZIPS_FROM = 2023  # the zips start in 2023; before, one CSV per month in Archiv/<year>/DE/
LATE = dt.timedelta(days=40)  # a month that ended longer ago must have a file
QH = pd.Timedelta(minutes=15)
TIMEOUT_S = 120
ATTEMPTS = 3
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; adele dataset fetcher)"}
FILE_RE = re.compile(r'href=["\']?([^"\'\s>?#]+\.(?:zip|csv|xlsx))', re.I)  # Pronovo writes href=name.zip, no quotes

CANTONS = ("AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW", "OW", "SG", "SH",
           "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH")
NATIONAL = "CH"

# Name in the file --> (technology, group). Three schemes: by energy source in the files from
# 2023-04 (2023-06 for the definitive ones), by machine type in the files of 2023-01 to 2023-05,
# and the names of 2020-2022. Equivalent hydro types share one technology.
TECH = {
    "Photovoltaik": ("pv", "pv"),
    "Biogas": ("biogas", "biomass"),
    "Übrige Biomasse": ("biomass_other", "biomass"),
    "Holzenergie": ("wood", "biomass"),
    "Kehrichtverbrennung (erneuerbar)": ("waste_renewable", "waste"),
    "Klärgas": ("sewage_gas", "biomass"),
    "Abwasserkraftwerk": ("hydro_wastewater", "hydro"),
    "Ausleitkraftwerk": ("hydro_diversion", "hydro"),
    "Dotierwasserkraftwerk": ("hydro_residual_flow", "hydro"),
    "Durchlaufkraftwerk": ("hydro_run_of_river", "hydro"),
    "Trinkwasserkraftwerk": ("hydro_drinking_water", "hydro"),
    "Pumpspeicherkraftwerk": ("hydro_pumped_storage", "hydro"),
    "Speicherkraftwerk": ("hydro_storage", "hydro"),
    "Windenergie": ("wind", "wind"),
    "Geothermie": ("geothermal", "other"),
    "Flüssige fossile Energieträger": ("fossil_liquid", "fossil"),
    "Gasförmige fossile Energieträger": ("fossil_gas", "fossil"),
    "Kehrichtverbrennung (nicht erneuerbar)": ("waste_nonrenewable", "waste"),
    "Übrige fossile Energieträger": ("fossil_other", "fossil"),
    "Kernenergie": ("nuclear", "nuclear"),
    # machine types, files of 2023-01 to 2023-05
    "Forst- und Landwirtschaftliche Abfälle": ("biomass_forest_agri_waste", "biomass"),
    "Kehrichtverbrennung": ("waste_total", "waste"),
    "Abwasserkraft": ("hydro_wastewater", "hydro"),
    "Ausleitwasser": ("hydro_diversion", "hydro"),
    "Dotierwasser": ("hydro_residual_flow", "hydro"),
    "Durchlaufwasser": ("hydro_run_of_river", "hydro"),
    "Pumpspeicherkraft": ("hydro_pumped_storage", "hydro"),
    "Speicherkraft": ("hydro_storage", "hydro"),
    "Trinkwasser": ("hydro_drinking_water", "hydro"),
    "Brennstoffzelle": ("fuel_cell", "thermal"),
    "Erdgas Dampfturbine": ("thermal_gas_steam_turbine", "thermal"),
    "Erdöl Dampfturbine": ("thermal_oil_steam_turbine", "thermal"),
    "Gas- und Dampfkombikraftwerk": ("thermal_ccgt", "thermal"),
    "Gasturbine": ("thermal_gas_turbine", "thermal"),
    "Leichtwasserreaktor": ("nuclear", "nuclear"),
    "Nicht spezifizierte Technologie": ("unspecified", "other"),
    "ORC-Dampfturbine": ("thermal_orc", "thermal"),
    "Verbrennungsmotor": ("thermal_combustion_engine", "thermal"),
    "Windturbine": ("wind", "wind"),
    # 2020-2022
    "Photovoltaic": ("pv", "pv"),
    "Biomasse": ("biomass_total", "biomass"),
    "Energiepflanze": ("biomass_energy_crops", "biomass"),
    "Abwasser": ("hydro_wastewater", "hydro"),
    "Wasser": ("hydro_total", "hydro"),
    "Wind": ("wind", "wind"),
}

# Known problems of the national rows, kept as published and marked in `suspect`.
# Single quarter-hours that are not physical (QA 8b): (delivery_start in UTC, technology).
SUSPECT_SPIKES = [
    ("2022-03-31 21:45", "waste_renewable"),  # 1,519 MW at local 23:45 on 31 Mar 2022, neighbours 144 and 155 MW
    ("2022-09-19 22:00", "pv"),  # 791 MW at local 00:00 on 20 Sep 2022 (night)
    ("2022-09-20 22:00", "pv"),  # 793 MW at local 00:00 on 21 Sep 2022 (night)
]
# Periods of one technology, by local date (first, last), both versions.
SUSPECT_PERIODS = [
    # PV about twice too high: 2.1 to 4.3 x the energy per unit of irradiance (swissgrid project, QA 8c)
    ("pv_level_2021_08", "pv", "2021-08-01", "2021-08-07"),
    # the canton files sum to 1.50 x the national PV (swissgrid project, section 9)
    ("pv_national_missing_plants", "pv", "2024-09-01", "2024-09-30"),
    # the file has 1,980 instead of 3,015 MW of nuclear, and its energy is 0.66 of BFE's monthly
    # nuclear production, against 1.000 to 1.014 in the other months (qa/published_figures_pronovo_production.md)
    ("nuclear_missing_unit", "nuclear", "2024-09-01", "2024-09-30"),
    ("nuclear_missing_unit", "nuclear", "2025-02-01", "2025-03-31"),
]

COLUMNS = {
    "by_technology": {"delivery_start": "datetime64[ns, UTC]", "technology": "object", "technology_src": "object",
                      "group": "object", "production_mwh": "float64", "production_mw": "float64",
                      "auxiliary_mwh": "float64", "version": "object", "suspect": "object"},
    "pv_by_canton": {"delivery_start": "datetime64[ns, UTC]", "canton": "object", "production_mwh": "float64",
                     "production_mw": "float64", "auxiliary_mwh": "float64", "version": "object"},
    "capacity_by_technology": {"delivery_month": "object", "technology": "object", "technology_src": "object",
                               "group": "object", "capacity_mva": "float64", "capacity_mw": "float64",
                               "units": "Int64", "version": "object"},
    "pv_capacity_by_canton": {"delivery_month": "object", "canton": "object", "capacity_mva": "float64",
                              "capacity_mw": "float64", "units": "Int64", "version": "object"},
}


# --- network -------------------------------------------------------------------------------------

def _get(url: str) -> bytes | None:
    """The body of a GET, None for a 404. Retries on a timeout, a lost connection or a 5xx."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout) as e:
            if attempt == ATTEMPTS:
                raise RuntimeError(f"{url}: no answer after {ATTEMPTS} attempts ({e})") from e
            time.sleep(5 * attempt)
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 500 and attempt < ATTEMPTS:
            time.sleep(5 * attempt)
            continue
        r.raise_for_status()
        return r.content
    raise AssertionError("unreachable")


def listing(url: str) -> dict[str, str]:
    """{file name: url} of a directory listing; {} when the folder doesn't exist."""
    body = _get(url)
    if body is None:
        return {}
    text = body.decode("utf-8", errors="replace")
    return {h.rsplit("/", 1)[-1]: urljoin(url, h) for h in FILE_RE.findall(text)}


def download(url: str) -> bytes:
    body = _get(url)
    if body is None:
        raise RuntimeError(f"{url}: listed, but the download answers 404")
    return body


# --- parsing -------------------------------------------------------------------------------------

def _num(s: pd.Series) -> pd.Series:
    """Cells such as "9'124.38", " 10\\x92699.285 " or "" --> float, NaN for an empty cell. The
    thousands mark is "'" or, in one column of Lastgangprofile_02.2021.csv, the byte 0x92."""
    s = s.fillna("").astype(str).str.replace(r"['\x92\u2019\s]", "", regex=True)
    return pd.to_numeric(s.mask(s == ""), errors="raise").astype("float64")


def _check_steps(end: pd.Series, name: str) -> None:
    """The stamps increase by whole quarter-hours: no repeat, no disorder. A missing quarter-hour is
    allowed (the definitive GL file of 2023-Q2 has 5,857 of 8,736)."""
    steps = end.diff().dropna()
    bad = (steps <= pd.Timedelta(0)) | (steps % QH != pd.Timedelta(0))
    if bad.any():
        raise RuntimeError(f"{name}: the stamps don't increase by whole quarter-hours "
                           f"(at {end[steps.index[bad.values][0]]})")
    if ((end.dt.minute % 15 != 0) | (end.dt.second != 0)).any():
        raise RuntimeError(f"{name}: a stamp is not on a quarter-hour")


def read_zip_csv(raw: bytes, name: str) -> tuple[pd.Series, dict]:
    """One CSV of a zip --> (end stamps in UTC, {name of technology: {out, inn, cap, cap_unit, n}})."""
    lines = raw.decode("latin-1").splitlines()
    if len(lines) < 2 or "Erstellt" not in lines[0]:
        raise RuntimeError(f"{name}: row 1 is not the title with 'Erstellt'")
    df = pd.read_csv(io.StringIO("\n".join(lines[1:])), sep=";", dtype=str, keep_default_na=False, index_col=False)
    utc_col, loc_col = df.columns[:2]
    if not (utc_col.startswith("Koordinierte Weltzeit") and loc_col.startswith("Mitteleurop")):
        raise RuntimeError(f"{name}: the first two columns are {utc_col!r}, {loc_col!r}")
    df = df[df[utc_col].str.strip() != ""].reset_index(drop=True)
    end = pd.to_datetime(df[utc_col].str.strip(), format="%d.%m.%Y %H:%M").dt.tz_localize("UTC")
    local = pd.to_datetime(df[loc_col].str.strip(), format="%d.%m.%Y %H:%M")
    bad = int((end.dt.tz_convert(ZRH).dt.tz_localize(None) != local).sum())
    if bad:
        raise RuntimeError(f"{name}: {bad} rows whose local stamp is not the UTC stamp in Europe/Zurich")
    _check_steps(end, name)
    techs = {}
    for c in df.columns:
        m = re.fullmatch(r"-A\.(.+) \[kWh\]", c)
        if not m:
            continue
        t = m.group(1)
        if t not in TECH:
            raise RuntimeError(f"{name}: unknown technology {t!r}: map it in TECH and in the descriptor")
        cap = [k for k in df.columns if k.startswith(f"Leistung.{t} [")]
        unit = re.search(r"\[(.+)\]$", cap[0]).group(1) if cap else None
        if unit not in (None, "kVA", "kW"):
            raise RuntimeError(f"{name}: capacity of {t!r} in {unit!r}, expected kVA or kW")
        techs[t] = dict(out=_num(df[c]), inn=_num(df[f"+A.{t} [kWh]"]),
                        cap=_num(df[cap[0]]) if cap else None, cap_unit=unit,
                        n=_num(df[f"Anzahl.{t}"]) if f"Anzahl.{t}" in df.columns else None)
    slugs = [TECH[t][0] for t in techs]
    if len(set(slugs)) != len(slugs):
        raise RuntimeError(f"{name}: two columns map to one technology: {sorted(techs)}")
    if not techs:
        raise RuntimeError(f"{name}: no column '-A.<technology> [kWh]'")
    return end, techs


def read_zip(raw: bytes, name: str) -> dict[str, tuple[pd.Series, dict]]:
    """A zip --> {CH or canton: (end stamps, technologies)}."""
    out = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for member in z.namelist():
            base = member.rsplit("/", 1)[-1]
            if not base.lower().endswith(".csv"):
                continue
            m = re.search(r"_CH_PV_([A-Z]{2})_", base)
            series = m.group(1) if m else NATIONAL if "_CH_Total_" in base else None
            if series is None or (series != NATIONAL and series not in CANTONS):
                raise RuntimeError(f"{name}: unknown CSV {base!r}")
            if series in out:
                raise RuntimeError(f"{name}: two CSVs for {series}")
            out[series] = read_zip_csv(z.read(member), f"{name}:{base}")
    if NATIONAL not in out:
        raise RuntimeError(f"{name}: no national CSV (*_CH_Total_*.csv)")
    return out


STAMP_RE = re.compile(r"^\d\d\.\d\d\.\d{4} \d\d:\d\d$")
SERIAL_RE = re.compile(r"^\d{2}'\d{3}\.\d+$")  # an Excel serial: 44'256.35 = 1 Mar 2021 08:24
EXCEL_EPOCH = dt.datetime(1899, 12, 30)


def read_archive_csv(raw: bytes, name: str) -> tuple[pd.Series, dict]:
    """A monthly CSV of 2020-2022 --> (end stamps in UTC, {name of technology: {out, inn, ...}}).

    Comment lines (# or ;) before the header "Datum/Zeit;" or "Datum Zeit;", one column
    "<name> (kWh)" per technology, local end stamps; in one file a last row of column sums
    without a stamp (dropped). Rows whose first cell is an Excel serial get the previous stamp
    plus 15 minutes.
    """
    lines = [ln for ln in raw.decode("latin-1").splitlines() if ln.strip()]
    hdr = next((i for i, ln in enumerate(lines) if re.match(r"^Datum[/ ]Zeit;", ln)), None)
    if hdr is None:
        raise RuntimeError(f"{name}: no header 'Datum/Zeit;...'")
    names = [re.sub(r"\s*\(kWh\)\s*$", "", c.strip()) for c in lines[hdr].split(";")]
    keep = [j for j, c in enumerate(names) if j > 0 and c]
    rows = [ln.split(";") for ln in lines[hdr + 1:]]
    data = [r for r in rows if STAMP_RE.match(r[0].strip()) or SERIAL_RE.match(r[0].strip())]
    stamps: list[dt.datetime] = []
    for k, r in enumerate(data):
        cell = r[0].strip()
        if STAMP_RE.match(cell):
            st = dt.datetime.strptime(cell, "%d.%m.%Y %H:%M")
            if k and SERIAL_RE.match(data[k - 1][0].strip()) and st != stamps[-1] + QH:
                raise RuntimeError(f"{name}: the stamp {cell} doesn't follow the recovered rows before it")
        else:
            if not k:
                raise RuntimeError(f"{name}: the first row has no stamp")
            st = stamps[-1] + QH
            if abs((st - EXCEL_EPOCH).total_seconds() / 86400 - float(cell.replace("'", ""))) > 0.0051:
                raise RuntimeError(f"{name}: the serial {cell} is not the stamp {st} that its position gives")
        stamps.append(st)
    seen: dict[dt.datetime, int] = {}
    ends = []
    for st in stamps:  # a stamp written twice (the fall-back night) is summer time the first time
        fold = seen.get(st, 0)
        seen[st] = fold + 1
        aware = st.replace(tzinfo=ZRH, fold=fold)
        if fold > 1 or aware.astimezone(UTC).astimezone(ZRH).replace(tzinfo=None) != st:
            raise RuntimeError(f"{name}: the local stamp {st} doesn't exist or comes more than twice")
        ends.append(aware.astimezone(UTC))
    end = pd.Series(pd.DatetimeIndex(ends).tz_convert("UTC"))
    _check_steps(end, name)
    techs = {}
    for j in keep:
        t = names[j]
        if t not in TECH:
            raise RuntimeError(f"{name}: unknown technology {t!r}: map it in TECH and in the descriptor")
        vals = _num(pd.Series([r[j] if j < len(r) else "" for r in data], dtype=object))
        techs[t] = dict(out=vals, inn=pd.Series(float("nan"), index=vals.index), cap=None, cap_unit=None, n=None)
    return end, techs


# --- months and files ----------------------------------------------------------------------------

def months(start: dt.datetime, end: dt.datetime, now: dt.datetime) -> list[tuple[int, int]]:
    """The local months (year, month) that overlap [start, end), from 2020-01 to the month of now."""
    if end <= start:
        return []
    a = start.astimezone(ZRH)
    b = (end - dt.timedelta(microseconds=1)).astimezone(ZRH)
    n = now.astimezone(ZRH)
    y, m = max((a.year, a.month), FIRST_MONTH)
    last = min((b.year, b.month), (n.year, n.month))
    out = []
    while (y, m) <= last:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def month_bounds(y: int, m: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """[first instant, first instant of the next month) of a local month, in UTC."""
    lo = pd.Timestamp(dt.datetime(y, m, 1), tz=ZRH)
    hi = pd.Timestamp(dt.datetime(y + (m == 12), m % 12 + 1, 1), tz=ZRH)
    return lo.tz_convert("UTC"), hi.tz_convert("UTC")


def _in_month(end: pd.Series, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.Series:
    start = end - QH
    return (start >= lo) & (start < hi)


class Files:
    """The listings and the parsed files of one call of fetch(); each file is read once."""

    def __init__(self):
        self._listings: dict[str, dict[str, str]] = {}
        self._parsed: dict[str, dict] = {}

    def _folder(self, path: str) -> dict[str, str]:
        if path not in self._listings:
            self._listings[path] = listing(BASE + path)
        return self._listings[path]

    def url(self, year: int, name: str) -> str | None:
        """The url of a zip of `year`: in the folder of the current year, else in Archiv/<year>/."""
        return self._folder("").get(name) or self._folder(f"Archiv/{year}/").get(name)

    def zip(self, year: int, name: str) -> dict | None:
        if name not in self._parsed:
            url = self.url(year, name)
            self._parsed[name] = None if url is None else read_zip(download(url), name)
        return self._parsed[name]

    def archive_csv(self, year: int, month: int) -> dict | None:
        name = f"Lastgangprofile_{month:02d}.{year}.csv"
        if name not in self._parsed:
            url = self._folder(f"Archiv/{year}/DE/").get(name)
            self._parsed[name] = None if url is None else {NATIONAL: read_archive_csv(download(url), name)}
        return self._parsed[name]


def choose(files: Files, y: int, m: int) -> dict[str, tuple[str, pd.Series, dict]]:
    """{CH or canton: (version, end stamps, technologies)} for one local month: the definitive
    CSV when it covers the whole month, else the CSV with more quarter-hours in the month."""
    lo, hi = month_bounds(y, m)
    if y < ZIPS_FROM:
        got = files.archive_csv(y, m)
        return {} if got is None else {NATIONAL: ("archive", *got[NATIONAL])}
    full = int((hi - lo) / QH)
    q = f"{y}{(m - 1) // 3 * 3 + 3:02d}_CH_Total_Quartal_def.zip"
    p = f"{y}{m:02d}_CH_Total_Monat_prov.zip"
    definitive = files.zip(y, q) or {}
    count = {s: int(_in_month(end, lo, hi).sum()) for s, (end, _) in definitive.items()}
    out = {s: ("def", *definitive[s]) for s, c in count.items() if c == full}
    if len(out) < 1 + len(CANTONS):
        provisional = files.zip(y, p) or {}
        for s in (NATIONAL, *CANTONS):
            if s in out:
                continue
            c_def = count.get(s, 0)
            c_prov = int(_in_month(provisional[s][0], lo, hi).sum()) if s in provisional else 0
            if c_def and c_def >= c_prov:
                out[s] = ("def", *definitive[s])
            elif c_prov:
                out[s] = ("prov", *provisional[s])
    return out


# --- rows ----------------------------------------------------------------------------------------

def _suspect(df: pd.DataFrame) -> pd.Series:
    out = pd.Series(None, index=df.index, dtype=object)
    if df.empty:
        return out
    day = df["delivery_start"].dt.tz_convert(ZRH).dt.strftime("%Y-%m-%d")
    for code, tech, first, last in SUSPECT_PERIODS:
        out[(df["technology"] == tech) & (day >= first) & (day <= last)] = code
    for start, tech in SUSPECT_SPIKES:
        out[(df["delivery_start"] == pd.Timestamp(start, tz="UTC")) & (df["technology"] == tech)] = "spike"
    return out


def _energy(d: dict, sel: pd.Series) -> dict:
    """kWh --> MWh and MW, rounded to 7 decimals: the files give at most 4 decimals of kWh, and
    the division by 1000 would otherwise print as 7.072926000000001."""
    out, inn = d["out"][sel], d["inn"][sel]
    return dict(production_mwh=(out / 1000).round(7), production_mw=(out * 4 / 1000).round(7),
                auxiliary_mwh=(inn / 1000).round(7))


def _capacity(d: dict, end: pd.Series, hi: pd.Timestamp) -> dict | None:
    """The capacity and the number of units in the last quarter-hour of the month, or None."""
    if d["cap"] is None:
        return None
    last = end == hi  # the quarter-hour that ends at local 00:00 of day 1 of the next month
    if not last.any():
        return None
    cap = d["cap"][last].iloc[0]
    n = d["n"][last].iloc[0] if d["n"] is not None else float("nan")
    if pd.isna(cap) and pd.isna(n):
        return None
    cap = round(cap / 1000, 6)  # kVA or kW with at most 2 decimals
    return dict(capacity_mva=cap if d["cap_unit"] == "kVA" else float("nan"),
                capacity_mw=cap if d["cap_unit"] == "kW" else float("nan"),
                units=pd.NA if pd.isna(n) else int(round(n)))


def month_rows(chosen: dict, y: int, m: int) -> dict[str, list]:
    lo, hi = month_bounds(y, m)
    month = dt.date(y, m, 1)
    rows: dict[str, list] = {t: [] for t in COLUMNS}
    for series, (version, end, techs) in chosen.items():
        sel = _in_month(end, lo, hi)
        start = (end - QH)[sel]
        for t, d in techs.items():
            slug, group = TECH[t]
            energy = _energy(d, sel)
            cap = _capacity(d, end, hi)
            if series == NATIONAL:
                if not (energy["production_mwh"].isna().all() and energy["auxiliary_mwh"].isna().all()):
                    rows["by_technology"].append(pd.DataFrame(dict(
                        delivery_start=start, technology=slug, technology_src=t, group=group, **energy,
                        version=version)))
                if cap:
                    rows["capacity_by_technology"].append(pd.DataFrame([dict(
                        delivery_month=month, technology=slug, technology_src=t, group=group, **cap,
                        version=version)]))
            elif t == "Photovoltaik":
                if not (energy["production_mwh"].isna().all() and energy["auxiliary_mwh"].isna().all()):
                    rows["pv_by_canton"].append(pd.DataFrame(dict(
                        delivery_start=start, canton=series, **energy, version=version)))
                if cap:
                    rows["pv_capacity_by_canton"].append(pd.DataFrame([dict(
                        delivery_month=month, canton=series, **cap, version=version)]))
            else:
                raise RuntimeError(f"{y}-{m:02d} {series}: a canton CSV with {t!r}, expected Photovoltaik only")
    return rows


def _frame(table: str, parts: list) -> pd.DataFrame:
    cols = COLUMNS[table]
    if not parts:
        # An empty column of dates must still read as DATE: an empty object column is typed NULL,
        # and the server's window filter (ingest._window_filter) fails on NULL + INTERVAL 1 MONTH
        # (2026-11-15, the backfill windows of 2020-2022, which have no capacity).
        import pyarrow as pa
        return pd.DataFrame({c: pd.Series(dtype=pd.ArrowDtype(pa.date32()) if c == "delivery_month" else t)
                             for c, t in cols.items()})
    df = pd.concat(parts, ignore_index=True)
    if table == "by_technology":
        df["suspect"] = _suspect(df)
    return df[list(cols)].astype(cols)


def fetch(start: dt.datetime, end: dt.datetime) -> dict[str, pd.DataFrame]:
    now = dt.datetime.now(UTC)
    files = Files()
    parts: dict[str, list] = {t: [] for t in COLUMNS}
    for y, m in months(start, end, now):
        chosen = choose(files, y, m)
        if NATIONAL not in chosen and month_bounds(y, m)[1] < now - LATE:
            raise RuntimeError(f"no file for {y}-{m:02d}, a month that ended more than {LATE.days} days ago")
        for t, p in month_rows(chosen, y, m).items():
            parts[t] += p
    out = {t: _frame(t, p) for t, p in parts.items()}
    for t in ("by_technology", "pv_by_canton"):  # the server cuts to the window too; this keeps the frames small
        df = out[t]
        out[t] = df[(df["delivery_start"] >= start) & (df["delivery_start"] < end)].reset_index(drop=True)
    return out
