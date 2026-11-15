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

from . import checks, engine, state, storage
from .catalog import DELIVERY_FIELD, VERSION_FIELD, VERSIONS_SUFFIX, Dataset, Table, category_values
from .config import Config
from .engine import QueryResult, iso_duration
from .storage import ident

CONVENTIONS = ("Timestamps are UTC. delivery_start is the start of the delivery interval; intervals are "
               "half-open: [delivery_start, delivery_start + resolution). To group by local day, convert "
               "first, e.g. date_trunc('day', delivery_start AT TIME ZONE 'Europe/Zurich').")
CONVENTIONS_INSTANTS = (" A table with valid_at instead of delivery_start holds values at an instant (e.g. cloud "
                        "cover at 12:00), not over an interval: resolution doesn't apply. To match an hourly "
                        "interval, choose the instant (its start, its end, or the mean of both) and say which.")
APPEND_ONLY = ("append-only: every version of each row is kept. <table> shows the latest version of each row; "
               "<table>_versions shows every version, with fetched_at: the time of the first fetch that saw that "
               "version (a later fetch that got the same values adds nothing), and superseded_at: the fetched_at "
               "of the next version, null on the latest. `adele query --as-of <time>` shows "
               "the tables as adele held them at that time.")
BACKFILLED = "rows fetched before were backfilled: their fetched_at is the time of the backfill, not of the publication"


def versions_since_line(st: dict) -> str:
    since = st.get("versions_since")
    return f"{ts(since)} ({BACKFILLED})" if since else "not yet: no scheduled run so far, as_of is refused"


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
        if t.is_instant:
            periods = []  # values at instants: no resolution
        elif "resolution" in t.field_names and stats.rows:
            periods = resolution_periods(con, data_dir, t)
        else:
            periods = [{"series": None, "resolution": r["value"], "first": r["from"], "last": None}
                       for r in declared_resolution]
    finally:
        con.close()
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = TableFacts(stats, periods)
    return _cache[key]


_window_cache: dict[tuple, tuple] = {}


def window_range(data_dir: Path, t: Table, column: str) -> tuple:
    """(first, last, distinct values) of the window column, when it isn't delivery_start (forecasts)."""
    files = storage.partitions(data_dir, t)
    key = (t.sql_name, column, tuple((p.name, p.stat().st_mtime_ns) for p in files))
    if key not in _window_cache:
        con = storage.connect()
        try:
            _window_cache.clear() if len(_window_cache) > 256 else None
            _window_cache[key] = con.execute(
                f"SELECT min({ident(column)}), max({ident(column)}), count(DISTINCT {ident(column)}) "
                f"FROM ({storage.select_sql(data_dir, t)})").fetchone()
        finally:
            con.close()
    return _window_cache[key]


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
            res |= {p["resolution"] for p in f.periods if p["resolution"]} | ({"instants"} if t.is_instant else set())
            if f.stats.first:
                cov.append(window_range(cfg.data_dir, t, ds.window)[:2] if ds.window != DELIVERY_FIELD
                           else (f.stats.first, f.stats.last))
        coverage = f"{ts(min(c[0] for c in cov))} .. {ts(max(c[1] for c in cov))}" if cov else "no data"
        if cov and ds.window != DELIVERY_FIELD:
            coverage = f"{ds.window} {coverage}"
        lines.append(f"{ds.id} | {ds.title} | {', '.join(sorted(res)) or '?'} | {coverage} | {st.get('status')}")
    return "\n".join(lines) + "\n"


# --- describe -------------------------------------------------------------------------------

class _CardDumper(yaml.SafeDumper):
    pass


def _str_repr(dumper, data):
    """SQL and CSV as literal blocks; long text folded (no quotes, no escapes); short text with '
    in double quotes, so YAML doesn't double the '."""
    if "\n" in data.strip():
        return dumper.represent_scalar("tag:yaml.org,2002:str", data.rstrip() + "\n", style="|")
    if len(data) > 80:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=">")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"' if "'" in data else None)


_CardDumper.add_representer(str, _str_repr)



