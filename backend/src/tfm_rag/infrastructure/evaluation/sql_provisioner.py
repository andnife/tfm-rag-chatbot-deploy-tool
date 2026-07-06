"""Provision a dataset's SQL seed into an isolated MySQL database.

Uses a dedicated admin asyncmy connection — separate from the read-only
MySQLConnector used at query time. Owns the DROP/CREATE DATABASE lifecycle;
the user-supplied seed may only define/populate tables (see seed_sql guard).
"""
import asyncio
from typing import Any
from uuid import UUID

import asyncmy
import asyncmy.errors

from tfm_rag.application.evaluation.seed_sql import (
    assert_safe_seed,
    split_sql_statements,
)
from tfm_rag.domain.errors.knowledge import DatabaseConnectionError

_CONNECT_TIMEOUT_S = 10.0


def schema_name_for(dataset_id: UUID) -> str:
    return f"evalds_{dataset_id.hex}"


async def _connect(
    *, host: str, port: int, user: str, password: str, db: str | None
) -> Any:
    kwargs = dict(
        host=host, port=int(port), user=user, password=password,
        connect_timeout=int(_CONNECT_TIMEOUT_S),
    )
    if db is not None:
        kwargs["db"] = db
    try:
        return await asyncio.wait_for(
            asyncmy.connect(**kwargs), timeout=_CONNECT_TIMEOUT_S
        )
    except (asyncmy.errors.Error, TimeoutError, OSError) as exc:
        raise DatabaseConnectionError(str(exc)) from exc


async def provision_seed(
    *,
    dataset_id: UUID,
    seed_sql: str,
    host: str,
    port: int,
    admin_user: str,
    admin_password: str,
) -> str:
    schema = schema_name_for(dataset_id)
    statements = split_sql_statements(seed_sql)
    assert_safe_seed(statements)  # raises EvalDatasetError on forbidden SQL

    # 1. Drop + create the isolated database (admin connection, no default db).
    admin = await _connect(
        host=host, port=port, user=admin_user, password=admin_password, db=None
    )
    try:
        async with admin.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS {schema}")
            await cur.execute(f"CREATE DATABASE {schema}")
    finally:
        admin.close()

    # 2. Run the seed statements inside the new database.
    conn = await _connect(
        host=host, port=port, user=admin_user, password=admin_password, db=schema
    )
    try:
        async with conn.cursor() as cur:
            for stmt in statements:
                await cur.execute(stmt)
        await conn.commit()
    except asyncmy.errors.Error as exc:
        raise DatabaseConnectionError(f"seed failed: {exc}") from exc
    finally:
        conn.close()

    return schema
