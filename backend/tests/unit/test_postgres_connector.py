"""Unit tests for the PostgresConnector adapter. asyncpg is monkey-patched."""
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import pytest

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    SchemaIntrospectionError,
)
from tfm_rag.infrastructure.database_connectors.postgres import (
    PostgresConnector,
)

pytestmark = pytest.mark.asyncio


def _spec(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "driver": "postgres",
        "host": "db.example.com",
        "port": 5432,
        "db_name": "analytics",
        "username": "ro",
        "password": "s3cret",
        "ssl_mode": "disable",
    }
    base.update(overrides)
    return base


class _FakeConnection:
    """Minimal asyncpg.Connection stand-in. Records the queries it sees."""

    def __init__(self, rows_by_query: dict[str, list[dict[str, Any]]]) -> None:
        self._rows_by_query = rows_by_query
        self.queries: list[str] = []
        self.closed = False

    async def fetch(self, query: str, *_args: Any) -> list[Any]:
        self.queries.append(query)
        rows = self._rows_by_query.get(query.strip(), [])
        return [_Row(r) for r in rows]

    async def close(self) -> None:
        self.closed = True


class _Row(dict[str, Any]):
    """asyncpg.Record-like: supports both __getitem__('col') and attribute access."""


def _patch_connect(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_conn: _FakeConnection | None = None,
    raise_exc: BaseException | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_connect(**kwargs: Any) -> _FakeConnection:
        captured.update(kwargs)
        if raise_exc is not None:
            raise raise_exc
        assert fake_conn is not None
        return fake_conn

    import asyncpg

    monkeypatch.setattr(asyncpg, "connect", _fake_connect)
    return captured


async def test_test_connection_success_uses_spec_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection({})
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await PostgresConnector().test_connection(_spec())

    assert captured["host"] == "db.example.com"
    assert captured["port"] == 5432
    assert captured["user"] == "ro"
    assert captured["password"] == "s3cret"
    assert captured["database"] == "analytics"
    assert conn.closed is True


async def test_test_connection_with_ssl_require_sets_ssl_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection({})
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await PostgresConnector().test_connection(_spec(ssl_mode="require"))

    assert captured["ssl"] == "require"


async def test_test_connection_with_ssl_disable_omits_ssl_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection({})
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await PostgresConnector().test_connection(_spec(ssl_mode="disable"))

    assert "ssl" not in captured or captured["ssl"] is False


async def test_test_connection_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncpg

    _patch_connect(
        monkeypatch,
        raise_exc=asyncpg.InvalidPasswordError("password authentication failed for user \"ro\""),
    )

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await PostgresConnector().test_connection(_spec())

    msg = str(exc_info.value)
    assert "authentication" in msg.lower()
    assert "s3cret" not in msg  # password must NOT leak


async def test_test_connection_network_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=OSError("Connection refused"))

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await PostgresConnector().test_connection(_spec())

    assert "refused" in str(exc_info.value).lower()


async def test_test_connection_timeout_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=asyncio.TimeoutError())

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await PostgresConnector().test_connection(_spec())

    assert "timeout" in str(exc_info.value).lower()


async def test_introspect_schema_returns_tables_and_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"table_schema": "public", "table_name": "users",
         "column_name": "id", "data_type": "integer", "is_nullable": "NO"},
        {"table_schema": "public", "table_name": "users",
         "column_name": "email", "data_type": "text", "is_nullable": "NO"},
        {"table_schema": "public", "table_name": "orders",
         "column_name": "id", "data_type": "integer", "is_nullable": "NO"},
        {"table_schema": "public", "table_name": "orders",
         "column_name": "user_id", "data_type": "integer", "is_nullable": "YES"},
    ]
    introspect_query = (
        "SELECT table_schema, table_name, column_name, data_type, is_nullable\n"
        "FROM information_schema.columns\n"
        "WHERE table_schema NOT IN ('pg_catalog','information_schema')\n"
        "ORDER BY table_schema, table_name, ordinal_position"
    )
    conn = _FakeConnection({introspect_query: rows})
    _patch_connect(monkeypatch, fake_conn=conn)

    snapshot = await PostgresConnector().introspect_schema(_spec())

    assert snapshot.table_count == 2
    tables = {t.name: t for t in snapshot.tables}
    assert set(tables) == {"users", "orders"}
    users = tables["users"]
    assert users.schema == "public"
    assert [c.name for c in users.columns] == ["id", "email"]
    assert users.columns[0].data_type == "integer"
    assert users.columns[0].nullable is False
    orders = tables["orders"]
    assert orders.columns[1].nullable is True
    assert conn.closed is True


async def test_introspect_schema_empty_db_returns_empty_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection({})  # any query returns []
    _patch_connect(monkeypatch, fake_conn=conn)

    snapshot = await PostgresConnector().introspect_schema(_spec())

    assert snapshot.table_count == 0
    assert snapshot.tables == ()
    assert isinstance(snapshot.captured_at, datetime)


async def test_introspect_schema_connection_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=OSError("no route to host"))

    with pytest.raises(DatabaseConnectionError):
        await PostgresConnector().introspect_schema(_spec())


async def test_introspect_schema_query_failure_raises_schema_introspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncpg

    class _FailingConn(_FakeConnection):
        async def fetch(self, query: str, *args: Any) -> list[Any]:
            raise asyncpg.InsufficientPrivilegeError(
                "permission denied for view columns"
            )

    conn = _FailingConn({})
    _patch_connect(monkeypatch, fake_conn=conn)

    with pytest.raises(SchemaIntrospectionError) as exc_info:
        await PostgresConnector().introspect_schema(_spec())

    assert "permission" in str(exc_info.value).lower()
