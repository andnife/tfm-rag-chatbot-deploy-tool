"""Unit tests for the MySQLConnector adapter. asyncmy is monkey-patched."""
import asyncio
from datetime import datetime
from typing import Any

import pytest

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    SchemaIntrospectionError,
)
from tfm_rag.infrastructure.database_connectors.mysql import MySQLConnector

pytestmark = pytest.mark.asyncio


def _spec(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "driver": "mysql",
        "host": "mysql.example.com",
        "port": 3306,
        "db_name": "shop",
        "username": "ro",
        "password": "p4ss",
        "ssl_mode": "disable",
    }
    base.update(overrides)
    return base


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.queries: list[str] = []

    async def execute(self, query: str, *_args: Any) -> None:
        self.queries.append(query)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()


class _FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows)

    async def close(self) -> None:
        self.closed = True


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

    import asyncmy

    monkeypatch.setattr(asyncmy, "connect", _fake_connect)
    return captured


async def test_test_connection_success_passes_spec_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await MySQLConnector().test_connection(_spec())

    assert captured["host"] == "mysql.example.com"
    assert captured["port"] == 3306
    assert captured["user"] == "ro"
    assert captured["password"] == "p4ss"
    assert captured["db"] == "shop"
    assert conn.closed is True


async def test_test_connection_with_ssl_require_sets_ssl_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await MySQLConnector().test_connection(_spec(ssl_mode="require"))

    # asyncmy uses `ssl={}` to opt-in (no specific certs in MVP)
    assert captured.get("ssl") == {}


async def test_test_connection_with_ssl_disable_omits_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await MySQLConnector().test_connection(_spec(ssl_mode="disable"))

    assert "ssl" not in captured


async def test_test_connection_auth_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncmy.errors

    _patch_connect(
        monkeypatch,
        raise_exc=asyncmy.errors.OperationalError(
            1045, "Access denied for user 'ro'@'host' (using password: YES)"
        ),
    )

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await MySQLConnector().test_connection(_spec())

    msg = str(exc_info.value)
    assert "access denied" in msg.lower() or "1045" in msg
    assert "p4ss" not in msg  # password must NOT leak


async def test_test_connection_network_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=OSError("Connection refused"))

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await MySQLConnector().test_connection(_spec())

    assert "refused" in str(exc_info.value).lower()


async def test_test_connection_timeout_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=asyncio.TimeoutError())

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await MySQLConnector().test_connection(_spec())

    assert "timeout" in str(exc_info.value).lower()


async def test_introspect_schema_returns_tables_and_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        ("shop", "users", "id", "int", "NO"),
        ("shop", "users", "email", "varchar", "NO"),
        ("shop", "orders", "id", "int", "NO"),
        ("shop", "orders", "user_id", "int", "YES"),
    ]
    conn = _FakeConnection(rows)
    _patch_connect(monkeypatch, fake_conn=conn)

    snapshot = await MySQLConnector().introspect_schema(_spec())

    assert snapshot.table_count == 2
    tables = {t.name: t for t in snapshot.tables}
    assert set(tables) == {"users", "orders"}
    users = tables["users"]
    assert users.schema == "shop"
    assert [c.name for c in users.columns] == ["id", "email"]
    assert users.columns[1].data_type == "varchar"
    assert users.columns[1].nullable is False
    orders = tables["orders"]
    assert orders.columns[1].nullable is True


async def test_introspect_schema_empty_db_returns_empty_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    _patch_connect(monkeypatch, fake_conn=conn)

    snapshot = await MySQLConnector().introspect_schema(_spec())

    assert snapshot.table_count == 0
    assert snapshot.tables == ()
    assert isinstance(snapshot.captured_at, datetime)


async def test_introspect_schema_query_failure_raises_schema_introspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncmy.errors

    class _FailingCursor(_FakeCursor):
        async def execute(self, query: str, *args: Any) -> None:
            raise asyncmy.errors.ProgrammingError(
                1142, "SELECT command denied to user 'ro'@'host'"
            )

    class _FailingConnection(_FakeConnection):
        def cursor(self) -> _FakeCursor:
            return _FailingCursor([])

    conn = _FailingConnection([])
    _patch_connect(monkeypatch, fake_conn=conn)

    with pytest.raises(SchemaIntrospectionError) as exc_info:
        await MySQLConnector().introspect_schema(_spec())

    assert "denied" in str(exc_info.value).lower() or "1142" in str(exc_info.value)
