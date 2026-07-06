"""attach_database_source — application use case.

Validates the KB ownership, calls the connector's test+introspect,
encrypts the password, and persists a new Source row with type='database'.
"""
import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.errors.knowledge import (
    KnowledgeBaseNotFoundError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.ports.repositories import (
    KnowledgeBaseRepositoryPort,
    SourceRepositoryPort,
)
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.value_objects.database_source_spec import (
    DatabaseSourceSpec,
)


@dataclass(frozen=True, slots=True)
class AttachDatabaseResult:
    source_id: UUID
    snapshot_table_count: int
    snapshot_captured_at: datetime


async def attach_database_source(
    *,
    kb_repo: KnowledgeBaseRepositoryPort,
    sources_repo: SourceRepositoryPort,
    kb_id: UUID,
    spec: DatabaseSourceSpec,
    encryptor: SecretEncryptor,
    connectors: dict[str, DatabaseConnector],
) -> AttachDatabaseResult:
    # 1. KB ownership (raises KnowledgeBaseNotFoundError on miss).
    try:
        await kb_repo.get_knowledge_base(kb_id)
    except NotFoundError as exc:
        raise KnowledgeBaseNotFoundError(str(exc)) from exc

    # 2. Driver supported?
    connector = connectors.get(spec.driver)
    if connector is None:
        raise UnsupportedDatabaseDialectError(
            f"driver {spec.driver!r} is not supported "
            f"(supported: {sorted(connectors)})"
        )

    spec_dict = spec.to_connector_spec()

    # 3. Test connection (raises DatabaseConnectionError on failure).
    await connector.test_connection(spec_dict)

    # 4. Introspect schema (raises DatabaseConnectionError or
    # SchemaIntrospectionError on failure).
    snapshot = await connector.introspect_schema(spec_dict)

    # 5. Encrypt password.
    encrypted = encryptor.encrypt(spec.password.encode("utf-8"))
    password_b64 = base64.b64encode(encrypted).decode("ascii")

    # 6. Build payload.
    payload: dict[str, Any] = {
        "driver": spec.driver,
        "host": spec.host,
        "port": spec.port,
        "db_name": spec.db_name,
        "username": spec.username,
        "password_encrypted": password_b64,
        "ssl_mode": spec.ssl_mode,
        "schema_snapshot": snapshot.to_dict(),
    }

    # 7. Persist (the repo commits the new source row).
    source_id = await sources_repo.insert_database_source(
        kb_id=kb_id, payload=payload
    )

    return AttachDatabaseResult(
        source_id=source_id,
        snapshot_table_count=snapshot.table_count,
        snapshot_captured_at=snapshot.captured_at,
    )
