"""HTTP API. Every endpoint except /health needs `Authorization: Bearer <API key>`.

GET  /datasets                          list (text)
GET  /datasets/{id}                     describe card (text, YAML)
GET  /datasets/{id}/datapackage.json    authored descriptor plus computed fields (JSON)
POST /query  {"sql": "..."}             JSON (columns, types, rows, total, truncated, footer, text);
                                        ?format=text returns only the text. Optional "as_of": an ISO
                                        timestamp (UTC if no offset): the tables of append-only
                                        datasets as adele held them then (D30)
"""
from __future__ import annotations

import difflib
import hmac
import json
import threading
import time

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import engine, render, state
from .catalog import Dataset
from .config import Config

_log_lock = threading.Lock()


def create_app(cfg: Config, catalog: dict[str, Dataset]) -> FastAPI:
    app = FastAPI(title="adele", docs_url=None, redoc_url=None)

    def key_name(request: Request) -> str:
        header = request.headers.get("authorization", "")
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        for name, key in cfg.keys.items():
            if token and hmac.compare_digest(token.encode(), key.encode()):
                return name
        raise HTTPException(401, "missing or unknown API key: send 'Authorization: Bearer <key>' "
                                 "(the CLI reads ADELE_API_KEY)")

    def dataset(ds_id: str) -> Dataset:
        if ds_id in catalog:
            return catalog[ds_id]
        near = difflib.get_close_matches(ds_id, list(catalog), n=3)
        hint = f" Did you mean {', '.join(near)}?" if near else ""
        raise HTTPException(404, f"unknown dataset {ds_id!r}.{hint} Run `adele list`.")

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return PlainTextResponse(f"error: {exc.detail}\n", status_code=exc.status_code)

    @app.get("/health")
    def health():
        return {"ok": True, "datasets": {ds_id: state.load(cfg.data_dir, ds_id).get("status") for ds_id in catalog}}

    @app.get("/datasets", response_class=PlainTextResponse)
    def list_datasets(who: str = Depends(key_name)):
        return render.render_list(cfg, catalog)

    @app.get("/datasets/{ds_id}", response_class=PlainTextResponse)
    def describe(ds_id: str, who: str = Depends(key_name)):
        return render.render_describe(cfg, dataset(ds_id))

    @app.get("/datasets/{ds_id}/datapackage.json")
    def datapackage(ds_id: str, who: str = Depends(key_name)):
        return render.merged_descriptor(cfg, dataset(ds_id))

    @app.post("/query")
    def query(sql: str = Body(..., embed=True), as_of: str | None = Body(None, embed=True), format: str = "json",
              who: str = Depends(key_name)):
        t0 = time.monotonic()
        entry = {"ts": state.now().isoformat(), "key": who, "sql": sql}
        if as_of is not None:
            entry["as_of"] = as_of
        try:
            when = engine.parse_as_of(as_of) if as_of is not None else None
            res = engine.run(catalog, cfg.data_dir, cfg.query, sql, as_of=when)
        except engine.QueryError as e:
            entry.update(duration_ms=int((time.monotonic() - t0) * 1000), error=str(e).splitlines()[0])
            _log(cfg, entry)
            msg = f"error: {e}\n"
            if format == "text":
                return PlainTextResponse(msg, status_code=400)
            return JSONResponse({"error": str(e)}, status_code=400)
        footer = render.query_footer(cfg, catalog, res.datasets, res.versions, res.as_of)
        text = render.render_query(res, footer)
        entry.update(duration_ms=int((time.monotonic() - t0) * 1000), rows=len(res.rows), total=res.total,
                     datasets=res.datasets)
        _log(cfg, entry)
        if format == "text":
            return PlainTextResponse(text)
        return {"columns": res.columns, "types": res.types, "rows": res.rows, "total": res.total,
                "truncated": res.truncated, "datasets": res.datasets, "footer": footer, "text": text}

    return app


def _log(cfg: Config, entry: dict) -> None:
    """One line per query: key name, SQL, duration, rows (SPEC.md, Security)."""
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    with _log_lock, open(cfg.log_dir / "queries.jsonl", "a") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")
