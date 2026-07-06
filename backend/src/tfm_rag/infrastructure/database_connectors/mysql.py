"""MySQLConnector — asyncmy adapter for DatabaseConnector port."""
import asyncio
import datetime as _dt
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncmy
import asyncmy.errors

from tfm_rag.domain.errors.chat import QueryExecutionError
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    SchemaIntrospectionError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.value_objects.database_schema import (
    ColumnSchema,
    DatabaseSchemaSnapshot,
    TableSchema,
)
from tfm_rag.domain.value_objects.sql_query_result import SqlQueryResult

_log = logging.getLogger(__name__)

_INTROSPECT_QUERY = (
    "SELECT table_schema, table_name, column_name, data_type, is_nullable "
    "FROM information_schema.columns "
    "WHERE table_schema NOT IN ("
    "'mysql','sys','performance_schema','information_schema'"
    ") "
    "ORDER BY table_schema, table_name, ordinal_position"
)

_CONNECT_TIMEOUT_S = 10.0
_QUERY_TIMEOUT_S = 15.0


class MySQLConnector(DatabaseConnector):
    async def test_connection(self, spec: dict[str, Any]) -> None:
        conn = await self._connect(spec)
        conn.close()

    async def introspect_schema(
        self, spec: dict[str, Any]
    ) -> DatabaseSchemaSnapshot:
        conn = await self._connect(spec)
        try:
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(_INTROSPECT_QUERY)
                    rows = await cursor.fetchall()
            except asyncmy.errors.Error as exc:
                raise SchemaIntrospectionError(
                    self._safe(exc, "schema introspection failed")
                ) from exc
        finally:
            conn.close()

        tables = self._group_rows_to_tables(rows)
        return DatabaseSchemaSnapshot(
            captured_at=datetime.now(_dt.UTC),
            tables=tables,
        )

    async def run_select(
        self,
        spec: dict[str, Any],
        sql: str,
        row_limit: int,
    ) -> SqlQueryResult:
        from tfm_rag.application.chat.sql_safety import enforce_limit

        final_sql = enforce_limit(sql, row_limit=row_limit)
        effective_extra = row_limit + 1

        conn = await self._connect(spec)
        try:
            try:
                async with conn.cursor() as cursor:
                    # Defence-in-depth: a read-only transaction makes the
                    # server reject any write, even if the application-layer
                    # SQL filter were bypassed and regardless of the user's
                    # grants.
                    await cursor.execute("START TRANSACTION READ ONLY")
                    try:
                        await asyncio.wait_for(
                            cursor.execute(final_sql), timeout=_QUERY_TIMEOUT_S
                        )
                    except TimeoutError as exc:
                        raise QueryExecutionError(
                            f"query timed out after {_QUERY_TIMEOUT_S:.0f}s"
                        ) from exc
                    description = cursor.description or []
                    columns = tuple(col[0] for col in description)
                    rows_raw = await cursor.fetchall()
            except asyncmy.errors.Error as exc:
                raise QueryExecutionError(
                    self._safe(exc, "query execution failed")
                ) from exc
        finally:
            conn.close()

        if not columns:
            return SqlQueryResult(columns=(), rows=(), truncated=False)

        truncated = len(rows_raw) >= effective_extra
        kept = rows_raw[:row_limit] if truncated else list(rows_raw)
        rows = tuple(
            {col: _jsonable(value) for col, value in zip(columns, row, strict=False)}
            for row in kept
        )
        return SqlQueryResult(columns=columns, rows=rows, truncated=truncated)

    async def _connect(self, spec: dict[str, Any]) -> Any:
        ssl_mode = spec.get("ssl_mode", "disable")
        kwargs: dict[str, Any] = {
            "host": spec["host"],
            "port": int(spec["port"]),
            "user": spec["username"],
            "password": spec["password"],
            "db": spec["db_name"],
            "connect_timeout": int(_CONNECT_TIMEOUT_S),
        }
        if ssl_mode != "disable":
            kwargs["ssl"] = {}
        try:
            return await asyncio.wait_for(
                asyncmy.connect(**kwargs), timeout=_CONNECT_TIMEOUT_S
            )
        except asyncmy.errors.OperationalError as exc:
            raise DatabaseConnectionError(
                self._safe(exc, "database connection failed")
            ) from exc
        except asyncmy.errors.Error as exc:
            raise DatabaseConnectionError(
                self._safe(exc, "database connection failed")
            ) from exc
        except TimeoutError as exc:
            raise DatabaseConnectionError(
                f"connection timeout after {_CONNECT_TIMEOUT_S:.0f}s"
            ) from exc
        except OSError as exc:
            raise DatabaseConnectionError(
                self._safe(exc, "database connection failed")
            ) from exc

    @staticmethod
    def _safe(exc: BaseException, generic_message: str) -> str:
        """Log the raw driver exception; return a generic, client-safe message.

        Raw asyncmy/OS exception text can embed hostnames, credential
        fragments, SQL text, or server version/error-code strings — none of
        which should ever reach an API client (T13 hardening). The raw
        detail stays available server-side: it's logged here, and (because
        every call site re-raises with `from exc`) it's preserved in the
        exception's `__cause__` chain, which `error_handler`'s traceback
        capture threads into both the server log and the recorded
        incident (see `infrastructure.api.error_handler._record_incident`).
        """
        _log.error(
            "sanitized %s for client response: %s",
            type(exc).__name__, exc, exc_info=exc,
        )
        return generic_message

    @staticmethod
    def _group_rows_to_tables(
        rows: list[tuple[Any, ...]],
    ) -> tuple[TableSchema, ...]:
        grouped: dict[tuple[str, str], list[ColumnSchema]] = {}
        order: list[tuple[str, str]] = []
        for row in rows:
            schema, name, col_name, data_type, is_nullable = row
            key = (schema, name)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(
                ColumnSchema(
                    name=col_name,
                    data_type=data_type,
                    nullable=is_nullable == "YES",
                )
            )
        return tuple(
            TableSchema(
                schema=s, name=n, columns=tuple(grouped[(s, n)])
            )
            for s, n in order
        )


def _jsonable(value: Any) -> Any:
    """Coerce asyncmy row values to JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return str(value)
