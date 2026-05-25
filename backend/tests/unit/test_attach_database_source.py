"""Unit tests for attach_database_source use case."""
import base64
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)

import pytest

from tfm_rag.application.knowledge.attach_database_source import (
    AttachDatabaseResult,
    attach_database_source,
)
from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    KnowledgeBaseNotFoundError,
    SchemaIntrospectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.value_objects.chunking_config import ChunkingConfig
from tfm_rag.domain.value_objects.database_schema import (
    ColumnSchema,
    DatabaseSchemaSnapshot,
    TableSchema,
)
from tfm_rag.domain.value_objects.database_source_spec import (
    DatabaseSourceSpec,
)
from tfm_rag.domain.value_objects.embedding_selection import EmbeddingSelection

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- fakes


class _StubEncryptor(SecretEncryptor):
    def encrypt(self, plaintext: bytes) -> bytes:
        return b"enc(" + plaintext + b")"

    def decrypt(self, ciphertext: bytes) -> bytes:
        assert ciphertext.startswith(b"enc(") and ciphertext.endswith(b")")
        return ciphertext[len(b"enc("):-1]


class _FakeConnector:
    def __init__(
        self,
        *,
        test_raises: BaseException | None = None,
        introspect_raises: BaseException | None = None,
        snapshot: DatabaseSchemaSnapshot | None = None,
    ) -> None:
        self.test_raises = test_raises
        self.introspect_raises = introspect_raises
        self.snapshot = snapshot or _snapshot()
        self.test_calls: list[dict[str, Any]] = []
        self.introspect_calls: list[dict[str, Any]] = []

    async def test_connection(self, spec: dict[str, Any]) -> None:
        self.test_calls.append(spec)
        if self.test_raises is not None:
            raise self.test_raises

    async def introspect_schema(
        self, spec: dict[str, Any]
    ) -> DatabaseSchemaSnapshot:
        self.introspect_calls.append(spec)
        if self.introspect_raises is not None:
            raise self.introspect_raises
        return self.snapshot


class _FakeKbRepo:
    def __init__(self, kb: KnowledgeBase | None) -> None:
        self._kb = kb
        self.calls: list[UUID] = []

    async def get(self, kb_id: UUID) -> KnowledgeBase:
        self.calls.append(kb_id)
        if self._kb is None:
            raise KnowledgeBaseNotFoundError(str(kb_id))
        return self._kb


class _FakeSourcesRepo:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def insert_database_source(
        self,
        *,
        kb_id: UUID,
        payload: dict[str, Any],
    ) -> UUID:
        source_id = uuid4()
        self.created.append(
            {"source_id": source_id, "kb_id": kb_id, "payload": payload}
        )
        return source_id


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


# --------------------------------------------------------------------------- helpers


def _snapshot() -> DatabaseSchemaSnapshot:
    return DatabaseSchemaSnapshot(
        captured_at=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
        tables=(
            TableSchema(
                schema="public",
                name="users",
                columns=(
                    ColumnSchema(name="id", data_type="integer", nullable=False),
                    ColumnSchema(name="email", data_type="text", nullable=False),
                ),
            ),
        ),
    )


