"""Checks of pronovo_production from BFE's monthly volumes of the reference market prices (Art. 15 EnFV).

BFE computes each volume from Pronovo's "Lastgangprofile nach Technologien" (the quarterly
definitive files), as net production: -A minus +A (method note, section 3.3,
https://pubdb.bfe.admin.ch/de/publication/download/11467). Usage:

    python qa/tools/rmp_checks_pronovo_production.py ogd60_rmp_monatspreise.csv [first YYYY-MM]

prints the YAML entries of `checks:` for every month and technology of the CSV (from the given
month on), to append to datasets/pronovo_production/checks.yaml. The CSV:
https://www.bfe-ogd.ch/ogd60_rmp_monatspreise.csv
"""
import csv
import datetime as dt
import sys
from zoneinfo import ZoneInfo

ZRH = ZoneInfo("Europe/Zurich")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
TECH = {  # name in the check: (CSV column, technologies of the dataset, words of the question)
    "pv": ("Volume_pv_MWh", ["pv"], "PV"),
    "wind": ("Volume_windenergie_MWh", ["wind"], "wind"),
    "hydro": ("Volume_wasserkraft_MWh",
              ["hydro_wastewater", "hydro_diversion", "hydro_residual_flow", "hydro_run_of_river", "hydro_drinking_water"],
              "hydro without storage and pumped storage (wastewater, diversion, residual-flow, run-of-river and "
              "drinking-water plants)"),
    "biomass": ("Volume_biomasse_MWh", ["biogas", "biomass_other", "wood", "waste_renewable", "sewage_gas"],
                "biomass (biogas, other biomass, wood, the renewable part of waste incineration, sewage gas)"),
}
SOURCE = ("BFE, Referenz-Marktpreise gemäss Art. 15 EnFV, monthly volumes, column {col}, "
          "https://www.bfe-ogd.ch/ogd60_rmp_monatspreise.csv (method: https://pubdb.bfe.admin.ch/de/publication/download/11467, section 3.3)")


def local_midnight(y: int, m: int) -> str:
    """The first instant of a local month, as a TIMESTAMPTZ literal with its offset (+01 or +02)."""
    t = dt.datetime(y, m, 1, tzinfo=ZRH)
    off = int(t.utcoffset().total_seconds() // 3600)
    return f"{y:04d}-{m:02d}-01 00:00:00+{off:02d}"


def main():
    first = sys.argv[2] if len(sys.argv) > 2 else "0000-00"
    with open(sys.argv[1], newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        y, m = int(r["Year"]), int(r["Month"])
        if f"{y:04d}-{m:02d}" < first:
            continue
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        for name, (col, techs, words) in TECH.items():
            where = f"technology = '{techs[0]}'" if len(techs) == 1 else \
                "technology IN (" + ", ".join(f"'{t}'" for t in techs) + ")"
            print(f"""  - name: rmp_{name}_{y}_{m:02d}_mwh
    question: "Net production of {words}, energy delivered minus energy drawn, in {MONTHS[m - 1]} {y} (local month, Europe/Zurich), MWh"
    sql: |
      SELECT sum(production_mwh - coalesce(auxiliary_mwh, 0))
      FROM pronovo_production.by_technology
      WHERE {where}
        AND delivery_start >= TIMESTAMPTZ '{local_midnight(y, m)}'
        AND delivery_start <  TIMESTAMPTZ '{local_midnight(ny, nm)}'
    expected: {int(r[col])}
    tolerance: 0.5
    source: "{SOURCE.format(col=col)}\"""")


if __name__ == "__main__":
    main()
