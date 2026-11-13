"""adele-server: validate | serve | fetch | backfill | check."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from . import config as config_mod
from . import ingest, state
from .catalog import CatalogError, load_catalog

UTC = dt.timezone.utc


def _date(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="adele-server", description=__doc__)
    p.add_argument("--config", help="config file (default: $ADELE_SERVER_CONFIG or ./adele-server.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="load and validate every descriptor")
    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    f = sub.add_parser("fetch", help="fetch the scheduled window [now - lookback, now + horizon)")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("dataset", nargs="?")
    g.add_argument("--due", action="store_true", help="every dataset whose refresh is due (run by cron)")
    f.add_argument("--start", type=_date, help="explicit window start (UTC date or ISO timestamp)")
    f.add_argument("--end", type=_date, help="explicit window end")
    b = sub.add_parser("backfill", help="fetch successive windows, then check")
    b.add_argument("dataset")
    b.add_argument("--start", type=_date, required=True)
    b.add_argument("--end", type=_date, help="default: now + horizon")
    b.add_argument("--step-days", type=int, default=365)
    b.add_argument("--step-hours", type=int, help="window length in hours, instead of --step-days "
                   "(forecasts: one window per run keeps each fetch under the time limit)")
    c = sub.add_parser("check", help="run the checks on the stored data and update the status")
    c.add_argument("dataset")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(args.config)
    try:
        catalog = load_catalog(cfg.datasets_dir)
    except CatalogError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.cmd == "validate":
        for ds in catalog.values():
            print(f"ok  {ds.id}: tables {', '.join(t.sql_name for t in ds.tables.values())}")
        return 0
    if args.cmd == "serve":
        import uvicorn

        from .app import create_app
        # Source credentials are not loaded here: the process that runs agent SQL doesn't need them.
        uvicorn.run(create_app(cfg, catalog), host=args.host, port=args.port, log_level="info")
        return 0

    config_mod.load_env_file(cfg.env_file)
    now = state.now()
    if args.cmd == "fetch":
        if args.due:
            todo = [ds for ds in catalog.values() if ingest.is_due(ds, state.load(cfg.data_dir, ds.id), now)]
        else:
            if args.dataset not in catalog:
                print(f"error: unknown dataset {args.dataset!r}", file=sys.stderr)
                return 2
            todo = [catalog[args.dataset]]
        rc = 0
        for ds in todo:
            start, end = ingest.scheduled_window(ds, now)
            start, end = args.start or start, args.end or end
            try:
                o = ingest.fetch_window(cfg, catalog, ds, start, end)
            except ingest.FetchError as e:
                print(f"skip {ds.id}: {e}", file=sys.stderr)
                continue
            print(f"{ds.id} [{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}) UTC: "
                  f"{'ok' if o.ok else 'FAILED'}, {o.rows} rows, {o.rows_changed} new or changed, "
                  f"{o.months_written} partitions written; status {'failing' if o.problems else 'ok'}")
            for pr in o.problems or []:
                print(f"  problem: {pr}")
            rc = rc or (0 if o.ok else 1)
        return rc
    if args.cmd == "backfill":
        ds = catalog[args.dataset]
        end = args.end or ingest.scheduled_window(ds, now)[1]
        step = dt.timedelta(hours=args.step_hours) if args.step_hours else dt.timedelta(days=args.step_days)
        outs = ingest.backfill(cfg, catalog, ds, args.start, end, step)
        failed = [o for o in outs if not o.ok]
        st = state.load(cfg.data_dir, ds.id)
        print(f"{ds.id}: {len(outs)} windows, {sum(o.rows for o in outs)} rows, {len(failed)} failed; "
              f"status {st['status']}")
        for o in failed:
            print(f"  failed [{o.start:%Y-%m-%d}, {o.end:%Y-%m-%d}): {o.error}")
        for pr in st.get("problems", []):
            print(f"  problem: {pr}")
        return 1 if failed else 0
    if args.cmd == "check":
        problems = ingest.recheck(cfg, catalog, catalog[args.dataset])
        print("ok" if not problems else "\n".join(f"problem: {x}" for x in problems))
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
