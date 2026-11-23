"""Calls to the adele server. Standard library only (D2).

Environment: ADELE_URL (default http://127.0.0.1:8000), ADELE_API_KEY.

HTTPS (D35): the server's certificate comes from adele's own authority. Its root certificate is
in this package (adele-ca.pem, a public file) and is trusted beside the authorities of the
system, for the calls of this client only.
"""
from __future__ import annotations

import ipaddress
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT_S = 120
CA_FILE = Path(__file__).with_name("adele-ca.pem")  # absent until the server's authority exists


class AdeleError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib sends the API key along to the address of a redirect, also to http://."""

    def redirect_request(self, *args):
        return None


def _is_loopback(host: str) -> bool:
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_url(base: str) -> None:
    """The API key travels in a header: https, or http to this machine only."""
    try:
        url = urllib.parse.urlsplit(base)
        scheme, host = url.scheme, url.hostname or ""
    except ValueError:
        scheme, host = "", ""
    if not host or not (scheme == "https" or scheme == "http" and _is_loopback(host)):
        raise AdeleError(f"ADELE_URL must start with https:// (http:// only for localhost): {base}")


def _opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    if CA_FILE.exists():
        context.load_verify_locations(cafile=CA_FILE)
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoRedirect)


def _request(method: str, path: str, body: dict | None = None) -> tuple[str, bytes]:
    base = os.environ.get("ADELE_URL", DEFAULT_URL).rstrip("/")
    _check_url(base)
    key = os.environ.get("ADELE_API_KEY")
    if not key:
        raise AdeleError("ADELE_API_KEY is not set")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "adele-client/0.1"})
    try:
        with _opener().open(req, timeout=TIMEOUT_S) as resp:
            return resp.headers.get("content-type", ""), resp.read()
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise AdeleError(f"{base} redirects to {e.headers.get('Location')}; check ADELE_URL") from None
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
