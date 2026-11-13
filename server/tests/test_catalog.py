"""Startup validation of descriptors (SPEC.md, Catalog; D8)."""
from __future__ import annotations

import pytest
import yaml

from adele_server.catalog import CatalogError, load_catalog, parse_duration


def mutate(env, fn):
    cfg, _, _ = env
    p = cfg.datasets_dir / "test_prices" / "datapackage.yaml"
    d = yaml.safe_load(p.read_text())
    fn(d)
    p.write_text(yaml.safe_dump(d))
    return cfg


def fields(d):
    return d["resources"][0]["schema"]["fields"]


@pytest.mark.parametrize("fn, message", [
    (lambda d: d.update(name="Test-Prices"), "must match"),
    (lambda d: fields(d).pop(1), "delivery_start"),
    (lambda d: fields(d)[0].update(categories=[{"value": "A"}, "B"]), "not both"),
    (lambda d: fields(d)[0].update(categories=["A", "A"]), "unique"),
    (lambda d: fields(d)[3].update(categories=[1.5]), "only allowed on string and integer"),
    (lambda d: fields(d)[3].update(type="money"), "not supported"),
    (lambda d: d["resources"][0]["schema"].update(primaryKey=["nope"]), "frictionless"),
    (lambda d: d["adele"]["refresh"].update(every="P1M"), "ISO 8601"),
    (lambda d: d["adele"].update(revisions="append-only"), "POC 2"),
])
def test_invalid_descriptors_are_refused(env, fn, message):
    cfg = mutate(env, fn)
    with pytest.raises(CatalogError, match=message):
        load_catalog(cfg.datasets_dir)


def test_reserved_schema_name(env):
    cfg, _, _ = env
    folder = cfg.datasets_dir / "test_prices"
    target = cfg.datasets_dir / "main"
    folder.rename(target)
    p = target / "datapackage.yaml"
    p.write_text(p.read_text().replace("name: test_prices", "name: main"))
    with pytest.raises(CatalogError, match="reserved"):
        load_catalog(cfg.datasets_dir)


def test_valid_fixture_and_computed_path(env):
    _, catalog, _ = env
    ds = catalog["test_prices"]
    assert ds.tables["prices"].sql_name == "test_prices.prices"
    assert ds.descriptor["resources"][0]["path"] == "datasets/test_prices/tables/prices"


def test_parse_duration():
    assert parse_duration("PT15M").total_seconds() == 900
    assert parse_duration("P2D").days == 2
    with pytest.raises(ValueError):
        parse_duration("P1Y")
