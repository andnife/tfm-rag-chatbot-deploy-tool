"""MySQLConnector — asyncmy adapter for DatabaseConnector port."""
import asyncio
from datetime import UTC, datetime
from typing import Any

import asyncmy
import asyncmy.errors

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

_INTROSPECT_QUERY = (
    "SELECT table_schema, table_name, column_name, data_type, is_nullable "
    "FROM information_schema.columns "
    "WHERE table_schema NOT IN ("
    "'mysql','sys','performance_schema','information_schema'"
    ") "
    "ORDER BY table_schema, table_name, ordinal_position"
)

_CONNECT_TIMEOUT_S = 10.0


class MySQLConnector(DatabaseConnector):
    async def test_connection(self, spec: dict[str, Any]) -> None:
        conn = await self._connect(spec)
        conn.close()  # asyncmy close() is synchronous

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
                raise SchemaIntrospectionError(str(exc)) from exc
        finally:
            conn.close()  # asyncmy close() is synchronous

        tables = self._group_rows_to_tables(rows)
        return DatabaseSchemaSnapshot(
            captured_at=datetime.now(UTC),
            tables=tables,
        )

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
            raise DatabaseConnectionError(str(exc)) from exc
        except asyncmy.errors.Error as exc:
            raise DatabaseConnectionError(str(exc)) from exc
        except TimeoutError as exc:
            raise DatabaseConnectionError(
                f"connection timeout after {_CONNECT_TIMEOUT_S:.0f}s"
            ) from exc
        except OSError as exc:
            raise DatabaseConnectionError(str(exc)) from exc

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
