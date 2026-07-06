"""DatabaseSourceTester — wraps DatabaseConnectors as a SourceConnectionTester.

Importing this module has the side effect of registering itself in the
global SOURCE_CONNECTION_TESTERS registry under the key "database". This
mirrors how plan #8 registers the document tester on import.
"""
from typing import Any

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.infrastructure.database_connectors.mysql import MySQLConnector
from tfm_rag.infrastructure.database_connectors.postgres import (
    PostgresConnector,
)

# Default driver -> connector mapping. Plan #13 will reuse this dict for
# query_database.
DATABASE_CONNECTORS: dict[str, DatabaseConnector] = {
    "postgres": PostgresConnector(),
    "mysql": MySQLConnector(),
}


class DatabaseSourceTester:
    """SourceConnectionTester implementation for type='database'.

    Dispatches on spec['driver'] to a connector in `connectors`. The
    registration at import time wires the production set, but the class
    accepts a custom dict for tests.
    """

    def __init__(self, connectors: dict[str, DatabaseConnector]) -> None:
        self._connectors = connectors

    async def test(
        self, spec: dict[str, Any]
    ) -> SourceConnectionTestResult:
        driver = spec.get("driver")
        if not isinstance(driver, str) or driver not in self._connectors:
            return SourceConnectionTestResult(
                ok=False,
                error=(
                    f"unsupported database driver {driver!r}; "
                    f"supported drivers: {sorted(self._connectors)}"
                ),
            )
        connector = self._connectors[driver]
        try:
            await connector.test_connection(spec)
        except DatabaseConnectionError as exc:
            return SourceConnectionTestResult(ok=False, error=str(exc))
        except KeyError as exc:
            return SourceConnectionTestResult(
                ok=False,
                error=f"missing required connection field: {exc}",
            )
        return SourceConnectionTestResult(
            ok=True, error=None, details={"driver": driver}
        )


# Register at import time. This MUST run before the API serves requests.
# `infrastructure/api/app.py` imports the routers, which import the
# attach_database_source use case, which imports this module.
SOURCE_CONNECTION_TESTERS["database"] = DatabaseSourceTester(DATABASE_CONNECTORS)

# Re-export so callers can `from ...database_connectors import UnsupportedDatabaseDialectError`
__all__ = [
    "DATABASE_CONNECTORS",
    "DatabaseSourceTester",
    "UnsupportedDatabaseDialectError",
]
