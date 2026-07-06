"""Adapters for the DatabaseConnector port (postgres, mysql).

Importing this package triggers the registration of DatabaseSourceTester
in SOURCE_CONNECTION_TESTERS for type="database".
"""
from tfm_rag.infrastructure.database_connectors.mysql import MySQLConnector
from tfm_rag.infrastructure.database_connectors.postgres import (
    PostgresConnector,
)
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
    DatabaseSourceTester,
)

__all__ = [
    "DATABASE_CONNECTORS",
    "DatabaseSourceTester",
    "MySQLConnector",
    "PostgresConnector",
]
