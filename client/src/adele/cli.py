"""adele: list | describe | query. Each subcommand calls one library function and prints it (D4)."""
from __future__ import annotations

import argparse
import sys

from ._api import AdeleError, datasets, describe, query


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="adele", description="Query the datasets of adele. Needs ADELE_API_KEY (and ADELE_URL).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="one line per dataset: id, title, resolution, coverage, status")
    d = sub.add_parser("describe", help="the dataset card: grain, fields, units, coverage, freshness, warnings")
    d.add_argument("dataset")
    q = sub.add_parser("query", help="run DuckDB SQL on the server; tables are <dataset>.<table>")
    q.add_argument("sql", help="the SQL, or - to read it from stdin")
    args = p.parse_args(argv)
    try:
        if args.cmd == "list":
            out = datasets()
        elif args.cmd == "describe":
            out = describe(args.dataset)
        else:
            out = str(query(sys.stdin.read() if args.sql == "-" else args.sql))
    except AdeleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
