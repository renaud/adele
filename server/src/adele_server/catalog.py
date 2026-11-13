"""The catalog: one folder per dataset in `datasets/`, with `datapackage.yaml` and `fetch.py`.

The server loads and validates every descriptor at startup and refuses to start on an error
(SPEC.md, Catalog). Table names are `<dataset>.<table>` (D8).
"""
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_SCHEMAS = {"main", "temp", "system", "memory", "information_schema", "pg_catalog"}
DELIVERY_FIELD = "delivery_start"  # every table has it: UTC start of the delivery interval
REVISION_POLICIES = {"overwrite"}  # append-only comes with POC 2

# Table Schema type --> the DuckDB type in which the server stores the column.
STORAGE_TYPE = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "number": "DOUBLE",
    "boolean": "BOOLEAN",
    "datetime": "TIMESTAMP WITH TIME ZONE",
    "date": "DATE",
    "time": "TIME",
    "duration": "INTERVAL",
}

_DURATION_RE = re.compile(r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


class CatalogError(Exception):
    pass


def parse_duration(s: str) -> dt.timedelta:
    """ISO 8601 duration without years or months (their length varies): PT15M, PT1H, P1D, P2W."""
    m = _DURATION_RE.match(str(s))
    if not m or s in ("P", "PT"):
        raise ValueError(f"not an ISO 8601 duration of weeks/days/hours/minutes/seconds: {s!r}")
    w, d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=se)


@dataclass
class Refresh:
    every: dt.timedelta
    lookback: dt.timedelta
    horizon: dt.timedelta


@dataclass
class Table:
    dataset_id: str
    name: str
    fields: list[dict]
    primary_key: list[str]
    description: str | None = None

    @property
    def sql_name(self) -> str:
        return f"{self.dataset_id}.{self.name}"

    @property
    def field_names(self) -> list[str]:
        return [f["name"] for f in self.fields]

    def storage_types(self) -> dict[str, str]:
        return {f["name"]: STORAGE_TYPE[f["type"]] for f in self.fields}


@dataclass
class Dataset:
    id: str
    folder: Path
    descriptor: dict  # as authored, plus the computed `path` of each resource
    tables: dict[str, Table]
    refresh: Refresh
    revisions: str
    fetch: Callable[..., Any]

    @property
    def adele(self) -> dict:
        return self.descriptor.get("adele", {})

    @property
    def title(self) -> str:
        return self.descriptor.get("title", self.id)

    @property
    def warnings(self) -> list[str]:
        return list(self.adele.get("warnings", []))

    @property
    def examples(self) -> list[dict]:
        return list(self.adele.get("examples", []))

    @property
    def resolution(self) -> list[dict]:
        return list(self.adele.get("resolution", []))

    def units(self) -> dict[str, str]:
        """`table.field` --> unit, for the fields that declare one."""
        return {f"{t.name}.{f['name']}": f["unit"] for t in self.tables.values() for f in t.fields if f.get("unit")}


