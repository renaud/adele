"""The catalog: one folder per dataset, with `datapackage.yaml` and `fetch.py`, and optionally
`checks.yaml` (published figures that the data must reproduce).

The server reads the folders listed in its config (`datasets_dirs`): an entry that holds a
datapackage.yaml is one dataset (e.g. the checkout of a dataset's own repository), any other
entry is a folder of dataset folders. It loads and validates every descriptor at startup and
refuses to start on an error (SPEC.md, Catalog). Table names are `<dataset>.<table>` (D8).
"""
from __future__ import annotations

import ast
import copy
import datetime as dt
import importlib.util
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_SCHEMAS = {"main", "temp", "system", "memory", "information_schema", "pg_catalog"}
DELIVERY_FIELD = "delivery_start"  # UTC start of the interval that a value covers [start, start + resolution)
INSTANT_FIELD = "valid_at"  # UTC instant that a value refers to (e.g. cloud cover at 12:00); no resolution
FORMATS = {1}  # adele.format_version: the version of the descriptor format that this server reads
SECRET_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
# overwrite: the latest fetch wins on the key. none: stored rows never change (forecast runs);
# the server fetches only the parts of a window that hold no stored rows. append-only: POC 2.
REVISION_POLICIES = {"overwrite", "none"}
PARTITIONS = {"month", "day"}  # adele.partition: one Parquet file per month or per day of the window column
REFRESH_KEYS = ("every", "lookback", "horizon", "max_window", "timeout")  # adele.refresh: any other key is refused

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
    max_window: dt.timedelta | None = None  # optional: a longer scheduled window is fetched in pieces of this length
    timeout: dt.timedelta | None = None  # optional: the time limit of one call of fetch.py, if under the server's


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

    @property
    def time_field(self) -> str:
        """delivery_start (values over intervals) or valid_at (values at instants)."""
        return DELIVERY_FIELD if DELIVERY_FIELD in self.field_names else INSTANT_FIELD

    @property
    def is_instant(self) -> bool:
        return self.time_field == INSTANT_FIELD

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
    fetch: Callable[..., Any] | None  # None when fetch.py declares its own dependencies (run by uv)
    checks: list[dict] = field(default_factory=list)  # from checks.yaml
    script_metadata: dict | None = None  # PEP 723 block of fetch.py: run with `uv run --script`

    @property
    def adele(self) -> dict:
        return self.descriptor.get("adele", {})

    @property
    def window(self) -> str:
        """The time column of the fetch window, of the [start, end) filter and of the month partitions."""
        return self.adele.get("window", DELIVERY_FIELD)

    @property
    def secrets(self) -> list[str]:
        """The environment variables (source credentials) that fetch() gets; no other secret."""
        return list(self.adele.get("secrets", []))

    @property
    def partition(self) -> str:
        """One Parquet file per `month` (default) or per `day` (UTC) of the window column."""
        return self.adele.get("partition", "month")

    @property
    def title(self) -> str:
        return self.descriptor.get("title", self.id)

    @property
    def warnings(self) -> list[str]:
        return list(self.adele.get("warnings", []))

    @property
    def examples(self) -> list[dict]:
        """The examples, an example that names a check replaced by the check's question, sql,
        expected value and source (D31)."""
        by_name = {c["name"]: c for c in self.checks}
        out = []
        for ex in self.adele.get("examples", []):
            if ex.get("check"):
                c = by_name[ex["check"]]
                out.append({"check": c["name"], "question": c["question"], "sql": c["sql"],
                            "expected": c["expected"], "source": c["source"]})
            else:
                out.append(dict(ex))
        return out

    @property
    def resolution(self) -> list[dict]:
        return list(self.adele.get("resolution", []))

    def units(self) -> dict[str, str]:
        """`table.field` --> unit, for the fields that declare one."""
        return {f"{t.name}.{f['name']}": f["unit"] for t in self.tables.values() for f in t.fields if f.get("unit")}