def describe_dict(cfg: Config, ds: Dataset) -> dict:
    st = state.load(cfg.data_dir, ds.id)
    card: dict = {"id": ds.id, "title": ds.title}
    if ds.descriptor.get("description"):
        card["description"] = ds.descriptor["description"].strip()
    lic = ds.descriptor.get("licenses")
    titles = [(lc.get("title") or lc.get("name") or lc.get("path", "?")).strip() for lc in lic or []]
    card["license"] = (titles[0] if len(titles) == 1 else titles) if titles else "not declared"
    card["status"] = st.get("status")
    if st.get("problems"):
        card["problems"] = st["problems"]
    eta = state.next_fetch_eta(st, ds.refresh.every)
    pieces = f", in pieces of {iso_duration(ds.refresh.max_window)}" if ds.refresh.max_window else ""
    card["freshness"] = {
        "last_fetched_at": ts(st.get("last_fetched_at")),
        "last_changed_at": ts(st.get("last_changed_at")),
        "next_fetch_eta": ts(eta) if eta else "on the next scheduled run",
        "refresh": f"every {iso_duration(ds.refresh.every)}, window on {ds.window} [last scheduled run - "
                   f"{iso_duration(ds.refresh.lookback)}, now + {iso_duration(ds.refresh.horizon)}){pieces}",
    }
    card["revisions"] = {"overwrite": "only the latest value of each row is kept",
                         "none": "rows never change once stored (each is fetched once)",
                         "append-only": APPEND_ONLY}.get(ds.revisions, ds.revisions)
    if ds.revisions == "append-only":
        card["versions_since"] = versions_since_line(st)
    if ds.checks:
        card["published_figures"] = published_figures_line(ds, st)
    card["conventions"] = CONVENTIONS + (CONVENTIONS_INSTANTS if any(t.is_instant for t in ds.tables.values()) else "")
    if ds.warnings:
        card["warnings"] = ds.warnings
    tables = []
    con = storage.connect()
    try:
        for t in ds.tables.values():
            facts = table_facts(cfg.data_dir, t, ds.resolution)
            entry: dict = {"table": t.sql_name, "grain": f"one row per ({', '.join(t.primary_key)})",
                           "rows": facts.stats.rows}
            if t.versioned:
                entry["versions"] = (f"{facts.stats.versions} rows in {t.sql_name}{VERSIONS_SUFFIX}: one per version, "
                                     f"key ({', '.join(t.primary_key)}, {VERSION_FIELD})")
            if t.description:
                entry["description"] = t.description.strip()
            what = "first and last valid_at" if t.is_instant else "first and last interval start"
            entry["coverage"] = (f"{ts(facts.stats.first)} .. {ts(facts.stats.last)} ({what})"
                                 if facts.stats.first else "no data")
            if ds.window != DELIVERY_FIELD and facts.stats.rows:
                lo, hi, n = window_range(cfg.data_dir, t, ds.window)
                entry[f"{ds.window} coverage"] = f"{ts(lo)} .. {ts(hi)} ({n} distinct values)"
            entry["resolution"] = "none: values at instants (valid_at)" if t.is_instant else [
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
                                  f"USING SAMPLE reservoir(5 ROWS) REPEATABLE (42) ORDER BY {ident(t.time_field)}")
                cols = [d[0] for d in cur.description]
                entry["sample_rows"] = to_csv(cols, [[engine.to_json(v) for v in r] for r in cur.fetchall()])
            tables.append(entry)
    finally:
        con.close()
    card["tables"] = tables
    if ds.examples:
        card["examples"] = [example_entry(ex, st) for ex in ds.examples]
    return card


def example_entry(ex: dict, st: dict) -> dict:
    """An example of the card. One that names a check shows the figure that its SQL reproduces."""
    entry = {"question": ex["question"], "sql": ex["sql"].strip() + "\n"}
    if ex.get("check"):
        differs = ", which this data does not reproduce now" if ex["check"] in failing_checks(st) else ""
        entry["published_figure"] = f"{ex['expected']:g} ({ex['source']}){differs}"
    else:
        entry["verified_at"] = str(ex["verified_at"]) if ex.get("verified_at") else "not verified yet"
    return entry


