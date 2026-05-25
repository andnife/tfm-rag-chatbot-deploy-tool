"""query_database — application use case dispatched from the agent loop.

Resolves a database source by id (scoped to the chatbot's allowed KBs),
decrypts the credentials, runs the SQL via the matching connector. Does
NOT validate the SQL itself — that's `sql_safety.assert_select_only`,
which is called inside the use case.
"""
import base64
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from tfm_rag.application.chat.sql_safety import assert_select_only
from tfm_rag.domain.errors.chat import (
    DatabaseSourceMismatchError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.value_objects.sql_query_result import SqlQueryResult


@dataclass(frozen=True, slots=True)
class QueryDatabaseInput:
    allowed_kb_ids: tuple[UUID, ...]
    source_id: UUID
    sql: str
    row_limit: int


@dataclass(frozen=True, slots=True)
class QueryDatabaseOutput:
    result: SqlQueryResult
    driver: str  # 'postgres' | 'mysql'
    db_name: str


class _SourcesRepoLike(Protocol):
    async def get_by_id(self, source_id: UUID) -> Any: ...


async def query_database(
    inp: QueryDatabaseInput,
    *,
    sources_repo: _SourcesRepoLike,
    connectors: dict[str, DatabaseConnector],
    encryptor: SecretEncryptor,
) -> QueryDatabaseOutput:
    # 1. Validate SQL.
    assert_select_only(inp.sql)

    # 2. Load source row.
    try:
        row = await sources_repo.get_by_id(inp.source_id)
    except Exception as exc:  # noqa: BLE001  — repo lookup miss
        raise DatabaseSourceMismatchError(
            f"source {inp.source_id} not found"
        ) from exc

    # 3. Ownership & type check.
    if row.type != "database":
        raise DatabaseSourceMismatchError(
            f"source {inp.source_id} is of type {row.type!r}, not 'database'"
        )
    if row.kb_id not in inp.allowed_kb_ids:
        raise DatabaseSourceMismatchError(
            f"source {inp.source_id} is not attached to the current chatbot's KBs"
        )

    payload: dict[str, Any] = dict(row.payload or {})
    driver = payload.get("driver")
    if driver not in connectors:
        raise DatabaseSourceMismatchError(
            f"unsupported driver {driver!r} for source {inp.source_id}"
        )

    # 4. Decrypt password.
    enc_b64 = payload["password_encrypted"]
    ciphertext = base64.b64decode(enc_b64)
    plaintext_password = encryptor.decrypt(ciphertext).decode("utf-8")

    spec: dict[str, Any] = {
        "driver": driver,
        "host": payload["host"],
        "port": int(payload["port"]),
        "db_name": payload["db_name"],
        "username": payload["username"],
        "password": plaintext_password,
        "ssl_mode": payload.get("ssl_mode", "disable"),
    }

    # 5. Dispatch.
    connector = connectors[driver]
    result = await connector.run_select(
        spec, inp.sql, row_limit=inp.row_limit
    )
    return QueryDatabaseOutput(
        result=result, driver=driver, db_name=payload["db_name"],
    )
