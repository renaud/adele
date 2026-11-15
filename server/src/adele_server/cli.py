"""adele-server: validate | serve | fetch | backfill | check | repartition.

This module imports only what `fetch <id> --if-due` needs to answer "not due": a timer runs
that command every minute for each dataset. The catalog and the ingestion (yaml, duckdb,
frictionless) are imported in main(), after that answer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import config as config_mod
from . import state

UTC = dt.timezone.utc


def _date(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d.replace(tzinfo=UTC) if d.tzinfo is None else d.astimezone(UTC)


def _signal_code() -> int:
    """The exit code of a command that SIGTERM or SIGINT stopped: 128 + the number of the signal (143, 130)."""
    import signal

    from . import ingest
    return 128 + signal.Signals[ingest.stopped()].value


def _not_due(cfg: config_mod.Config, ds_id: str) -> bool:
    """True when it is certain that no scheduled run of this dataset is due.

    The cheap answer for the timer: it reads state.json and adele.refresh.every of the one
    descriptor, not the catalog. On any doubt (no attempt yet, no descriptor, an error): False,
    and the full path decides and reports.
    """
    try:
        s = state.load(cfg.data_dir, ds_id)
        if s.get("last_attempt_at") is None:
            return False
        from .catalog import refresh_every  # yaml: imported only when there is a state to compare with
        every = refresh_every(cfg.datasets_dirs, ds_id)
        return every is not None and not state.is_due(s, every, state.now())
    except Exception:  # noqa: BLE001 - the full path reports what is wrong
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="adele-server", description=__doc__)
    p.add_argument("--config", help="config file (default: $ADELE_SERVER_CONFIG or ./adele-server.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="load and validate every descriptor")
    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    f = sub.add_parser("fetch", help="scheduled run: fetch [last scheduled run - lookback, now + horizon)")
    g = f.add_mutually_exclusive_group(required=True)
    g.add_argument("dataset", nargs="?")
    g.add_argument("--due", action="store_true", help="every dataset whose refresh is due (run by cron)")
    f.add_argument("--if-due", action="store_true", help="with a dataset: fetch it if its refresh is due, else "
                   "exit with 0 and without output (run by a timer every minute)")
    f.add_argument("--start", type=_date, help="explicit window start (UTC date or ISO timestamp); with --start "
                   "or --end the fetch is not a scheduled run (default for the other end: now - lookback, now + horizon)")
    f.add_argument("--end", type=_date, help="explicit window end")
    b = sub.add_parser("backfill", help="fetch successive windows, then check")
    b.add_argument("dataset")
    b.add_argument("--start", type=_date, required=True)
    b.add_argument("--end", type=_date, help="default: now + horizon")
    b.add_argument("--step-days", type=int, help="window length in days (default: adele.refresh.max_window, else 365)")
    b.add_argument("--step-hours", type=int, help="window length in hours, instead of --step-days "
                   "(forecasts: one window per run keeps each fetch under the time limit)")
    c = sub.add_parser("check", help="run the checks on the stored data and update the status")
    c.add_argument("dataset")
    rp = sub.add_parser("repartition", help="rewrite the stored files after a change of adele.partition")
    rp.add_argument("dataset")
    args = p.parse_args(argv)
    if args.cmd == "fetch" and args.if_due and (args.dataset is None or args.start or args.end):
        f.error("--if-due needs a dataset, and neither --start nor --end")

    cfg = config_mod.load(args.config)
    if args.cmd == "fetch" and args.if_due and _not_due(cfg, args.dataset):
        return 0

    import logging

    from . import ingest
    from .catalog import CatalogError, load_catalog, scan_catalog

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    invalid: list[str] = []
    if args.cmd == "fetch":
        # Tolerant: one invalid descriptor must not stop the fetches of the other datasets.
        catalog, invalid = scan_catalog(cfg.datasets_dirs)
        for e in invalid:
            print(f"invalid, not loaded: {' '.join(e.split())}", file=sys.stderr)  # one line each
    else:
        try:
            catalog = load_catalog(cfg.datasets_dirs)
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
            todo = list(catalog.values())
        else:
            if args.dataset not in catalog:
                known = any(e.startswith(f"{args.dataset}: ") for e in invalid)
                print(f"error: the descriptor of {args.dataset!r} is invalid (see above)" if known else
                      f"error: unknown dataset {args.dataset!r}", file=sys.stderr)
                return 2
            todo = [catalog[args.dataset]]
        rc, cut = 0, False
        with ingest.stop_on_signals():
            for ds in todo:
                if ingest.stopped():  # SIGTERM or SIGINT: the datasets that are left wait for the next command
                    cut = True
                    break
                # The time of this dataset's run, not of the command: the run of the dataset before
                # may have lasted hours (a catch-up in pieces), and another command may have fetched
                # this one meanwhile.
                now = state.now()
                if (args.due or args.if_due) and not ingest.is_due(ds, state.load(cfg.data_dir, ds.id), now):
                    continue
                try:
                    if args.start is None and args.end is None:
                        o = ingest.scheduled_fetch(cfg, catalog, ds, now)
                    else:  # an explicit window: not a scheduled run, last_scheduled_at stays
                        start, end = ingest.scheduled_window(ds, now)
                        o = ingest.fetch_window(cfg, catalog, ds, args.start or start, args.end or end)
                except ingest.FetchError as e:
                    print(f"skip {ds.id}: {e}", file=sys.stderr)
                    continue
                print(f"{ds.id} [{o.start:%Y-%m-%d %H:%M}, {o.end:%Y-%m-%d %H:%M}) UTC: "
                      f"{'ok' if o.ok else 'FAILED'}, {o.rows} rows, {o.rows_changed} new or changed, "
                      f"{o.partitions_written} partitions written"
                      f"{f' ({o.windows_fetched} windows fetched)' if ds.revisions == 'none' else ''}"
                      f"{f' (in {o.pieces} pieces)' if o.pieces > 1 else ''}; "
                      f"status {'failing' if o.problems else 'ok'}")
                for pr in o.problems or []:
                    print(f"  problem: {pr}")
                rc = rc or (0 if o.ok else 1)
                cut = cut or o.interrupted
            if cut:
                return _signal_code()
        # --due with an invalid descriptor: the other datasets were fetched, and the code says that one was not.
        return 2 if args.due and invalid else rc
    if args.dataset not in catalog:
        print(f"error: unknown dataset {args.dataset!r}", file=sys.stderr)
        return 2
    try:
        return _by_hand(args, cfg, catalog, now)
    except ingest.FetchError as e:  # the lock: a fetch or a backfill of this dataset is running
        print(f"error: {e}", file=sys.stderr)
        return 1


def _by_hand(args, cfg, catalog, now) -> int:
    """backfill, repartition, check: each holds the lock of the dataset from start to end."""
    from . import ingest

    if args.cmd == "backfill":
        ds = catalog[args.dataset]
        end = args.end or ingest.scheduled_window(ds, now)[1]
        step = (dt.timedelta(hours=args.step_hours) if args.step_hours else
                dt.timedelta(days=args.step_days) if args.step_days else None)  # None: max_window, else 365 days
        with ingest.stop_on_signals():
            outs = ingest.backfill(cfg, catalog, ds, args.start, end, step, now=now)
            cut = _signal_code() if outs and outs[-1].interrupted else 0
        failed = [o for o in outs if not o.ok]
        st = state.load(cfg.data_dir, ds.id)
        print(f"{ds.id}: {len(outs)} windows, {sum(o.rows for o in outs)} rows, {len(failed)} failed; "
              f"status {st['status']}")
        for o in failed:
            print(f"  failed [{o.start:%Y-%m-%d %H:%M}, {o.end:%Y-%m-%d %H:%M}) UTC: {o.error}")
        if failed and st.get("last_scheduled_at") == now:  # the backfill counts as a scheduled run made at `now`
            print(f"  the scheduled runs fetch again from {now - ds.refresh.lookback:%Y-%m-%d %H:%M} UTC on; "
                  "a failed window before that needs a new backfill")
        for pr in st.get("problems", []):
            print(f"  problem: {pr}")
        return cut or (1 if failed else 0)
    if args.cmd == "repartition":
        from . import storage
        ds = catalog[args.dataset]
        with ingest.dataset_lock(cfg.data_dir, ds.id):
            con = storage.connect()
            for t in ds.tables.values():
                if not t.has_time:
                    print(f"{t.sql_name}: no time column, one file: nothing to do")
                    continue
                n = storage.repartition(con, cfg.data_dir, t)
                print(f"{t.sql_name}: {n} files, one per {t.partition} of {t.window}")
            con.close()
        return 0
    if args.cmd == "check":
        problems = ingest.recheck(cfg, catalog, catalog[args.dataset])
        print("ok" if not problems else "\n".join(f"problem: {x}" for x in problems))
        return 1 if problems else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
