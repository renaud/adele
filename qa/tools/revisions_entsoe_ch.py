"""Which ENTSO-E series for CH does ENTSO-E revise after publishing them? (WP3, 2026-11-15)

Compares the raw answers that the swissgrid project saved on 2026-10-31
(`swissgrid_project/data/entsoe/raw_nosync/<family>/`) with fresh answers to the same requests,
point by point. The request parameters are those of the project's `fetch_entsoe_ch.py` (FAMILIES);
the file name of each saved answer gives its window. Any ENTSO-E document is parsed the same way:
a time series is identified by its fields outside the periods (mRID left out), a point by its
time (curve types A01 and A03 expanded) and by its text fields; each numeric field of a point is
one value. A value counts if its time is before the old answer's createdDateTime.

Usage: python revisions_entsoe_ch.py [--since YEAR] <raw_nosync folder> <.env with ENTSO_TOKEN> <out folder> [family ...]
(yearly windows of one border take several seconds each: --since 2025 keeps the last two)
The token is read from the file and never printed. Fresh answers are saved in <out folder>.
"""
from __future__ import annotations

import datetime as dt
import gzip
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import requests

API = "https://web-api.tp.entsoe.eu/api"
CH = "10YCH-SWISSGRIDZ"
EIC = {"DE": "10Y1001A1001A83F", "DE_LU": "10Y1001A1001A82H", "FR": "10YFR-RTE------C", "IT": "10YIT-GRTN-----B",
       "AT": "10YAT-APG------L"}
BORDERS = ["DE", "DE_LU", "FR", "IT", "AT"]


def border(doc: str, extra: dict) -> list[tuple[str, dict]]:
    out = []
    for nb in BORDERS:
        out.append((f"{nb}_from_CH", {"documentType": doc, "in_Domain": EIC[nb], "out_Domain": CH, **extra}))
        out.append((f"{nb}_to_CH", {"documentType": doc, "in_Domain": CH, "out_Domain": EIC[nb], **extra}))
    return out


FAMILIES = {  # as in swissgrid_project/code/pv_imbalance/fetch_entsoe_ch.py
    "imbalance_volume": [("A86", {"documentType": "A86", "controlArea_Domain": CH})],
    "imbalance_price": [("A85", {"documentType": "A85", "controlArea_Domain": CH})],
    "activated_price": [("A84", {"documentType": "A84", "processType": "A16", "controlArea_Domain": CH})],
    "generation": [("A75_A16", {"documentType": "A75", "processType": "A16", "in_Domain": CH})],
    "ws_forecast": [(f"A69_{pt}", {"documentType": "A69", "processType": pt, "in_Domain": CH})
                    for pt in ("A01", "A40", "A18")],
    "da_price": [("A44", {"documentType": "A44", "in_Domain": CH, "out_Domain": CH})],
    "installed_capacity": [("A68_A33", {"documentType": "A68", "processType": "A33", "in_Domain": CH})],
    "flows": [(f"A11_{lab}", p) for lab, p in border("A11", {})],
    "scheduled": [(f"A09_{ct}_{lab}", p) for ct in ("A01", "A05")
                  for lab, p in border("A09", {"contract_MarketAgreement.type": ct})],
}
STEP = {"PT1M": 1, "PT15M": 15, "PT30M": 30, "PT60M": 60, "P1D": 1440, "P7D": 10080}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def leaves(el, prefix=""):
    for ch in el:
        name = prefix + local(ch.tag)
        if len(ch):
            yield from leaves(ch, name + "/")
        elif ch.text and ch.text.strip():
            yield name, ch.text.strip()


