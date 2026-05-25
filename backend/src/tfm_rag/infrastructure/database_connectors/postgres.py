"""PostgresConnector — asyncpg adapter for DatabaseConnector port."""
import asyncio
import datetime as _dt
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

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

_INTROSPECT_QUERY = (
    "SELECT table_schema, table_name, column_name, data_type, is_nullable\n"
    "FROM information_schema.columns\n"
    "WHERE table_schema NOT IN ('pg_catalog','information_schema')\n"
    "ORDER BY table_schema, table_name, ordinal_position"
)

_CONNECT_TIMEOUT_S = 10.0
_QUERY_TIMEOUT_S = 15.0


class PostgresConnector(DatabaseConnector):
    async def test_connection(self, spec: dict[str, Any]) -> None:
        conn = await self._connect(spec)
        await conn.close()

    async def introspect_schema(
        self, spec: dict[str, Any]
    ) -> DatabaseSchemaSnapshot:
        conn = await self._connect(spec)
        try:
            try:
                rows = await conn.fetch(_INTROSPECT_QUERY)
            except (
                asyncpg.InsufficientPrivilegeError,
                asyncpg.PostgresError,
            ) as exc:
                raise SchemaIntrospectionError(self._safe(exc)) from exc
        finally:
            await conn.close()

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
        # The caller (use case) has already applied sql_safety.assert_select_only
        # and enforce_limit. The SQL we receive carries `LIMIT row_limit + 1`.
        from tfm_rag.application.chat.sql_safety import enforce_limit

        final_sql = enforce_limit(sql, row_limit=row_limit)
        effective_extra = row_limit + 1

        conn = await self._connect(spec)
        try:
            try:
                rows_raw = await asyncio.wait_for(
                    conn.fetch(final_sql), timeout=_QUERY_TIMEOUT_S
                )
            except TimeoutError as exc:
                raise QueryExecutionError(
                    f"query timed out after {_QUERY_TIMEOUT_S:.0f}s"
                ) from exc
            except asyncpg.PostgresError as exc:
                raise QueryExecutionError(self._safe(exc)) from exc
        finally:
            await conn.close()

        if not rows_raw:
            return SqlQueryResult(columns=(), rows=(), truncated=False)

        first = rows_raw[0]
        if hasattr(first, "keys"):
            columns = tuple(first.keys())
        else:
            columns = tuple(first.__class__.__annotations__.keys())
        truncated = len(rows_raw) >= effective_extra
        kept = rows_raw[:row_limit] if truncated else rows_raw[:row_limit + 1]
        # Ensure we never return more than row_limit rows when truncated.
        rows = tuple(
            {c: _jsonable(r[c]) for c in columns}
            for r in kept[:row_limit if truncated else len(kept)]
        )
        return SqlQueryResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
        )

    async def _connect(self, spec: dict[str, Any]) -> asyncpg.Connection:
        ssl_mode = spec.get("ssl_mode", "disable")
        kwargs: dict[str, Any] = {
            "host": spec["host"],
            "port": int(spec["port"]),
            "user": spec["username"],
            "password": spec["password"],
            "database": spec["db_name"],
            "timeout": _CONNECT_TIMEOUT_S,
        }
        if ssl_mode != "disable":
            kwargs["ssl"] = ssl_mode
        try:
            return await asyncpg.connect(**kwargs)
        except asyncpg.InvalidPasswordError as exc:
            raise DatabaseConnectionError(
                "authentication failed for the given username/password"
            ) from exc
        except asyncpg.PostgresError as exc:
            raise DatabaseConnectionError(self._safe(exc)) from exc
        except TimeoutError as exc:
            raise DatabaseConnectionError(
                f"connection timeout after {_CONNECT_TIMEOUT_S:.0f}s"
            ) from exc
        except OSError as exc:
            raise DatabaseConnectionError(str(exc)) from exc

    @staticmethod
    def _safe(exc: BaseException) -> str:
        return str(exc)

    @staticmethod
    def _group_rows_to_tables(
        rows: list[Any],
    ) -> tuple[TableSchema, ...]:
        grouped: dict[tuple[str, str], list[ColumnSchema]] = {}
        order: list[tuple[str, str]] = []
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            grouped[key].append(
                ColumnSchema(
                    name=row["column_name"],
                    data_type=row["data_type"],
                    nullable=row["is_nullable"] == "YES",
                )
            )
        return tuple(
            TableSchema(
                schema=schema,
                name=name,
                columns=tuple(grouped[(schema, name)]),
            )
            for schema, name in order
        )


def _jsonable(value: Any) -> Any:
    """Coerce asyncpg row values to JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    # Fall back to str for Decimal, custom types, etc.
    return str(value)