def _kb() -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid4(),
        tenant_id=uuid4(),
        name="MyKB",
        description=None,
        chunking_config=ChunkingConfig(strategy="fixed", chunk_size=300, chunk_overlap=50),
        embedding_selection=EmbeddingSelection(
            provider_id="ollama",
            credential_id=uuid4(),
            model_id="bge-m3",
            dim=1024,
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _spec(driver: str = "postgres") -> DatabaseSourceSpec:
    return DatabaseSourceSpec(
        driver=driver,  # type: ignore[arg-type]
        host="h.example.com",
        port=5432,
        db_name="d",
        username="ro",
        password="s3cret",
        ssl_mode="disable",
    )


# --------------------------------------------------------------------------- tests


async def test_attach_happy_path_persists_encrypted_payload() -> None:
    kb = _kb()
    sources = _FakeSourcesRepo()
    connector = _FakeConnector()
    session = _FakeSession()

    result = await attach_database_source(
        session=session,  # type: ignore[arg-type]
        kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
        sources_repo=sources,  # type: ignore[arg-type]
        kb_id=kb.id,
        spec=_spec("postgres"),
        encryptor=_StubEncryptor(),
        connectors={"postgres": connector},  # type: ignore[arg-type]
    )

    assert isinstance(result, AttachDatabaseResult)
    assert result.snapshot_table_count == 1
    assert result.snapshot_captured_at == _snapshot().captured_at

    assert len(sources.created) == 1
    payload = sources.created[0]["payload"]
    assert payload["driver"] == "postgres"
    assert payload["host"] == "h.example.com"
    assert payload["port"] == 5432
    assert payload["db_name"] == "d"
    assert payload["username"] == "ro"
    assert payload["ssl_mode"] == "disable"
    # Password must be encrypted (base64 of stub-encrypted bytes).
    assert "password" not in payload
    enc_b64 = payload["password_encrypted"]
    assert base64.b64decode(enc_b64) == b"enc(s3cret)"
    # Snapshot is embedded as dict.
    assert payload["schema_snapshot"]["tables"][0]["name"] == "users"
    assert session.commits == 1


async def test_attach_calls_test_connection_before_introspect() -> None:
    kb = _kb()
    connector = _FakeConnector()
    sources = _FakeSourcesRepo()

    await attach_database_source(
        session=_FakeSession(),  # type: ignore[arg-type]
        kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
        sources_repo=sources,  # type: ignore[arg-type]
        kb_id=kb.id,
        spec=_spec("postgres"),
        encryptor=_StubEncryptor(),
        connectors={"postgres": connector},  # type: ignore[arg-type]
    )

    assert len(connector.test_calls) == 1
    assert len(connector.introspect_calls) == 1


async def test_attach_skips_introspection_when_test_fails() -> None:
    kb = _kb()
    connector = _FakeConnector(
        test_raises=DatabaseConnectionError("auth failed")
    )
    sources = _FakeSourcesRepo()
    session = _FakeSession()

    with pytest.raises(DatabaseConnectionError):
        await attach_database_source(
            session=session,  # type: ignore[arg-type]
            kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
            sources_repo=sources,  # type: ignore[arg-type]
            kb_id=kb.id,
            spec=_spec("postgres"),
            encryptor=_StubEncryptor(),
            connectors={"postgres": connector},  # type: ignore[arg-type]
        )
    assert connector.introspect_calls == []
    assert sources.created == []
    assert session.commits == 0


async def test_attach_skips_persistence_when_introspect_fails() -> None:
    kb = _kb()
    connector = _FakeConnector(
        introspect_raises=SchemaIntrospectionError("permission denied")
    )
    sources = _FakeSourcesRepo()
    session = _FakeSession()

    with pytest.raises(SchemaIntrospectionError):
        await attach_database_source(
            session=session,  # type: ignore[arg-type]
            kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
            sources_repo=sources,  # type: ignore[arg-type]
            kb_id=kb.id,
            spec=_spec("postgres"),
            encryptor=_StubEncryptor(),
            connectors={"postgres": connector},  # type: ignore[arg-type]
        )
    assert sources.created == []
    assert session.commits == 0


async def test_attach_unknown_driver_raises_unsupported() -> None:
    kb = _kb()
    with pytest.raises(UnsupportedDatabaseDialectError) as exc_info:
        await attach_database_source(
            session=_FakeSession(),  # type: ignore[arg-type]
            kb_repo=_FakeKbRepo(kb),  # type: ignore[arg-type]
            sources_repo=_FakeSourcesRepo(),  # type: ignore[arg-type]
            kb_id=kb.id,
            spec=_spec("oracle"),
            encryptor=_StubEncryptor(),
            connectors={"postgres": _FakeConnector()},  # type: ignore[arg-type]
        )
    assert "oracle" in str(exc_info.value)


async def test_attach_kb_not_found_propagates() -> None:
    with pytest.raises(KnowledgeBaseNotFoundError):
        await attach_database_source(
            session=_FakeSession(),  # type: ignore[arg-type]
            kb_repo=_FakeKbRepo(None),  # type: ignore[arg-type]
            sources_repo=_FakeSourcesRepo(),  # type: ignore[arg-type]
            kb_id=uuid4(),
            spec=_spec("postgres"),
            encryptor=_StubEncryptor(),
            connectors={"postgres": _FakeConnector()},  # type: ignore[arg-type]
        )
