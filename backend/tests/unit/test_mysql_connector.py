"""Unit tests for the MySQLConnector adapter. asyncmy is monkey-patched."""
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

    def close(self) -> None:
        # asyncmy.Connection.close() is synchronous (returns None, not a coroutine).
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
    _patch_connect(monkeypatch, raise_exc=TimeoutError())

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


# --- run_select ---------------------------------------------------------------


class _RunSelectCursor:
    """Cursor variant that also exposes asyncmy's `description` attribute
    after `execute`, so we can read column names."""

    def __init__(
        self, rows: list[tuple[Any, ...]], description: list[tuple[str, ...]]
    ) -> None:
        self._rows = rows
        self._description = description
        self.queries: list[str] = []

    async def execute(self, query: str, *_args: Any) -> None:
        self.queries.append(query)

    @property
    def description(self) -> list[tuple[str, ...]]:
        return self._description

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "_RunSelectCursor":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()


class _RunSelectConnection:
    def __init__(
        self, rows: list[tuple[Any, ...]], description: list[tuple[str, ...]]
    ) -> None:
        self._rows = rows
        self._description = description
        self.closed = False

    def cursor(self) -> _RunSelectCursor:
        return _RunSelectCursor(self._rows, self._description)

    def close(self) -> None:
        # asyncmy.Connection.close() is synchronous.
        self.closed = True


def _patch_connect_run_select(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fake_conn: _RunSelectConnection | None = None,
    raise_exc: BaseException | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_connect(**kwargs: Any) -> _RunSelectConnection:
        captured.update(kwargs)
        if raise_exc is not None:
            raise raise_exc
        assert fake_conn is not None
        return fake_conn

    import asyncmy
    monkeypatch.setattr(asyncmy, "connect", _fake_connect)
    return captured


async def test_run_select_returns_columns_and_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [(1, "alice"), (2, "bob")]
    description = [("id",), ("name",)]
    conn = _RunSelectConnection(rows, description)
    _patch_connect_run_select(monkeypatch, fake_conn=conn)

    result = await MySQLConnector().run_select(
        _spec(), "SELECT id, name FROM users", row_limit=10
    )

    assert result.columns == ("id", "name")
    assert result.row_count == 2
    assert result.rows[0] == {"id": 1, "name": "alice"}
    assert result.truncated is False
    assert conn.closed is True


async def test_run_select_truncates_when_db_returns_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [(i,) for i in range(4)]
    description = [("i",)]
    conn = _RunSelectConnection(rows, description)
    _patch_connect_run_select(monkeypatch, fake_conn=conn)

    result = await MySQLConnector().run_select(
        _spec(), "SELECT i FROM t", row_limit=3
    )

    assert result.row_count == 3
    assert [r["i"] for r in result.rows] == [0, 1, 2]
    assert result.truncated is True


async def test_run_select_stringifies_uuid_and_datetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import datetime as _dt
    from uuid import UUID

    rows = [(
        UUID("11111111-2222-3333-4444-555555555555"),
        _dt.datetime(2026, 5, 25, 12, 0, tzinfo=_dt.UTC),
        None,
    )]
    description = [("id",), ("ts",), ("n",)]
    conn = _RunSelectConnection(rows, description)
    _patch_connect_run_select(monkeypatch, fake_conn=conn)

    result = await MySQLConnector().run_select(
        _spec(), "SELECT id, ts, n FROM t", row_limit=10
    )

    assert isinstance(result.rows[0]["id"], str)
    assert "2026-05-25" in result.rows[0]["ts"]
    assert result.rows[0]["n"] is None


async def test_run_select_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _RunSelectConnection([], [])
    _patch_connect_run_select(monkeypatch, fake_conn=conn)

    result = await MySQLConnector().run_select(
        _spec(), "SELECT 1 WHERE FALSE", row_limit=10
    )

    assert result.row_count == 0
    assert result.columns == ()
    assert result.truncated is False


async def test_run_select_query_error_raises_query_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncmy.errors

    from tfm_rag.domain.errors.chat import QueryExecutionError

    class _FailingCursor(_RunSelectCursor):
        async def execute(self, query: str, *args: Any) -> None:
            raise asyncmy.errors.ProgrammingError(
                1146, "Table 'shop.nope' doesn't exist"
            )

    class _Conn(_RunSelectConnection):
        def cursor(self) -> _RunSelectCursor:
            return _FailingCursor([], [])

    conn = _Conn([], [])
    _patch_connect_run_select(monkeypatch, fake_conn=conn)

    with pytest.raises(QueryExecutionError) as exc_info:
        await MySQLConnector().run_select(
            _spec(), "SELECT * FROM nope", row_limit=10
        )
    assert "doesn't exist" in str(exc_info.value).lower() or "1146" in str(exc_info.value)
    assert conn.closed is True
