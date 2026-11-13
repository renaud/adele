"""adele: library and CLI for the agentic data layer (D4, D6).

    import adele
    print(adele.datasets())
    print(adele.describe("entsoe_day_ahead_prices"))
    r = adele.query("SELECT ... FROM entsoe_day_ahead_prices.prices ...")
    r.rows, r.columns, r.total, r.footer; print(r)  # the CLI output
"""
from ._api import AdeleError, QueryResult, datasets, describe, query

__all__ = ["AdeleError", "QueryResult", "datasets", "describe", "query"]
