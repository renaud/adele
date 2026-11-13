"""Reference answers for the QA questions from entsoe-py's pandas client (not through adele)."""
import sys, pathlib
import pandas as pd
from entsoe import EntsoePandasClient
env = pathlib.Path(sys.argv[1])
token = dict(l.split("=", 1) for l in env.read_text().splitlines() if "=" in l)["ENTSO_TOKEN"].strip()
c = EntsoePandasClient(api_key=token, timeout=60)

def get(zone, s, e, tz):
    s, e = pd.Timestamp(s, tz=tz), pd.Timestamp(e, tz=tz)
    x = c.query_day_ahead_prices(zone, start=s, end=e)
    return x[(x.index >= s) & (x.index < e)]

def hours(x):  # duration of each row in hours, from the index spacing (last row: same as previous)
    d = pd.Series(x.index, index=x.index).diff().shift(-1)
    d.iloc[-1] = d.iloc[-2]
    return d.dt.total_seconds() / 3600

def tw(x):
    h = hours(x); return (x * h).sum() / h.sum()

ch24 = get("CH", "2024-01-01", "2025-01-01", "Europe/Zurich"); print("q01 CH 2024 mean", round(ch24.mean(), 2), "n", len(ch24))
de17 = get("DE_AT_LU", "2017-01-01", "2018-01-01", "Europe/Berlin"); print("q02 DE_AT_LU 2017 mean", round(de17.mean(), 2), "n", len(de17))
a = get("DE_AT_LU", "2018-01-01", "2018-10-01", "Europe/Berlin"); b = get("DE_LU", "2018-10-01", "2019-01-01", "Europe/Berlin")
print("q03 DE 2018 mean", round(pd.concat([a, b]).mean(), 2), "n", len(a) + len(b), "parts", round(a.mean(), 2), round(b.mean(), 2))
fr = get("FR", "2025-07-01", "2026-01-01", "Europe/Paris"); print("q04 FR H2 2025 time-weighted", round(tw(fr), 2), "plain", round(fr.mean(), 2), "n", len(fr))
de25 = get("DE_LU", "2025-01-01", "2026-01-01", "Europe/Berlin"); h = hours(de25)
print("q05 DE_LU 2025 negative hours (time)", (h[de25 < 0]).sum(), "rows", len(de25))
fr22 = get("FR", "2022-01-01", "2023-01-01", "Europe/Paris"); d = fr22.groupby(fr22.index.date).mean().sort_values(ascending=False)
print("q06 FR 2022 max day", d.index[0], round(d.iloc[0], 2))
ch26 = get("CH", "2026-03-30", "2026-03-31", "Europe/Zurich"); print("q07 CH 2026-03-30 08:00 local", ch26[ch26.index.hour == 8].round(2).to_dict())
oct = get("CH", "2026-10-25", "2026-10-26", "Europe/Zurich"); print("q08 CH 2026-10-25 intervals", len(oct))
wk = get("CH", "2026-11-01", "2026-11-08", "Europe/Zurich"); print("q09 CH 1-7 Nov 2026 time-weighted", round(tw(wk), 2), "plain", round(wk.mean(), 2))
ch25 = get("CH", "2025-01-01", "2026-01-01", "Europe/Zurich"); fr25 = get("FR", "2025-01-01", "2026-01-01", "Europe/Paris")
fr25h = fr25.resample("h").mean(); j = pd.concat([ch25.resample("h").mean().rename("ch"), fr25h.rename("fr")], axis=1).dropna()
print("q10 CH-FR spread 2025 (hourly means)", round((j.ch - j.fr).mean(), 2), "n", len(j))
