"""Catalog of explicit router routes (sub-proyecto B).

Single source of truth for the route-name strings the evaluator emits and
the orchestrator branches on.
"""

ROUTE_NORMAL = "normal"
ROUTE_DOCS = "docs"
ROUTE_SQL = "sql"
ROUTE_BOTH = "both"

ROUTE_NAMES: tuple[str, ...] = (ROUTE_NORMAL, ROUTE_DOCS, ROUTE_SQL, ROUTE_BOTH)
