"""Port for outbound read-only database connectors.

A DatabaseConnector knows how to:
  * test that a connection spec is reachable + authenticated
  * introspect the schema (tables + columns) of the target DB
  * run a SELECT statement and return rows (plan #13)

The `spec` dict is plaintext (callers MUST decrypt before invoking).
"""
from abc import ABC, abstractmethod
from typing import Any

from tfm_rag.domain.value_objects.database_schema import (
    DatabaseSchemaSnapshot,
)
from tfm_rag.domain.value_objects.sql_query_result import SqlQueryResult


class DatabaseConnector(ABC):
    """Adapter contract for a single SQL dialect."""

    @abstractmethod
    async def test_connection(self, spec: dict[str, Any]) -> None:
        """Open a one-shot connection. Returns None on success.

        Raises DatabaseConnectionError on any failure (auth, network,
        SSL, timeout). The error message MUST NOT contain the password.
        """

    @abstractmethod
    async def introspect_schema(
        self, spec: dict[str, Any]
    ) -> DatabaseSchemaSnapshot:
        """Read tables + columns from information_schema.

        Raises DatabaseConnectionError if connecting fails, or
        SchemaIntrospectionError if the query succeeds but the result is
        unusable.
        """

    @abstractmethod
    async def run_select(
        self,
        spec: dict[str, Any],
        sql: str,
        row_limit: int,
    ) -> SqlQueryResult:
        """Execute a single read-only SELECT and return the rows.

        The caller MUST have already validated that `sql` is a single
        read-only statement via `application/chat/sql_safety.py`. The
        connector MAY further harden (timeout, server-side row cap) but
        is NOT responsible for parsing.

        Raises:
          - DatabaseConnectionError on connection/auth/timeout failure.
          - QueryExecutionError if the database returns an error
            (syntax, permission, missing table, …).

        Sets `SqlQueryResult.truncated = True` iff the database returned
        MORE rows than `row_limit` (i.e. the connector enforces the cap
        via `LIMIT row_limit + 1` and trims if needed).
        """
