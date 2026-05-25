"""Port for outbound read-only database connectors.

A DatabaseConnector knows how to:
  * test that a connection spec is reachable + authenticated
  * introspect the schema (tables + columns) of the target DB

Plan #13 will extend this port with a `run_select(spec, sql, limit) -> Rows`
method for the `query_database` agent tool. Plan #9 does NOT need it yet.
"""
from abc import ABC, abstractmethod
from typing import Any

from tfm_rag.domain.value_objects.database_schema import (
    DatabaseSchemaSnapshot,
)


class DatabaseConnector(ABC):
    """Adapter contract for a single SQL dialect.

    `spec` is the plaintext dict produced from a DatabaseSourceSpec. It
    contains the user-supplied connection params PLUS the plaintext
    password (callers MUST decrypt before invoking). The connector itself
    is stateless and does not log or persist `spec`.
    """

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