def load_catalog(datasets_dir: Path) -> dict[str, Dataset]:
    if not datasets_dir.is_dir():
        raise CatalogError(f"datasets folder not found: {datasets_dir}")
    catalog, errors = {}, []
    for folder in sorted(p for p in datasets_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        try:
            ds = load_dataset(folder)
            catalog[ds.id] = ds
        except CatalogError as e:
            errors.append(f"{folder.name}: {e}")
    if errors:
        raise CatalogError("invalid catalog:\n" + "\n".join(f"  - {e}" for e in errors))
    return catalog


def load_dataset(folder: Path) -> Dataset:
    desc_path = folder / "datapackage.yaml"
    if not desc_path.exists():
        raise CatalogError("missing datapackage.yaml")
    descriptor = yaml.safe_load(desc_path.read_text())
    if not isinstance(descriptor, dict):
        raise CatalogError("datapackage.yaml is not a mapping")
    errors: list[str] = []
    ds_id = descriptor.get("name")
    if ds_id != folder.name:
        errors.append(f"name {ds_id!r} differs from the folder name {folder.name!r}")
    if not isinstance(ds_id, str) or not NAME_RE.match(ds_id):
        raise CatalogError(f"dataset name {ds_id!r} must match {NAME_RE.pattern}")
    if ds_id in RESERVED_SCHEMAS:
        errors.append(f"dataset name {ds_id!r} is reserved by DuckDB")

    descriptor = copy.deepcopy(descriptor)
    for res in descriptor.get("resources", []):
        # Required by the standard; points to where the table is served (SPEC.md, Catalog).
        res.setdefault("path", f"datasets/{ds_id}/tables/{res.get('name')}")
    errors += _frictionless_errors(descriptor)

    tables: dict[str, Table] = {}
    for res in descriptor.get("resources", []):
        tname = res.get("name")
        if not isinstance(tname, str) or not NAME_RE.match(tname):
            errors.append(f"resource name {tname!r} must match {NAME_RE.pattern}")
            continue
        if tname in tables:
            errors.append(f"two resources are named {tname!r}")
        schema = res.get("schema") or {}
        fields = schema.get("fields") or []
        errors += [f"{tname}: {e}" for e in _field_errors(fields)]
        pk = schema.get("primaryKey") or []
        pk = [pk] if isinstance(pk, str) else list(pk)
        if not pk:
            errors.append(f"{tname}: primaryKey is required (it states the grain)")
        names = [f.get("name") for f in fields]
        if DELIVERY_FIELD not in names:
            errors.append(f"{tname}: every table needs a field {DELIVERY_FIELD!r} of type datetime")
        elif next(f for f in fields if f.get("name") == DELIVERY_FIELD).get("type") != "datetime":
            errors.append(f"{tname}: {DELIVERY_FIELD!r} must have type datetime")
        tables[tname] = Table(ds_id, tname, fields, pk, res.get("description"))
    if not tables:
        errors.append("no resources")

    adele = descriptor.get("adele") or {}
    refresh = None
    try:
        r = adele["refresh"]
        refresh = Refresh(parse_duration(r["every"]), parse_duration(r["lookback"]), parse_duration(r["horizon"]))
    except (KeyError, TypeError):
        errors.append("adele.refresh needs every, lookback and horizon")
    except ValueError as e:
        errors.append(f"adele.refresh: {e}")
    revisions = adele.get("revisions")
    if revisions not in REVISION_POLICIES:
        errors.append(f"adele.revisions must be one of {sorted(REVISION_POLICIES)} (append-only: POC 2), got {revisions!r}")
    errors += _adele_errors(adele)

    fetch = None
    fetch_path = folder / "fetch.py"
    if not fetch_path.exists():
        errors.append("missing fetch.py")
    else:
        try:
            fetch = _load_fetch(ds_id, fetch_path)
        except Exception as e:  # noqa: BLE001 - any import error makes the dataset invalid
            errors.append(f"fetch.py: {type(e).__name__}: {e}")
    if errors:
        raise CatalogError("; ".join(errors))
    return Dataset(ds_id, folder, descriptor, tables, refresh, revisions, fetch)


def _frictionless_errors(descriptor: dict) -> list[str]:
    from frictionless import Package

    report = Package.validate_descriptor(copy.deepcopy(descriptor))
    return [] if report.valid else [f"frictionless: {e.message}" for e in report.errors]


def _field_errors(fields: list[dict]) -> list[str]:
    errors = []
    for f in fields:
        name, ftype = f.get("name"), f.get("type", "string")
        f.setdefault("type", ftype)
        if not isinstance(name, str) or not NAME_RE.match(name):
            errors.append(f"field name {name!r} must match {NAME_RE.pattern}")
        if ftype not in STORAGE_TYPE:
            errors.append(f"field {name}: type {ftype!r} not supported (use one of {sorted(STORAGE_TYPE)})")
        if "unit" in f and not isinstance(f["unit"], str):
            errors.append(f"field {name}: unit must be a string")
        if "categories" in f:
            errors += [f"field {name}: {e}" for e in _categories_errors(f["categories"], ftype)]
    return errors


def _categories_errors(cats: Any, ftype: str) -> list[str]:
    """Table Schema v2: an array of unique values, or of objects with a unique `value` (and `label`)."""
    if ftype not in ("string", "integer"):
        return [f"categories are only allowed on string and integer fields, not {ftype}"]
    if not isinstance(cats, list) or not cats:
        return ["categories must be a non-empty list"]
    objects = [isinstance(c, dict) for c in cats]
    if any(objects) and not all(objects):
        return ["categories must be all values or all {value, label} objects, not both"]
    values = [c.get("value") for c in cats] if all(objects) else cats
    if any(v is None for v in values):
        return ["every category object needs a value"]
    errors = []
    if len(set(map(repr, values))) != len(values):
        errors.append("category values must be unique")
    if all(objects):
        labels = [c["label"] for c in cats if "label" in c]
        if any(not isinstance(lb, str) for lb in labels):
            errors.append("category labels must be strings")
        elif len(set(labels)) != len(labels):
            errors.append("category labels must be unique")
    return errors


def category_values(field: dict) -> list | None:
    cats = field.get("categories")
    if not cats:
        return None
    return [c["value"] for c in cats] if isinstance(cats[0], dict) else list(cats)


def _adele_errors(adele: dict) -> list[str]:
    errors = []
    prev = None
    for i, r in enumerate(adele.get("resolution", []) or []):
        try:
            frm = dt.date.fromisoformat(str(r["from"]))
            parse_duration(r["value"])
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"adele.resolution[{i}]: needs from (date) and value (ISO duration): {e}")
            continue
        if prev and frm <= prev:
            errors.append("adele.resolution: periods must be in increasing order of `from`")
        prev = frm
    warnings = adele.get("warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
        errors.append("adele.warnings must be a list of sentences")
    for i, ex in enumerate(adele.get("examples", []) or []):
        if not isinstance(ex, dict) or not ex.get("question") or not ex.get("sql"):
            errors.append(f"adele.examples[{i}] needs question and sql")
    return errors


def _load_fetch(ds_id: str, path: Path) -> Callable:
    spec = importlib.util.spec_from_file_location(f"adele_datasets.{ds_id}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "fetch", None)
    if not callable(fn):
        raise CatalogError("fetch.py must define fetch(start, end)")
    return fn
