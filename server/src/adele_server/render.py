"""What agents read: the `list` lines, the `describe` card, the query text and its footer.

The server renders them, so the CLI and the HTTP fallback print the same text (D6).
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import io
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import engine, state, storage
from .catalog import DELIVERY_FIELD, Dataset, Table, category_values
from .config import Config
from .engine import QueryResult, iso_duration
from .storage import ident

CONVENTIONS = ("Timestamps are UTC. delivery_start is the start of the delivery interval; intervals are "
               "half-open: [delivery_start, delivery_start + resolution). To group by local day, convert "
               "first, e.g. date_trunc('day', delivery_start AT TIME ZONE 'Europe/Zurich').")


def ts(v: dt.datetime | None, minutes: bool = True) -> str | None:
    if v is None:
        return None
    v = v.astimezone(dt.timezone.utc)
    return v.strftime("%Y-%m-%d %H:%MZ" if minutes else "%Y-%m-%d %H:%M:%SZ")


# --- computed facts per table, cached until a partition file changes -------------------------

@dataclass
class TableFacts:
    stats: storage.TableStats
    periods: list[dict]  # resolution periods: {series, resolution, first, last}


_cache: dict[tuple, TableFacts] = {}


def table_facts(data_dir: Path, t: Table, declared_resolution: list[dict]) -> TableFacts:
    files = storage.partitions(data_dir, t)
    key = (t.sql_name, tuple((p.name, p.stat().st_mtime_ns) for p in files))
    if key in _cache:
        return _cache[key]
    con = storage.connect()
    try:
        stats = storage.table_stats(con, data_dir, t)
        periods = resolution_periods(con, data_dir, t) if "resolution" in t.field_names and stats.rows else [
            {"series": None, "resolution": r["value"], "first": r["from"], "last": None} for r in declared_resolution]
    finally:
        con.close()
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = TableFacts(stats, periods)
    return _cache[key]


def resolution_periods(con, data_dir: Path, t: Table) -> list[dict]:
    """Periods of constant resolution per series (the key without delivery_start), from the data.

    A period also ends at a gap: a row that doesn't start where the previous one ended.
    """
    series = [k for k in t.primary_key if k != DELIVERY_FIELD]
    part = ("PARTITION BY " + ", ".join(ident(k) for k in series)) if series else ""
    keys = "".join(f"{ident(k)}, " for k in series)
    d = ident(DELIVERY_FIELD)
    rows = con.execute(f"""
        WITH r AS (
          SELECT {keys} resolution, {d} AS d,
                 CASE WHEN resolution IS DISTINCT FROM lag(resolution) OVER ({part} ORDER BY {d})
                        OR {d} IS DISTINCT FROM lag({d} + resolution) OVER ({part} ORDER BY {d})
                      THEN 1 ELSE 0 END AS chg
          FROM ({storage.select_sql(data_dir, t)})),
        g AS (SELECT *, sum(chg) OVER ({part} ORDER BY d) AS grp FROM r)
        SELECT {keys} resolution, min(d), max(d) FROM g GROUP BY {keys} resolution, grp ORDER BY {keys} min(d)
    """).fetchall()
    out = []
    for r in rows:
        out.append({"series": " ".join(str(x) for x in r[:len(series)]) or None,
                    "resolution": iso_duration(r[-3]) if r[-3] is not None else None,
                    "first": r[-2], "last": r[-1]})
    return out


def resolution_summary(periods: list[dict]) -> str:
    """'CH PT1H, PT15M from 2026-11-03 23:00Z; FR ...'"""
    by_series: dict = {}
    for p in periods:
        by_series.setdefault(p["series"], []).append(p)
    parts = []
    for s, ps in by_series.items():
        items = [ps[0]["resolution"]] + [
            f"{p['resolution']} from {ts(p['first']) if isinstance(p['first'], dt.datetime) else p['first']}"
            for p in ps[1:]]
        parts.append((f"{s} " if s else "") + ", ".join(items))
    return "; ".join(parts) or "not declared"


# --- list -----------------------------------------------------------------------------------

def render_list(cfg: Config, catalog: dict[str, Dataset]) -> str:
    lines = ["id | title | resolution | coverage (UTC, first and last interval start) | status"]
    for ds in catalog.values():
        st = state.load(cfg.data_dir, ds.id)
        res, cov = set(), []
        for t in ds.tables.values():
            f = table_facts(cfg.data_dir, t, ds.resolution)
            res |= {p["resolution"] for p in f.periods if p["resolution"]}
            if f.stats.first:
                cov.append((f.stats.first, f.stats.last))
        coverage = f"{ts(min(c[0] for c in cov))} .. {ts(max(c[1] for c in cov))}" if cov else "no data"
        lines.append(f"{ds.id} | {ds.title} | {', '.join(sorted(res)) or '?'} | {coverage} | {st.get('status')}")
    return "\n".join(lines) + "\n"


# --- describe -------------------------------------------------------------------------------

class _CardDumper(yaml.SafeDumper):
    pass


def _str_repr(dumper, data):
    """SQL and CSV as literal blocks; text with ' in double quotes, so YAML doesn't double the '."""
    if "\n" in data.strip():
        return dumper.represent_scalar("tag:yaml.org,2002:str", data.rstrip() + "\n", style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"' if "'" in data else None)


_CardDumper.add_representer(str, _str_repr)



def describe_dict(cfg: Config, ds: Dataset) -> dict:
    st = state.load(cfg.data_dir, ds.id)
    card: dict = {"id": ds.id, "title": ds.title}
    if ds.descriptor.get("description"):
        card["description"] = ds.descriptor["description"].strip()
    lic = ds.descriptor.get("licenses")
    card["license"] = ", ".join(lc.get("title") or lc.get("name") or lc.get("path", "?") for lc in lic) if lic \
        else "not declared"
    card["status"] = st.get("status")
    if st.get("problems"):
        card["problems"] = st["problems"]
    eta = state.next_fetch_eta(st, ds.refresh.every)
    card["freshness"] = {
        "last_fetched_at": ts(st.get("last_fetched_at")),
        "last_changed_at": ts(st.get("last_changed_at")),
        "next_fetch_eta": ts(eta) if eta else "on the next scheduled run",
        "refresh": f"every {iso_duration(ds.refresh.every)}, window [now - {iso_duration(ds.refresh.lookback)}, "
                   f"now + {iso_duration(ds.refresh.horizon)})",
    }
    card["revisions"] = {"overwrite": "only the latest value of each row is kept"}.get(ds.revisions, ds.revisions)
    card["conventions"] = CONVENTIONS
    if ds.warnings:
        card["warnings"] = ds.warnings
    tables = []
    con = storage.connect()
    try:
        for t in ds.tables.values():
            facts = table_facts(cfg.data_dir, t, ds.resolution)
            entry: dict = {"table": t.sql_name, "grain": f"one row per ({', '.join(t.primary_key)})",
                           "rows": facts.stats.rows}
            if t.description:
                entry["description"] = t.description.strip()
            entry["coverage"] = (f"{ts(facts.stats.first)} .. {ts(facts.stats.last)} (first and last interval start)"
                                 if facts.stats.first else "no data")
            entry["resolution"] = [
                (f"{p['series']}: " if p["series"] else "") + f"{p['resolution']} "
                + (f"{ts(p['first'])} .. {ts(p['last'])}" if isinstance(p["first"], dt.datetime) else f"from {p['first']}")
                for p in facts.periods] or "not declared"
            fields = []
            for f in t.fields:
                fe: dict = {"name": f["name"],
                            "type": f"{f['type']} ({facts.stats.duckdb_types.get(f['name'], '?')})"}
                if f.get("unit"):
                    fe["unit"] = f["unit"]
                if f.get("description"):
                    fe["description"] = f["description"].strip()
                cats = f.get("categories")
                if cats:
                    fe["values"] = ({c["value"]: c.get("label") for c in cats} if isinstance(cats[0], dict)
                                    else list(cats))
                fields.append(fe)
            entry["fields"] = fields
            if facts.stats.rows:
                cur = con.execute(f"SELECT * FROM ({storage.select_sql(cfg.data_dir, t)}) "
                                  f"USING SAMPLE reservoir(5 ROWS) REPEATABLE (42) ORDER BY {ident(DELIVERY_FIELD)}")
                cols = [d[0] for d in cur.description]
                entry["sample_rows"] = to_csv(cols, [[engine.to_json(v) for v in r] for r in cur.fetchall()])
            tables.append(entry)
    finally:
        con.close()
    card["tables"] = tables
    if ds.examples:
        card["examples"] = [
            {"question": ex["question"], "sql": ex["sql"].strip() + "\n",
             "verified_at": str(ex["verified_at"]) if ex.get("verified_at") else "not verified yet"}
            for ex in ds.examples[:3]]
    return card


def render_describe(cfg: Config, ds: Dataset) -> str:
    return yaml.dump(describe_dict(cfg, ds), Dumper=_CardDumper, sort_keys=False, allow_unicode=True, width=100)


def merged_descriptor(cfg: Config, ds: Dataset) -> dict:
    """The authored datapackage plus the computed fields (SPEC.md, Catalog)."""
    d = copy.deepcopy(ds.descriptor)
    st = state.load(cfg.data_dir, ds.id)
    computed: dict = {"status": st.get("status"), "problems": st.get("problems", []),
                      "last_fetched_at": ts(st.get("last_fetched_at"), False),
                      "last_changed_at": ts(st.get("last_changed_at"), False)}
    eta = state.next_fetch_eta(st, ds.refresh.every)
    computed["next_fetch_eta"] = ts(eta, False) if eta else None
    tables = {}
    for res in d.get("resources", []):
        t = ds.tables[res["name"]]
        facts = table_facts(cfg.data_dir, t, ds.resolution)
        for f in res["schema"]["fields"]:
            f["duckdb_type"] = facts.stats.duckdb_types.get(f["name"])
        tables[t.name] = {"rows": facts.stats.rows, "coverage": [ts(facts.stats.first, False), ts(facts.stats.last, False)],
                          "resolution_periods": [{**p, "first": ts(p["first"], False) if isinstance(p["first"], dt.datetime)
                                                  else str(p["first"]), "last": ts(p["last"], False)} for p in facts.periods]}
    computed["tables"] = tables
    d.setdefault("adele", {})["computed"] = computed
    return d


# --- query ----------------------------------------------------------------------------------

def to_csv(columns: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue()


def query_footer(cfg: Config, catalog: dict[str, Dataset], datasets: list[str]) -> str:
    lines = []
    for ds_id in datasets:
        ds = catalog[ds_id]
        st = state.load(cfg.data_dir, ds.id)
        units = ", ".join(f"{k.split('.', 1)[1]} {v}" for k, v in ds.units().items()) or "none declared"
        res = "; ".join(resolution_summary(table_facts(cfg.data_dir, t, ds.resolution).periods)
                        for t in ds.tables.values())
        lines.append(f"-- {ds.id}: units: {units}. resolution: {res}. status {st.get('status')}, "
                     f"last fetched {ts(st.get('last_fetched_at')) or 'never'}.")
        lines += [f"-- warning ({ds.id}): {w}" for w in ds.warnings]
    return "\n".join(lines) + ("\n" if lines else "")


def render_query(result: QueryResult, footer: str) -> str:
    out = to_csv(result.columns, result.rows) if result.columns else ""
    if not result.rows:
        out += "-- (no rows)\n"
    if result.truncated:
        total = f"{result.total:,}" if result.total is not None else "more than " + f"{len(result.rows):,}"
        out += f"-- showing {len(result.rows):,} of {total} rows. Aggregate, or narrow the filter.\n"
    return out + footer
