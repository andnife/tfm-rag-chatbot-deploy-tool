"""Unit tests for DatabaseSourceTester (registry dispatch by driver)."""
from typing import Any

import pytest

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
    DatabaseSourceTester,
)

pytestmark = pytest.mark.asyncio


class _FakeConnector:
    def __init__(self) -> None:
        self.test_calls: list[dict[str, Any]] = []
        self.raise_on_test: BaseException | None = None

    async def test_connection(self, spec: dict[str, Any]) -> None:
        self.test_calls.append(spec)
        if self.raise_on_test is not None:
            raise self.raise_on_test

    async def introspect_schema(self, spec: dict[str, Any]) -> None:
        raise NotImplementedError("not used in the tester")


def _spec(driver: str = "postgres") -> dict[str, Any]:
    return {
        "driver": driver, "host": "h", "port": 5432, "db_name": "d",
        "username": "u", "password": "p", "ssl_mode": "disable",
    }


async def test_tester_registers_itself_as_database() -> None:
    # Importing the module above is enough to trigger registration.
    assert "database" in SOURCE_CONNECTION_TESTERS
    assert isinstance(
        SOURCE_CONNECTION_TESTERS["database"], DatabaseSourceTester
    )


async def test_tester_dispatches_to_postgres_connector() -> None:
    fake = _FakeConnector()
    tester = DatabaseSourceTester({"postgres": fake})

    result = await tester.test(_spec("postgres"))

    assert result == SourceConnectionTestResult(
        ok=True, error=None,
        details={"driver": "postgres"},
    )
    assert fake.test_calls == [_spec("postgres")]


async def test_tester_dispatches_to_mysql_connector() -> None:
    fake = _FakeConnector()
    tester = DatabaseSourceTester({"mysql": fake})

    result = await tester.test(_spec("mysql"))

    assert result.ok is True
    assert result.details == {"driver": "mysql"}
    assert fake.test_calls == [_spec("mysql")]


async def test_tester_unknown_driver_returns_unsupported_error() -> None:
    tester = DatabaseSourceTester({"postgres": _FakeConnector()})

    result = await tester.test(_spec("oracle"))

    assert result.ok is False
    assert result.error is not None
    assert "oracle" in result.error.lower()


async def test_tester_translates_database_connection_error_to_result() -> None:
    fake = _FakeConnector()
    fake.raise_on_test = DatabaseConnectionError("auth failed")
    tester = DatabaseSourceTester({"postgres": fake})

    result = await tester.test(_spec("postgres"))

    assert result.ok is False
    assert result.error == "auth failed"


async def test_tester_unexpected_exception_bubbles_up() -> None:
    fake = _FakeConnector()
    fake.raise_on_test = ValueError("bug")  # not a DatabaseConnectionError
    tester = DatabaseSourceTester({"postgres": fake})

    with pytest.raises(ValueError):
        await tester.test(_spec("postgres"))


async def test_default_registry_has_both_drivers() -> None:
    assert set(DATABASE_CONNECTORS.keys()) == {"postgres", "mysql"}


async def test_unsupported_dialect_error_exists() -> None:
    # Sanity: the error class is imported, not just typed.
    # Async signature aligns with pytestmark = pytest.mark.asyncio at file
    # scope, silencing the "asyncio mark on sync function" warning.
    assert issubclass(UnsupportedDatabaseDialectError, Exception)
