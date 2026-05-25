"""Unit tests for the query_database use case."""
import base64
from typing import Any
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.chat.query_database import (
    QueryDatabaseInput,
    QueryDatabaseOutput,
    query_database,
)
from tfm_rag.domain.errors.chat import (
    DatabaseSourceMismatchError,
    QueryExecutionError,
    UnsafeSQLError,
)
from tfm_rag.domain.errors.knowledge import DatabaseConnectionError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.value_objects.sql_query_result import SqlQueryResult

pytestmark = pytest.mark.asyncio


class _StubEncryptor(SecretEncryptor):
    def encrypt(self, plaintext: bytes) -> bytes:
        return b"enc(" + plaintext + b")"

    def decrypt(self, ciphertext: bytes) -> bytes:
        assert ciphertext.startswith(b"enc(") and ciphertext.endswith(b")")
        return ciphertext[len(b"enc("):-1]


class _FakeConnector:
    def __init__(
        self,
        result: SqlQueryResult | None = None,
        raise_exc: BaseException | None = None,
    ) -> None:
        self.result = result or SqlQueryResult(
            columns=("id",), rows=({"id": 1},), truncated=False
        )
        self.raise_exc = raise_exc
        self.calls: list[tuple[dict[str, Any], str, int]] = []

    async def test_connection(self, spec: dict[str, Any]) -> None:
        raise NotImplementedError

    async def introspect_schema(self, spec: dict[str, Any]) -> Any:
        raise NotImplementedError

    async def run_select(
        self, spec: dict[str, Any], sql: str, row_limit: int,
    ) -> SqlQueryResult:
        self.calls.append((spec, sql, row_limit))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


class _FakeSourceRow:
    """Stand-in for SourceRow with the attrs the use case reads."""

    def __init__(
        self,
        *,
        source_id: UUID,
        kb_id: UUID,
        type_: str = "database",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.id = source_id
        self.kb_id = kb_id
        self.type = type_
        self.payload = payload or _db_payload()


class _FakeSourcesRepo:
    def __init__(self, rows: dict[UUID, _FakeSourceRow]) -> None:
        self._rows = rows

    async def get_by_id(self, source_id: UUID) -> _FakeSourceRow:
        # The use case may call either get_by_id or get; provide both.
        if source_id not in self._rows:
            raise LookupError(source_id)
        return self._rows[source_id]


def _db_payload() -> dict[str, Any]:
    # password_encrypted is base64 of `_StubEncryptor.encrypt(b"s3cret")`.
    encrypted_bytes = b"enc(s3cret)"
    return {
        "driver": "postgres",
        "host": "h.example.com",
        "port": 5432,
        "db_name": "analytics",
        "username": "ro",
        "password_encrypted": base64.b64encode(encrypted_bytes).decode("ascii"),
        "ssl_mode": "disable",
        "schema_snapshot": {"captured_at": "2026-05-25", "tables": []},
    }


def _kb_ids() -> tuple[UUID, UUID]:
    return uuid4(), uuid4()


async def test_happy_path_dispatches_to_correct_driver_with_plain_password() -> None:
    kb_id, source_id = _kb_ids()
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=kb_id,
    )})
    connector = _FakeConnector()
    out = await query_database(
        QueryDatabaseInput(
            allowed_kb_ids=(kb_id,),
            source_id=source_id,
            sql="SELECT id FROM users",
            row_limit=50,
        ),
        sources_repo=repo,
        connectors={"postgres": connector},
        encryptor=_StubEncryptor(),
    )
    assert isinstance(out, QueryDatabaseOutput)
    assert out.result.row_count == 1
    assert out.result.columns == ("id",)

    spec, sql, limit = connector.calls[0]
    assert spec["password"] == "s3cret"  # decrypted
    assert spec["driver"] == "postgres"
    assert spec["host"] == "h.example.com"
    assert sql == "SELECT id FROM users"
    assert limit == 50


async def test_unsafe_sql_is_rejected_before_connector_call() -> None:
    kb_id, source_id = _kb_ids()
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=kb_id,
    )})
    connector = _FakeConnector()

    with pytest.raises(UnsafeSQLError):
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="DROP TABLE users",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": connector},
            encryptor=_StubEncryptor(),
        )
    assert connector.calls == []  # never reached


async def test_source_not_found_raises_mismatch() -> None:
    kb_id, source_id = _kb_ids()
    repo = _FakeSourcesRepo({})  # empty
    with pytest.raises(DatabaseSourceMismatchError):
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="SELECT 1",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": _FakeConnector()},
            encryptor=_StubEncryptor(),
        )


async def test_source_type_not_database_raises_mismatch() -> None:
    kb_id, source_id = _kb_ids()
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=kb_id,
        type_="document",
        payload={"kind": "upload", "filename": "x.txt"},
    )})
    with pytest.raises(DatabaseSourceMismatchError) as exc_info:
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="SELECT 1",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": _FakeConnector()},
            encryptor=_StubEncryptor(),
        )
    assert "document" in str(exc_info.value).lower()


async def test_source_outside_allowed_kb_set_raises_mismatch() -> None:
    kb_id, source_id = _kb_ids()
    other_kb = uuid4()
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=other_kb,
    )})
    with pytest.raises(DatabaseSourceMismatchError):
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="SELECT 1",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": _FakeConnector()},
            encryptor=_StubEncryptor(),
        )


async def test_connector_query_error_bubbles_up() -> None:
    kb_id, source_id = _kb_ids()
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=kb_id,
    )})
    connector = _FakeConnector(
        raise_exc=QueryExecutionError("relation \"nope\" does not exist")
    )
    with pytest.raises(QueryExecutionError):
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="SELECT * FROM nope",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": connector},
            encryptor=_StubEncryptor(),
        )


async def test_connector_connection_error_bubbles_up() -> None:
    kb_id, source_id = _kb_ids()
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=kb_id,
    )})
    connector = _FakeConnector(
        raise_exc=DatabaseConnectionError("connection refused")
    )
    with pytest.raises(DatabaseConnectionError):
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="SELECT 1",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": connector},
            encryptor=_StubEncryptor(),
        )


async def test_unknown_driver_raises_mismatch() -> None:
    kb_id, source_id = _kb_ids()
    bad_payload = _db_payload()
    bad_payload["driver"] = "oracle"
    repo = _FakeSourcesRepo({source_id: _FakeSourceRow(
        source_id=source_id, kb_id=kb_id, payload=bad_payload,
    )})
    with pytest.raises(DatabaseSourceMismatchError) as exc_info:
        await query_database(
            QueryDatabaseInput(
                allowed_kb_ids=(kb_id,),
                source_id=source_id,
                sql="SELECT 1",
                row_limit=50,
            ),
            sources_repo=repo,
            connectors={"postgres": _FakeConnector()},  # only postgres wired
            encryptor=_StubEncryptor(),
        )
    assert "oracle" in str(exc_info.value).lower()
