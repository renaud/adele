"""`adele-server fetch --due` for one lane: only the datasets whose `every` is in [--min-every, --max-every] seconds.

The same calls as the `fetch --due` branch of cli.py of the copied server code (is_due,
scheduled_window, fetch_window), plus the filter on `every`, which the CLI does not have yet.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

common.use_copy()
from adele_server import config as config_mod  # noqa: E402
from adele_server import ingest, state  # noqa: E402
from adele_server.catalog import load_catalog  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--min-every", type=float, default=0)
    ap.add_argument("--max-every", type=float, default=float("inf"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = config_mod.load(args.config)
    catalog = load_catalog(cfg.datasets_dirs)
    now = state.now()
    todo = [ds for ds in catalog.values()
            if args.min_every <= ds.refresh.every.total_seconds() <= args.max_every
            and ingest.is_due(ds, state.load(cfg.data_dir, ds.id), now)]
    rc = 0
    for ds in todo:
        start, end = ingest.scheduled_window(ds, now)
        try:
            o = ingest.fetch_window(cfg, catalog, ds, start, end)
        except ingest.FetchError as e:
            print(f"skip {ds.id}: {e}", file=sys.stderr)
            continue
        print(f"{ds.id} [{start:%Y-%m-%d %H:%M}, {end:%Y-%m-%d %H:%M}) UTC: {'ok' if o.ok else 'FAILED'}, "
              f"{o.rows} rows, {o.rows_changed} new or changed; status {'failing' if o.problems else 'ok'}")
        rc = rc or (0 if o.ok else 1)
    return rc


if __name__ == "__main__":
    sys.exit(main())
