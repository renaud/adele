"""Extract the station tables of MeteoSwiss's monthly climate bulletins (Klimabulletin) as figures.

From May 2025 the bulletins give three tables as text: monthly mean temperature (Tabelle 1),
precipitation (Tabelle 2) and sunshine duration (Tabelle 3) at selected stations, to 0.1. Older
bulletins print the table as an image: those figures are typed by hand in
qa/published_figures_meteoswiss_typed.csv. Text of a record ("Airolo 7.4 mm (bisheriger
Rekord ...)") is not parsed here.

Usage: python -I klimabulletin_figures.py <folder of klimabulletin_YYYY-MM.pdf> > figures.csv
Needs pdftotext (poppler). Writes CSV: period (YYYY-MM), kind, station_name, height, value, file.
"""
import csv
import re
import subprocess
import sys
from pathlib import Path

ROW = re.compile(r"^\s{2,}(\S.*?\S)\s{2,}(\d{3,4})\s+(-?\d+\.\d)\s+(-?\d+(?:\.\d)?)\s+([+-]?\d+(?:\.\d)?)\s*$")


def kind_of(header: str) -> str | None:
    if "Monatsmittel" in header and "[°C]" in header:
        return "temperature_mean_c"
    if "Monatssumme" in header and "[mm]" in header:
        return "precipitation_mm"
    if "Monatssumme" in header and "[h]" in header:
        return "sunshine_h"
    return None


def main() -> None:
    out = csv.writer(sys.stdout)
    out.writerow(["period", "kind", "station_name", "height", "value", "file"])
    for pdf in sorted(Path(sys.argv[1]).glob("klimabulletin_20??-??.pdf")):
        month = pdf.stem.split("_")[1]
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True,
                              check=True).stdout
        kind, header = None, ""
        for line in text.splitlines():
            if re.match(r"^\s+Station\s{2,}Höhe", line):
                header, kind = line, None
                continue
            if header and kind is None:
                header += " " + line  # the units of the header sit on the next line
                kind = kind_of(header)
                continue
            m = ROW.match(line)
            if kind and m:
                out.writerow([month, kind, m.group(1), m.group(2), m.group(3), pdf.name])
            elif kind and not line.strip():
                kind, header = None, ""


if __name__ == "__main__":
    main()