def number(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def documents(content: bytes) -> list[bytes]:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            return [z.read(n) for n in sorted(z.namelist())]
    if b"Acknowledgement_MarketDocument" in content[:800]:
        return []
    return [content]


def values(content: bytes) -> tuple[dict, list[str], list[str]]:
    """(key --> value), the createdDateTime of each document, the docStatus of each document."""
    out, created, status = {}, [], []
    for doc in documents(content):
        root = ET.fromstring(doc)
        created += [e.text for e in root.iter() if local(e.tag) == "createdDateTime"][:1]
        st = next((e for e in root.iter() if local(e.tag) == "docStatus"), None)
        status.append(next((c.text for c in st), "-") if st is not None else "-")
        for ts in (e for e in root.iter() if local(e.tag) == "TimeSeries"):
            skey = tuple(sorted((k, v) for k, v in leaves(ts) if not k.startswith("Period/") and k != "mRID"))
            curve = dict(skey).get("curveType", "A01")
            for period in (e for e in ts if local(e.tag) == "Period"):
                f = dict(leaves(period))
                start = dt.datetime.fromisoformat(f["timeInterval/start"].replace("Z", "+00:00"))
                end = dt.datetime.fromisoformat(f["timeInterval/end"].replace("Z", "+00:00"))
                if f["resolution"] == "P1Y":  # installed capacity: one point per calendar year
                    n = end.year - start.year
                    at = lambda k, start=start: start.replace(year=start.year + k - 1)  # noqa: E731
                else:
                    step = dt.timedelta(minutes=STEP[f["resolution"]])
                    n = int((end - start) / step)
                    at = lambda k, start=start, step=step: start + (k - 1) * step  # noqa: E731
                pts = []
                for p in (e for e in period if local(e.tag) == "Point"):
                    pf = dict(leaves(p))
                    pos = int(pf.pop("position"))
                    text = tuple(sorted((k, v) for k, v in pf.items() if number(v) is None))
                    nums = {k: number(v) for k, v in pf.items() if number(v) is not None}
                    pts.append((pos, text, nums))
                pts.sort(key=lambda x: x[0])
                for i, (pos, text, nums) in enumerate(pts):
                    last = (pts[i + 1][0] if i + 1 < len(pts) else n + 1) if curve == "A03" else pos + 1
                    for k in range(pos, last):
                        t = at(k)
                        for field, v in nums.items():
                            out[(skey, text, field, t)] = v
    return out, created, status


def window(name: str) -> tuple[dt.datetime, dt.datetime]:
    a, b = re.findall(r"_(\d{12})(?=_|\.)", name)[:2]
    return tuple(dt.datetime.strptime(x, "%Y%m%d%H%M").replace(tzinfo=dt.timezone.utc) for x in (a, b))


def age_bucket(days: float) -> str:
    for lim, lab in ((2, "<2 d"), (7, "2-7 d"), (30, "7-30 d"), (365, "30-365 d")):
        if days < lim:
            return lab
    return ">1 y"


def main() -> None:
    args = sys.argv[1:]
    since = None
    if "--since" in args:  # only the windows that start in that year or later
        i = args.index("--since")
        since = dt.datetime(int(args[i + 1]) - 1, 12, 31, 23, tzinfo=dt.timezone.utc)
        del args[i:i + 2]
    raw, env, out = Path(args[0]), Path(args[1]), Path(args[2])
    fams = args[3:] or list(FAMILIES)
    tok = next(m.group(1) for line in env.read_text().splitlines()
               if (m := re.match(r"^\s*(?:export\s+)?ENTSO_TOKEN\s*=\s*['\"]?([^'\"\s]+)", line)))
    s = requests.Session()
    for fam in fams:
        stats = Counter()
        diffs = defaultdict(list)  # age bucket --> [(label, key, old, new)]
        status_change = Counter()
        for label, params in FAMILIES[fam]:
            for old_path in sorted((raw / fam).glob(f"{label}_[0-9]*")):
                if old_path.name.endswith(".err.txt"):
                    continue
                a, b = window(old_path.name)
                if since is not None and a < since:
                    continue
                content = old_path.read_bytes()
                if old_path.suffix == ".gz":
                    content = gzip.decompress(content)
                for attempt in range(5):
                    try:
                        r = s.get(API, params={"securityToken": tok, **params, "periodStart": f"{a:%Y%m%d%H%M}",
                                               "periodEnd": f"{b:%Y%m%d%H%M}"}, timeout=300)
                    except requests.RequestException as e:  # its message would carry the URL with the token
                        print(f"  {old_path.name}: {type(e).__name__}, retry", flush=True)
                        time.sleep(2 ** (attempt + 1))
                        continue
                    time.sleep(0.2)
                    if r.status_code in (429, 500, 502, 503, 504):
                        time.sleep(2 ** (attempt + 2))
                        continue
                    break
                new = r.content.replace(tok.encode(), b"***")
                (out / fam).mkdir(parents=True, exist_ok=True)
                (out / fam / (old_path.name.split(".")[0] + (".zip" if new[:2] == b"PK" else ".xml.gz"))).write_bytes(
                    new if new[:2] == b"PK" else gzip.compress(new, mtime=0))
                old_v, old_created, old_status = values(content)
                new_v, _, new_status = values(new)
                if sorted(old_status) != sorted(new_status):
                    status_change[(tuple(sorted(Counter(old_status).items())), tuple(sorted(Counter(new_status).items())))] += 1
                cut = min((dt.datetime.fromisoformat(c.replace("Z", "+00:00")) for c in old_created), default=None)
                for key in old_v.keys() | new_v.keys():
                    t = key[3]
                    o, n = old_v.get(key), new_v.get(key)
                    if cut is not None and t >= cut:  # a forecast for an hour still ahead at the old download
                        if o is not None and n is not None:
                            stats["ahead at the old download: equal" if o == n else
                                  "ahead at the old download: different"] += 1
                            if o != n and len(diffs["ahead"]) < 5:
                                diffs["ahead"].append((label, key[2], t, o, n))
                        continue
                    if o is None:
                        stats["only new (before the old download)"] += 1
                        if len(diffs["only new"]) < 5:
                            diffs["only new"].append((label, key[2], t, o, n))
                    elif n is None:
                        stats["only old"] += 1
                        if len(diffs["only old"]) < 5:
                            diffs["only old"].append((label, key[2], t, o, n))
                    elif o == n:
                        stats["equal"] += 1
                    else:
                        stats["different"] += 1
                        bucket = age_bucket((cut - t).total_seconds() / 86400) if cut else "?"
                        stats[f"different, age {bucket}"] += 1
                        if len(diffs[bucket]) < 5:
                            diffs[bucket].append((label, key[2], t, o, n))
        print(f"\n=== {fam}: " + ", ".join(f"{k} {v:,}" for k, v in sorted(stats.items())), flush=True)
        for b, ex in diffs.items():
            for e in ex:
                print(f"   {b}: {e[0]} {e[1]} {e[2]:%Y-%m-%d %H:%M} old {e[3]} new {e[4]}")
        for (o, n), k in status_change.items():
            print(f"   docStatus of {k} answers: old {dict(o)} --> new {dict(n)}")


if __name__ == "__main__":
    main()
