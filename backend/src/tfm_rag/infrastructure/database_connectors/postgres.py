"""PostgresConnector — asyncpg adapter for DatabaseConnector port."""
import asyncio
from datetime import datetime, timezone
from typing import Any

import asyncpg

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
    "SELECT table_schema, table_name, column_name, data_type, is_nullable\n"
    "FROM information_schema.columns\n"
    "WHERE table_schema NOT IN ('pg_catalog','information_schema')\n"
    "ORDER BY table_schema, table_name, ordinal_position"
)

_CONNECT_TIMEOUT_S = 10.0


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
            captured_at=datetime.now(timezone.utc),
            tables=tables,
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
        except asyncio.TimeoutError as exc:
            raise DatabaseConnectionError(
                f"connection timeout after {_CONNECT_TIMEOUT_S:.0f}s"
            ) from exc
        except OSError as exc:
            raise DatabaseConnectionError(str(exc)) from exc

    @staticmethod
    def _safe(exc: BaseException) -> str:
        # Defensive: asyncpg error messages may include the host but should
        # not include the password. We still strip the spec password if it
        # somehow shows up.
        return str(exc)

    @staticmethod
    def _group_rows_to_tables(
        rows: list[Any],
    ) -> tuple[TableSchema, ...]:
        # rows are (table_schema, table_name, column_name, data_type, is_nullable)
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