def load_catalog(dirs: Path | list[Path]) -> dict[str, Dataset]:
    """Every dataset of the listed folders, or CatalogError if one of them has an error (strict:
    `validate` and `serve`)."""
    catalog, errors = scan_catalog(dirs)
    if errors:
        raise CatalogError("invalid catalog:\n" + "\n".join(f"  - {e}" for e in errors))
    return catalog


def scan_catalog(dirs: Path | list[Path]) -> tuple[dict[str, Dataset], list[str]]:
    """The valid datasets of the listed folders, and one message per error (tolerant: `fetch`).

    A folder with a datapackage.yaml is one dataset, another folder holds dataset folders. A
    dataset with an invalid descriptor is left out and its message starts with the name of its
    folder. Two datasets with the same id are an error: the first one is kept.
    """
    catalog, errors, origin = {}, [], {}
    for entry in [dirs] if isinstance(dirs, Path) else list(dirs):
        if not entry.is_dir():
            errors.append(f"datasets folder not found: {entry}")
            continue
        if (entry / "datapackage.yaml").exists():
            folders, single = [entry], True
        else:
            folders = sorted(p for p in entry.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))
            single = False
        for folder in folders:
            try:
                ds = load_dataset(folder, check_folder_name=not single)
            except CatalogError as e:
                errors.append(f"{folder.name}: {e}")
                continue
            except Exception as e:  # noqa: BLE001 - a descriptor that can't be read at all is one invalid dataset
                errors.append(f"{folder.name}: {type(e).__name__}: {e}")
                continue
            if ds.id in catalog:
                errors.append(f"dataset {ds.id!r} is defined twice: {origin[ds.id]} and {folder}")
                continue
            catalog[ds.id], origin[ds.id] = ds, folder
    return catalog, errors


