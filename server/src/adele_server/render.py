"""What agents read: the `list` lines, the `describe` card, the query text and its footer.

The server renders them, so the CLI and the HTTP fallback print the same text (D6).
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import io
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import checks, engine, raw, state, storage
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
CONVENTIONS_PERIODS = (" A table with delivery_date, delivery_month or delivery_year holds values over a calendar day, "
                       "month or year in the zone that its card names (timezone), not in UTC; a month and a year are "
                       "stored as their first day. It has no resolution: a local day lasts 23 to 25 hours. To join it "
                       "with a table in UTC, use the expression under `join` of its table.")
CONVENTIONS_WHOLE = (" A table without a time column (e.g. a list of stations) holds what the source delivers now: "
                     "each fetch replaces it whole, and a row that the source drops goes.")


def versions_since_line(st: dict) -> str:
    since = st.get("versions_since")
    return f"{ts(since)} ({BACKFILLED})" if since else "not yet: no scheduled run so far, as_of is refused"


def ts(v: dt.datetime | dt.date | None, minutes: bool = True) -> str | None:
    if v is None:
        return None
    if not isinstance(v, dt.datetime):  # the date of a calendar period (D26)
        return v.isoformat()
    v = v.astimezone(dt.timezone.utc)
    return v.strftime("%Y-%m-%d %H:%MZ" if minutes else "%Y-%m-%d %H:%M:%SZ")


def period_str(v: dt.date | None, period: str) -> str | None:
    """A calendar period as people write it: 2026-03-29, 2026-03 or 2026."""
    return v.strftime({"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}[period]) if v is not None else None


_JOIN_EXAMPLE = {  # a period, and the plain filter on u that covers it padded by a day
    "day": ("2026-03-29", "u >= '2026-03-28' AND u < '2026-03-31'"),
    "month": ("March 2026", "u >= '2026-02-28' AND u < '2026-04-02'"),
    "year": ("2026", "u >= '2025-12-31' AND u < '2027-01-02'"),
}


def join_text(t: Table) -> str:
    """How to match a UTC timestamp to a row of a table by calendar period (D26)."""
    z, c, p = t.timezone, t.time_field, t.period
    period, plain = _JOIN_EXAMPLE[p]
    text = (f"To match a UTC timestamp u of another table (its delivery_start or valid_at) to a row: "
            f"date_trunc('{p}', u AT TIME ZONE '{z}') = {c}. Add a plain filter on u, the period padded by a day "
            f"(for {period}: {plain}), so that DuckDB skips the files outside it.")
    if z != "UTC":
        text += f" Without AT TIME ZONE, the hours between midnight UTC and midnight in {z} go to the wrong {p}."
    return text


# --- computed facts per table ---------------------------------------------------------------
# Computed per partition file, kept in memory until the file changes, joined per table (D37): a
# fetch changes one or two files of a table, and a whole table can take gigabytes.

FACTS_MEMORY, FACTS_TEMP = "500MB", "1GB"  # beside the queries of agents, in the cap of the service (D35)


@dataclass
class TableFacts:
    rows: int
    first: dt.datetime | dt.date | None  # of the time field, as in storage.FileFacts
    last: dt.datetime | dt.date | None
    duckdb_types: dict[str, str]
    versions: int | None  # append-only: every version stored
    changed_at: dt.datetime | None  # a table without a time column: when its file was last written
    window: tuple | None  # (first, last, distinct values) of the window column, when it isn't the time field
    periods: list[dict]  # resolution periods: {series, resolution, first, last}


_facts_lock = threading.Lock()  # one computation at a time: two would use twice the memory for one result
_file_facts: dict[tuple, dict[str, tuple[int, storage.FileFacts]]] = {}  # per table: {file: (mtime, facts)}
_table_facts: dict[tuple, tuple[tuple, TableFacts]] = {}  # per table: (files and mtimes, facts)


def table_facts(data_dir: Path, t: Table) -> TableFacts:
    # not the folder alone: a descriptor can change while the data stays (in the tests)
    table = (str(storage.table_dir(data_dir, t)), t.versioned, t.window, t.time_field, tuple(t.primary_key),
             tuple(t.field_names), repr(t.resolution))
    files = tuple((p, p.stat().st_mtime_ns) for p in storage.partitions(data_dir, t))
    cached = _table_facts.get(table)
    if cached and cached[0] == files:
        return cached[1]
    with _facts_lock:
        cached = _table_facts.get(table)  # another thread may have computed it
        if cached and cached[0] == files:
            return cached[1]
        known = _file_facts.get(table, {})
        con = storage.connect(FACTS_MEMORY, FACTS_TEMP)
        try:
            new = {p.name: known[p.name] if known.get(p.name, (None,))[0] == mtime
                   else (mtime, storage.file_facts(con, data_dir, t, p)) for p, mtime in files}
            types = storage.duckdb_types(con, data_dir, t)
        finally:
            con.close()
        facts = join_facts(t, [f for _, f in new.values()], types, [m for _, m in files])
        _file_facts[table], _table_facts[table] = new, (files, facts)
    return facts


def join_facts(t: Table, files: list[storage.FileFacts], types: dict[str, str], mtimes: list[int]) -> TableFacts:
    firsts = [f.first for f in files if f.first is not None]
    lasts = [f.last for f in files if f.last is not None]
    windows = [f.window for f in files if f.window and f.window[0] is not None]
    if t.time_field != DELIVERY_FIELD:
        periods = []  # instants, calendar periods, no time column: no resolution
    elif "resolution" in t.field_names and any(f.rows for f in files):
        periods = join_periods(files)
    else:
        periods = [{"series": None, "resolution": r["value"], "first": r["from"], "last": None} for r in t.resolution]
    return TableFacts(
        rows=sum(f.rows for f in files),
        first=min(firsts, default=None), last=max(lasts, default=None),
        duckdb_types=types,
        versions=sum(f.versions for f in files) if t.versioned else None,
        changed_at=(dt.datetime.fromtimestamp(max(mtimes) / 1e9, dt.timezone.utc)
                    if mtimes and not t.has_time else None),
        window=((min(w[0] for w in windows), max(w[1] for w in windows), sum(w[2] for w in windows))
                if windows else None),
        periods=periods)


def join_periods(files: list[storage.FileFacts]) -> list[dict]:
    """Periods of constant resolution per series, over all files. A period that reaches the end of
    a file goes on in the next one if the resolution is the same and no interval is missing."""
    by_series: dict[tuple, list[tuple]] = {}
    for f in files:
        for series, *run in f.periods:
            by_series.setdefault(series, []).append(run)
    out = []
    for series in sorted(by_series, key=lambda s: tuple((v is None, v) for v in s)):
        joined: list[list] = []
        for resolution, first, last, end in sorted(by_series[series], key=lambda run: run[1]):
            if joined and joined[-1][0] == resolution and joined[-1][3] == first:
                joined[-1][2:] = [last, end]
            else:
                joined.append([resolution, first, last, end])
        out += [{"series": " ".join(str(x) for x in series) or None,
                 "resolution": iso_duration(resolution) if resolution is not None else None,
                 "first": first, "last": last} for resolution, first, last, _ in joined]
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
        res, cov, whole_rows = set(), {}, 0
        for t in ds.tables.values():
            f = table_facts(cfg.data_dir, t)
            if t.is_instant:
                res.add("instants")
            elif t.period:
                res.add(f"calendar {t.period} ({t.timezone})")
            elif not t.has_time:
                res.add("no time column")
            else:
                res |= {p["resolution"] for p in f.periods if p["resolution"]}
            if not t.has_time:
                whole_rows += f.rows
            elif f.first is not None:  # one coverage per window column (and zone, for a date)
                rng = f.window[:2] if t.window != t.time_field else (f.first, f.last)
                cov.setdefault((t.window, t.period if t.window_is_date else None, t.timezone), []).append(rng)
        parts = []
        for (col, period, tz), rs in cov.items():
            lo, hi = min(r[0] for r in rs), max(r[1] for r in rs)
            parts.append(f"{col} {period_str(lo, period)} .. {period_str(hi, period)} ({tz})" if period else
                         ("" if col == DELIVERY_FIELD else f"{col} ") + f"{ts(lo)} .. {ts(hi)}")
        if not parts and whole_rows:
            parts.append(f"no time column, {whole_rows:,} rows")
        coverage = "; ".join(parts) or "no data"
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
    every = f"every {iso_duration(ds.refresh.every)}"
    card["freshness"] = {
        "last_fetched_at": ts(st.get("last_fetched_at")),
        "last_changed_at": ts(st.get("last_changed_at")),
        "next_fetch_eta": ts(eta) if eta else "on the next scheduled run",
        "refresh": (f"{every}, window on {', '.join(ds.windows)} [last scheduled run - "
                    f"{iso_duration(ds.refresh.lookback)}, now + {iso_duration(ds.refresh.horizon)}){pieces}"
                    if ds.windows else f"{every}, each fetch replaces every table whole"),
    }
    card["revisions"] = {"overwrite": "only the latest value of each row is kept",
                         "none": "rows never change once stored (each is fetched once)",
                         "append-only": APPEND_ONLY}.get(ds.revisions, ds.revisions)
    if ds.revisions == "append-only":
        card["versions_since"] = versions_since_line(st)
        if st.get("imported"):
            first, last = (dt.datetime.fromisoformat(x) for x in st["imported"])
            card["imported"] = (f"the versions fetched from {ts(first)} to {ts(last)} were received by another "
                                "program and imported with their time of reception")
    if ds.keeps_raw:
        s = raw.summary(cfg.data_dir, ds.id)
        card["raw_answers"] = ("each answer of the source is kept as received, on the server only"
                               + (f": from {s['first_day']} to {s['last_day']}" if s else ": none yet"))
    if ds.checks:
        card["published_figures"] = published_figures_line(ds, st)
    shapes = ds.tables.values()
    card["conventions"] = (CONVENTIONS + (CONVENTIONS_INSTANTS if any(t.is_instant for t in shapes) else "")
                           + (CONVENTIONS_PERIODS if any(t.period for t in shapes) else "")
                           + (CONVENTIONS_WHOLE if any(not t.has_time for t in shapes) else ""))
    if ds.warnings:
        card["warnings"] = ds.warnings
    tables = []
    con = storage.connect(FACTS_MEMORY, FACTS_TEMP)
    try:
        for t in ds.tables.values():
            facts = table_facts(cfg.data_dir, t)
            entry: dict = {"table": t.sql_name, "grain": f"one row per ({', '.join(t.primary_key)})",
                           "rows": facts.rows}
            if t.versioned:
                entry["versions"] = (f"{facts.versions} rows in {t.sql_name}{VERSIONS_SUFFIX}: one per version, "
                                     f"key ({', '.join(t.primary_key)}, {VERSION_FIELD})")
            if t.description:
                entry["description"] = t.description.strip()
            if not t.has_time:  # D22: the row count and the time of the last change, in place of a coverage
                entry["coverage"] = (f"no time column: the whole table as the source delivers it; last changed "
                                     f"{ts(facts.changed_at)}" if facts.changed_at else "no data")
            elif t.period:
                entry["coverage"] = (f"{period_str(facts.first, t.period)} .. {period_str(facts.last, t.period)}"
                                     f" (first and last {t.time_field}, in {t.timezone})"
                                     if facts.first else "no data")
            else:
                what = "first and last valid_at" if t.is_instant else "first and last interval start"
                entry["coverage"] = (f"{ts(facts.first)} .. {ts(facts.last)} ({what})"
                                     if facts.first else "no data")
            if t.window and t.window != t.time_field and facts.rows:
                lo, hi, n = facts.window
                entry[f"{t.window} coverage"] = f"{ts(lo)} .. {ts(hi)} ({n} distinct values)"
            if t.is_instant:
                entry["resolution"] = "none: values at instants (valid_at)"
            elif t.period:
                entry["resolution"] = (f"none: one row per calendar {t.period} in {t.timezone} ({t.time_field}"
                                       + (", stored as its first day)" if t.period != "day" else ")"))
                entry["timezone"] = t.timezone
                entry["join"] = join_text(t)
            elif t.has_time:
                entry["resolution"] = [
                    (f"{p['series']}: " if p["series"] else "") + f"{p['resolution']} "
                    + (f"{ts(p['first'])} .. {ts(p['last'])}" if isinstance(p["first"], dt.datetime)
                       else f"from {p['first']}")
                    for p in facts.periods] or "not declared"
            fields = []
            for f in t.fields:
                fe: dict = {"name": f["name"],
                            "type": f"{f['type']} ({facts.duckdb_types.get(f['name'], '?')})"}
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
            if facts.rows:
                order = ", ".join(ident(c) for c in ([t.time_field] if t.has_time else t.primary_key))
                cur = con.execute(f"SELECT * FROM ({storage.select_sql(cfg.data_dir, t)}) "
                                  f"USING SAMPLE reservoir(5 ROWS) REPEATABLE (42) ORDER BY {order}")
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
        facts = table_facts(cfg.data_dir, t)
        for f in res["schema"]["fields"]:
            f["duckdb_type"] = facts.duckdb_types.get(f["name"])
        tables[t.name] = {"rows": facts.rows}
        if t.has_time:
            tables[t.name]["coverage"] = [ts(facts.first, False), ts(facts.last, False)]
        else:
            tables[t.name]["last_changed_at"] = ts(facts.changed_at, False)
        tables[t.name]["resolution_periods"] = [  # empty for instants, calendar periods, no time column
            {**p, "first": ts(p["first"], False) if isinstance(p["first"], dt.datetime) else str(p["first"]),
             "last": ts(p["last"], False)} for p in facts.periods]
        if t.versioned:
            tables[t.name]["versions"] = facts.versions
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
        res = "; ".join((f"{t.name} " if many else "") + table_resolution(cfg.data_dir, t) for t in ds.tables.values())
        lines.append(f"-- {ds.id}: units: {units}. resolution: {res}. status {st.get('status')}, "
                     f"last fetched {ts(st.get('last_fetched_at')) or 'never'}.")
        if ds.revisions == "append-only" and (as_of or ds.id in versions):
            head = f"as of {ts(as_of, False)}: each row as adele held it then. " if as_of else ""
            lines.append(f"-- {ds.id}: {head}versions since {versions_since_line(st)}.")
        lines += [f"-- warning ({ds.id}): {w}" for w in ds.warnings]
    return "\n".join(lines) + ("\n" if lines else "")


def table_resolution(data_dir: Path, t: Table) -> str:
    """The resolution of a table in the footer: periods, instants, a calendar period, or no time column."""
    if t.is_instant:
        return "instants (valid_at)"
    if t.period:
        return f"calendar {t.period} in {t.timezone} ({t.time_field})"
    if not t.has_time:
        return "no time column"
    return resolution_summary(table_facts(data_dir, t).periods)


def render_query(result: QueryResult, footer: str) -> str:
    out = to_csv(result.columns, result.rows) if result.columns else ""
    if not result.rows:
        out += "-- (no rows)\n"
    if result.truncated:
        total = f"{result.total:,}" if result.total is not None else "more than " + f"{len(result.rows):,}"
        out += f"-- showing {len(result.rows):,} of {total} rows. Aggregate, or narrow the filter.\n"
    return out + footer
