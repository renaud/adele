"""Declared means checked: test what a descriptor states against the stored data.

Run after each fetch. Any problem sets the dataset's status to failing. Besides the descriptor,
`checks.yaml` lists published figures (regulators, papers) that the data must reproduce.
"""
from __future__ import annotations

from pathlib import Path

from . import engine
from .catalog import Dataset, category_values
from .config import QueryLimits
from .storage import connect, ident, partitions, select_sql, table_dir, sql_str


def run_checks(catalog: dict[str, Dataset], ds: Dataset, data_dir: Path, limits: QueryLimits) -> list[str]:
    problems: list[str] = []
    con = connect()
    try:
        for t in ds.tables.values():
            if not partitions(data_dir, t):
                problems.append(f"{t.sql_name}: no data yet")
                continue
            # schema of the stored files (a descriptor change without a refetch shows up here)
            raw = con.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_str(table_dir(data_dir, t) / '*.parquet')})").fetchall()
            stored = {r[0]: r[1] for r in raw}
            for name, want in t.storage_types().items():
                if name not in stored:
                    problems.append(f"{t.sql_name}: column {name} is declared but not stored")
                elif stored[name] != want:
                    problems.append(f"{t.sql_name}: column {name} is stored as {stored[name]}, declared {want}")
            extra = set(stored) - set(t.field_names)
            if extra:
                problems.append(f"{t.sql_name}: stored columns not declared: {sorted(extra)}")
            if any(p.startswith(f"{t.sql_name}: column") or "not declared" in p for p in problems):
                continue
            src = f"({select_sql(data_dir, t)})"
            pk = ", ".join(ident(k) for k in t.primary_key)
            nulls = con.execute(
                f"SELECT count(*) FROM {src} WHERE " + " OR ".join(f"{ident(k)} IS NULL" for k in t.primary_key)
            ).fetchone()[0]
            if nulls:
                problems.append(f"{t.sql_name}: {nulls} rows with a null in the primary key ({pk})")
            dups = con.execute(
                f"SELECT {pk}, count(*) AS n FROM {src} GROUP BY ALL HAVING n > 1 ORDER BY n DESC LIMIT 3"
            ).fetchall()
            if dups:
                problems.append(f"{t.sql_name}: primary key ({pk}) not unique, e.g. {dups}")
            for f in t.fields:
                values = category_values(f)
                if values is None:
                    continue
                bad = con.execute(
                    f"SELECT DISTINCT {ident(f['name'])} FROM {src} "
                    f"WHERE {ident(f['name'])} IS NOT NULL AND NOT list_contains($v, {ident(f['name'])}) LIMIT 10",
                    {"v": values}).fetchall()
                if bad:
                    problems.append(f"{t.sql_name}: {f['name']} holds undeclared values {[b[0] for b in bad]}")
    finally:
        con.close()
    for i, ex in enumerate(ds.examples):
        try:
            res = engine.run(catalog, data_dir, limits, ex["sql"], max_rows=1)
            if not res.rows:
                problems.append(f"example {i + 1} ({ex['question']!r}) returns no rows")
        except engine.QueryError as e:
            problems.append(f"example {i + 1} ({ex['question']!r}) fails: {str(e).splitlines()[0]}")
    for c in ds.checks:
        problem = run_published_check(catalog, data_dir, limits, c)
        if problem:
            problems.append(problem)
    return problems


CHECK_PREFIX = "check "  # problems from checks.yaml start with it (the describe card counts them)


def run_published_check(catalog: dict[str, Dataset], data_dir: Path, limits: QueryLimits, c: dict) -> str | None:
    """None if the query reproduces the published figure within the tolerance, else the problem."""
    name = f"{CHECK_PREFIX}{c['name']}"
    try:
        res = engine.run(catalog, data_dir, limits, c["sql"], max_rows=1)
    except engine.QueryError as e:
        return f"{name} fails: {str(e).splitlines()[0]}"
    if not res.rows or not res.rows[0]:
        return f"{name} returns no row"
    v = res.rows[0][0]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return f"{name} returns {v!r}, not a number"
    if abs(v - c["expected"]) > c["tolerance"] + 1e-9:
        return (f"{name}: got {v:.6g}, published {c['expected']:g} (tolerance {c['tolerance']:g}; "
                f"{c['source'].split(',')[0]})")
    return None
