"""Unit tests for the PostgresConnector adapter. asyncpg is monkey-patched."""
from datetime import datetime
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
    _patch_connect(monkeypatch, raise_exc=TimeoutError())

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


# --- run_select ---------------------------------------------------------------


async def test_run_select_returns_columns_and_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"id": 1, "email": "a@x"},
        {"id": 2, "email": "b@x"},
    ]
    # The connector emits `SELECT id, email FROM users LIMIT N+1`. The fake
    # echoes back whatever rows were registered for any query.
    conn = _FakeConnection({})
    captured_sql: dict[str, str] = {}

    async def _fake_fetch(query: str, *args: Any) -> list[Any]:
        captured_sql["last"] = query
        return [_Row(r) for r in rows]

    conn.fetch = _fake_fetch  # type: ignore[method-assign]
    _patch_connect(monkeypatch, fake_conn=conn)

    result = await PostgresConnector().run_select(
        _spec(), "SELECT id, email FROM users", row_limit=10
    )

    assert result.columns == ("id", "email")
    assert result.row_count == 2
    assert result.rows[0] == {"id": 1, "email": "a@x"}
    assert result.truncated is False
    assert "LIMIT 11" in captured_sql["last"].upper()
    assert conn.closed is True


async def test_run_select_truncates_when_db_returns_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # connector asks for row_limit+1 = 4; fake returns 4 rows → truncated=True
    rows = [{"i": i} for i in range(4)]
    conn = _FakeConnection({})

    async def _fake_fetch(query: str, *args: Any) -> list[Any]:
        return [_Row(r) for r in rows]

    conn.fetch = _fake_fetch  # type: ignore[method-assign]
    _patch_connect(monkeypatch, fake_conn=conn)

    result = await PostgresConnector().run_select(
        _spec(), "SELECT i FROM t", row_limit=3
    )

    assert result.row_count == 3  # trimmed
    assert [r["i"] for r in result.rows] == [0, 1, 2]
    assert result.truncated is True


async def test_run_select_stringifies_uuid_and_datetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import datetime as _dt
    from uuid import UUID

    rows = [{
        "id": UUID("11111111-2222-3333-4444-555555555555"),
        "ts": _dt.datetime(2026, 5, 25, 12, 0, tzinfo=_dt.UTC),
        "n": None,
    }]
    conn = _FakeConnection({})

    async def _fake_fetch(query: str, *args: Any) -> list[Any]:
        return [_Row(r) for r in rows]

    conn.fetch = _fake_fetch  # type: ignore[method-assign]
    _patch_connect(monkeypatch, fake_conn=conn)

    result = await PostgresConnector().run_select(
        _spec(), "SELECT id, ts, n FROM t", row_limit=10
    )

    assert isinstance(result.rows[0]["id"], str)
    assert result.rows[0]["id"].startswith("11111111-")
    assert isinstance(result.rows[0]["ts"], str)
    assert "2026-05-25" in result.rows[0]["ts"]
    assert result.rows[0]["n"] is None


async def test_run_select_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConnection({})
    async def _fake_fetch(query: str, *args: Any) -> list[Any]:
        return []
    conn.fetch = _fake_fetch  # type: ignore[method-assign]
    _patch_connect(monkeypatch, fake_conn=conn)

    result = await PostgresConnector().run_select(
        _spec(), "SELECT 1 WHERE FALSE", row_limit=10
    )

    assert result.row_count == 0
    assert result.columns == ()
    assert result.truncated is False


async def test_run_select_query_error_raises_query_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncpg

    from tfm_rag.domain.errors.chat import QueryExecutionError

    conn = _FakeConnection({})
    async def _fake_fetch(query: str, *args: Any) -> list[Any]:
        raise asyncpg.UndefinedTableError(
            'relation "nope" does not exist'
        )
    conn.fetch = _fake_fetch  # type: ignore[method-assign]
    _patch_connect(monkeypatch, fake_conn=conn)

    with pytest.raises(QueryExecutionError) as exc_info:
        await PostgresConnector().run_select(
            _spec(), "SELECT * FROM nope", row_limit=10
        )
    assert "nope" in str(exc_info.value).lower()
    assert conn.closed is True


async def test_run_select_connection_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=OSError("no route to host"))

    with pytest.raises(DatabaseConnectionError):
        await PostgresConnector().run_select(
            _spec(), "SELECT 1", row_limit=10
        )
