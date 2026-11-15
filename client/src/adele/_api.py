"""Calls to the adele server. Standard library only (D2).

Environment: ADELE_URL (default http://127.0.0.1:8000), ADELE_API_KEY.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT_S = 120


class AdeleError(Exception):
    pass


def _request(method: str, path: str, body: dict | None = None) -> tuple[str, bytes]:
    base = os.environ.get("ADELE_URL", DEFAULT_URL).rstrip("/")
    key = os.environ.get("ADELE_API_KEY")
    if not key:
        raise AdeleError("ADELE_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "adele-client/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            msg = json.loads(raw).get("error", raw)
        except ValueError:
            msg = raw
        msg = msg.strip()
        raise AdeleError(msg[7:] if msg.startswith("error: ") else msg) from None
    except urllib.error.URLError as e:
        raise AdeleError(f"cannot reach the adele server at {base} ({e.reason}); check ADELE_URL") from None


def datasets() -> str:
    """One line per dataset: id, title, resolution, coverage, status."""
    return _request("GET", "/datasets")[1].decode()


def describe(dataset_id: str) -> str:
    """The dataset card (YAML): description, grain, fields, coverage, freshness, warnings, examples."""
    return _request("GET", "/datasets/" + urllib.parse.quote(dataset_id, safe=""))[1].decode()


@dataclass
class QueryResult:
    columns: list[str]
    types: list[str]
    rows: list[list]
    total: int | None  # rows before the cap; None if unknown
    truncated: bool
    footer: str
    text: str = field(repr=False)  # what the CLI prints: CSV, the cap note, the footer
    datasets: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


def query(sql: str, as_of: str | None = None) -> QueryResult:
    """Run DuckDB SQL on the server. Tables are named <dataset>.<table>. Results are capped.

    `as_of`: an ISO timestamp (UTC if it has no offset). The tables of append-only datasets then
    show what adele held at that time; a query that reads another dataset is refused.
    """
    body = {"sql": sql} if as_of is None else {"sql": sql, "as_of": as_of}
    payload = json.loads(_request("POST", "/query", body)[1])
    return QueryResult(payload["columns"], payload["types"], payload["rows"], payload["total"],
                       payload["truncated"], payload["footer"], payload["text"], payload.get("datasets", []))