def refresh_every(dirs: Path | list[Path], ds_id: str) -> dt.timedelta | None:
    """adele.refresh.every of one dataset, read from its descriptor alone, without validation.

    For `fetch <id> --if-due`, which a timer runs every minute: to learn that nothing is due,
    it must not load and validate the whole catalog. The descriptor is found as scan_catalog
    finds it: `<entry>/<id>/datapackage.yaml`, or an entry that is one dataset with that name.
    None when it is not found or can't be read: the caller then takes the full path, which
    reports the error.
    """
    if not NAME_RE.match(ds_id):
        return None
    for entry in [dirs] if isinstance(dirs, Path) else list(dirs):
        path = entry / "datapackage.yaml"
        if not path.exists():
            path = entry / ds_id / "datapackage.yaml"
        try:
            descriptor = yaml.load(path.read_text(), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
            if descriptor["name"] == ds_id:
                return parse_duration(descriptor["adele"]["refresh"]["every"]) or None
        except Exception:  # noqa: BLE001 - not there, not readable, or another dataset: look further
            continue
    return None


def load_dataset(folder: Path, check_folder_name: bool = True) -> Dataset:
    desc_path = folder / "datapackage.yaml"
    if not desc_path.exists():
        raise CatalogError("missing datapackage.yaml")
    try:
        descriptor = yaml.safe_load(desc_path.read_text())
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise CatalogError(f"datapackage.yaml is not valid YAML: {e}") from None
    if not isinstance(descriptor, dict):
        raise CatalogError("datapackage.yaml is not a mapping")
    errors: list[str] = []
    ds_id = descriptor.get("name")
    if check_folder_name and ds_id != folder.name:
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
        times = [n for n in (DELIVERY_FIELD, INSTANT_FIELD) if n in names]
        if len(times) != 1:
            errors.append(f"{tname}: every table needs one time field: {DELIVERY_FIELD!r} (the start of the "
                          f"interval that a value covers) or {INSTANT_FIELD!r} (the instant that a value refers to)")
        elif next(f for f in fields if f.get("name") == times[0]).get("type") != "datetime":
            errors.append(f"{tname}: {times[0]!r} must have type datetime")
        tables[tname] = Table(ds_id, tname, fields, pk, res.get("description"))
    if not tables:
        errors.append("no resources")

    adele = descriptor.get("adele") or {}
    refresh = None
    r = adele.get("refresh")
    try:
        refresh = Refresh(parse_duration(r["every"]), parse_duration(r["lookback"]), parse_duration(r["horizon"]))
    except (KeyError, TypeError):
        errors.append("adele.refresh needs every, lookback and horizon")
    except ValueError as e:
        errors.append(f"adele.refresh: {e}")
    if isinstance(r, dict):  # a misspelt key (max_windw) must not be ignored
        unknown = sorted(str(k) for k in set(r) - set(REFRESH_KEYS))
        if unknown:
            errors.append(f"adele.refresh: unknown key{'s' if len(unknown) > 1 else ''} {', '.join(unknown)} "
                          f"(allowed: {', '.join(REFRESH_KEYS)})")
    if refresh is not None:
        if not refresh.every:
            errors.append("adele.refresh.every: it must be longer than zero")
        for key in ("max_window", "timeout"):
            if key not in r:
                continue
            try:
                value = parse_duration(r[key])
                if not value:
                    raise ValueError("it must be longer than zero")
                setattr(refresh, key, value)
            except ValueError as e:
                errors.append(f"adele.refresh.{key}: {e}")
    fmt = adele.get("format_version")
    readable = ", ".join(map(str, sorted(FORMATS)))
    if fmt is None:
        errors.append(f"adele.format_version is missing (this server reads version {readable})")
    elif isinstance(fmt, bool) or fmt not in FORMATS:
        errors.append(f"adele.format_version {fmt!r} is unknown (this server reads version {readable})")
    secrets = adele.get("secrets", [])
    if not isinstance(secrets, list) or not all(isinstance(x, str) and SECRET_RE.match(x) for x in secrets):
        errors.append("adele.secrets must be a list of environment variable names (e.g. [ENTSO_TOKEN])")
    revisions = adele.get("revisions")
    if revisions not in REVISION_POLICIES:
        errors.append(f"adele.revisions must be one of {sorted(REVISION_POLICIES)} (append-only: POC 2), got {revisions!r}")
    if adele.get("partition", "month") not in PARTITIONS:
        errors.append(f"adele.partition must be one of {sorted(PARTITIONS)}, got {adele.get('partition')!r}")
    errors += _adele_errors(adele)

    window = adele.get("window", DELIVERY_FIELD)
    for t in tables.values():
        wf = next((f for f in t.fields if f.get("name") == window), None)
        if wf is None or wf.get("type") != "datetime" or window not in t.primary_key:
            errors.append(f"{t.name}: adele.window {window!r} must be a datetime field in the primaryKey")

    fetch, meta = None, None
    fetch_path = folder / "fetch.py"
    if not fetch_path.exists():
        errors.append("missing fetch.py")
    else:
        try:
            meta = script_metadata(fetch_path)
            if meta is None:
                fetch = _load_fetch(ds_id, fetch_path)
            else:  # its dependencies are not installed in the server: check it without importing it
                _check_fetch_source(fetch_path)
        except Exception as e:  # noqa: BLE001 - any import error makes the dataset invalid
            errors.append(f"fetch.py: {type(e).__name__}: {e}")
    checks, check_errors = load_checks(folder / "checks.yaml")
    errors += check_errors
    if not check_errors:
        names = {c["name"] for c in checks}
        for i, ex in enumerate(adele.get("examples", []) or []):
            if isinstance(ex, dict) and isinstance(ex.get("check"), str) and ex["check"] not in names:
                errors.append(f"adele.examples[{i}]: check {ex['check']!r} is not in checks.yaml")
    if errors:
        raise CatalogError("; ".join(errors))
    return Dataset(ds_id, folder, descriptor, tables, refresh, revisions, fetch, checks, meta)


CHECK_KEYS = ("name", "question", "sql", "expected", "tolerance", "source")


def load_checks(path: Path) -> tuple[list[dict], list[str]]:
    """checks.yaml: published figures that the data must reproduce, run after each fetch.

    Each entry: name, question, sql (one row, one number), expected, tolerance, source.
    """
    if not path.exists():
        return [], []
    try:
        doc = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        return [], [f"checks.yaml: {e}"]
    if not isinstance(doc, dict) or not isinstance(doc.get("checks"), list):
        return [], ["checks.yaml must be a mapping with a list `checks`"]
    errors, names = [], set()
    for i, c in enumerate(doc["checks"]):
        where = f"checks.yaml, entry {i + 1}"
        if not isinstance(c, dict):
            errors.append(f"{where}: not a mapping")
            continue
        where = f"checks.yaml, {c.get('name') or f'entry {i + 1}'}"
        missing = [k for k in CHECK_KEYS if c.get(k) is None or c.get(k) == ""]
        if missing:
            errors.append(f"{where}: missing {missing}")
            continue
        if not isinstance(c["name"], str) or not NAME_RE.match(c["name"]):
            errors.append(f"{where}: name must match {NAME_RE.pattern}")
        elif c["name"] in names:
            errors.append(f"{where}: two checks are named {c['name']!r}")
        names.add(c["name"])
        for k in ("question", "sql", "source"):
            if not isinstance(c[k], str):
                errors.append(f"{where}: {k} must be text")
        for k in ("expected", "tolerance"):
            if isinstance(c[k], bool) or not isinstance(c[k], (int, float)):
                errors.append(f"{where}: {k} must be a number, got {c[k]!r}")
        if isinstance(c["tolerance"], (int, float)) and not isinstance(c["tolerance"], bool) and c["tolerance"] < 0:
            errors.append(f"{where}: tolerance must be >= 0")
        extra = set(c) - set(CHECK_KEYS)
        if extra:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
    return (doc["checks"] if not errors else []), errors


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
    examples = adele.get("examples", []) or []
    if not isinstance(examples, list):
        return errors + ["adele.examples must be a list"]
    if len(examples) > MAX_EXAMPLES:
        errors.append(f"adele.examples: at most {MAX_EXAMPLES} (describe prints them all), got {len(examples)}")
    for i, ex in enumerate(examples):
        if isinstance(ex, dict) and "check" in ex:
            if not isinstance(ex["check"], str) or set(ex) != {"check"}:
                errors.append(f"adele.examples[{i}]: an example that names a check has only `check: <name>` "
                              "(its question and sql come from checks.yaml)")
        elif not isinstance(ex, dict) or not ex.get("question") or not ex.get("sql"):
            errors.append(f"adele.examples[{i}] needs question and sql, or check")
    return errors


MAX_EXAMPLES = 5  # describe prints every example (D31)


_PEP723_RE = re.compile(r"(?m)^# /// script[ \t]*\n((?:^#(?:| .*)\n)+?)^# ///[ \t]*$")


def script_metadata(path: Path) -> dict | None:
    """The inline script metadata of fetch.py (PEP 723), or None if it has none."""
    m = _PEP723_RE.search(path.read_text())
    if not m:
        return None
    toml = "".join(line[2:] if line.startswith("# ") else line[1:] for line in m.group(1).splitlines(keepends=True))
    meta = tomllib.loads(toml)
    deps = meta.get("dependencies", [])
    if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
        raise CatalogError("the script block's dependencies must be a list of strings")
    return meta


def _check_fetch_source(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch"), None)
    if fn is None or len(fn.args.args) < 2:
        raise CatalogError("fetch.py must define fetch(start, end)")


def _load_fetch(ds_id: str, path: Path) -> Callable:
    spec = importlib.util.spec_from_file_location(f"adele_datasets.{ds_id}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, "fetch", None)
    if not callable(fn):
        raise CatalogError("fetch.py must define fetch(start, end)")
    return fn