def failing_checks(st: dict) -> list[str]:
    pre = checks.CHECK_PREFIX
    return [p[len(pre):].split()[0].rstrip(":") for p in st.get("problems", []) if p.startswith(pre)]


def published_figures_line(ds: Dataset, st: dict) -> str:
    """One line on checks.yaml: how many published figures the data reproduces (not the list)."""
    sources = list(dict.fromkeys(c["source"].split(",")[0].strip() for c in ds.checks))
    head = f"{len(ds.checks)} figures published by {', '.join(sources)} are recomputed from this data after each fetch"
    ran = st.get("published_checks") or {}
    if ran.get("count") != len(ds.checks):
        return head + ": not run yet"
    bad = failing_checks(st)
    return head + (f": {len(bad)} differ ({', '.join(bad)})" if bad else ": all match")


def render_describe(cfg: Config, ds: Dataset) -> str:
    return yaml.dump(describe_dict(cfg, ds), Dumper=_CardDumper, sort_keys=False, allow_unicode=True, width=100)


def merged_descriptor(cfg: Config, ds: Dataset) -> dict:
    """The authored datapackage plus the computed fields (SPEC.md, Catalog)."""
    d = copy.deepcopy(ds.descriptor)
    st = state.load(cfg.data_dir, ds.id)
    computed: dict = {"status": st.get("status"), "problems": st.get("problems", []),
                      "last_fetched_at": ts(st.get("last_fetched_at"), False),
                      "last_changed_at": ts(st.get("last_changed_at"), False)}
    if ds.checks:
        computed["published_checks"] = {"count": len(ds.checks), "failing": failing_checks(st),
                                        "run_at": (st.get("published_checks") or {}).get("at")}
    eta = state.next_fetch_eta(st, ds.refresh.every)
    computed["next_fetch_eta"] = ts(eta, False) if eta else None
    if ds.revisions == "append-only":
        computed["versions_since"] = ts(st.get("versions_since"), False)
    tables = {}
    for res in d.get("resources", []):
        t = ds.tables[res["name"]]
        facts = table_facts(cfg.data_dir, t, ds.resolution)
        for f in res["schema"]["fields"]:
            f["duckdb_type"] = facts.stats.duckdb_types.get(f["name"])
        tables[t.name] = {"rows": facts.stats.rows, "coverage": [ts(facts.stats.first, False), ts(facts.stats.last, False)],
                          "resolution_periods": [{**p, "first": ts(p["first"], False) if isinstance(p["first"], dt.datetime)
                                                  else str(p["first"]), "last": ts(p["last"], False)} for p in facts.periods]}
        if t.versioned:
            tables[t.name]["versions"] = facts.stats.versions
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


def query_footer(cfg: Config, catalog: dict[str, Dataset], datasets: list[str], versions: list[str] = (),
                 as_of: dt.datetime | None = None) -> str:
    """Per dataset read: units, resolution, status, warnings. A query with as_of, or on a view of
    every version, also gets the time since when the dataset keeps versions (D30)."""
    lines = []
    for ds_id in datasets:
        ds = catalog[ds_id]
        st = state.load(cfg.data_dir, ds.id)
        units = ", ".join(dict.fromkeys(f"{k.split('.', 1)[1]} {v}" for k, v in ds.units().items())) or "none declared"
        many = len(ds.tables) > 1
        res = "; ".join((f"{t.name} " if many else "") + ("instants (valid_at)" if t.is_instant else
                        resolution_summary(table_facts(cfg.data_dir, t, ds.resolution).periods))
                        for t in ds.tables.values())
        lines.append(f"-- {ds.id}: units: {units}. resolution: {res}. status {st.get('status')}, "
                     f"last fetched {ts(st.get('last_fetched_at')) or 'never'}.")
        if ds.revisions == "append-only" and (as_of or ds.id in versions):
            head = f"as of {ts(as_of, False)}: each row as adele held it then. " if as_of else ""
            lines.append(f"-- {ds.id}: {head}versions since {versions_since_line(st)}.")
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
