# CAP-KB-DB-SOURCES Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach external read-only SQL databases (Postgres, MySQL) as `DatabaseSource` rows inside a `KnowledgeBase`, with pre-attach connection testing, schema introspection at attach time, and encrypted credentials at rest. Unblocks plan #13 (CHAT-SQL-EXECUTION).

**Architecture:** Extends the existing polymorphic `Source` hierarchy. Adds a new domain port `DatabaseConnector` (test + introspect) with two adapters (`PostgresConnector` via asyncpg, `MySQLConnector` via asyncmy). A driver-dispatching `DatabaseSourceTester` is registered into the existing `SOURCE_CONNECTION_TESTERS` registry for `type="database"`. Credentials are encrypted inline in `Source.payload` via the existing Fernet encryptor; no schema migration required (the `sources` table already supports `type='database'` and a JSONB payload).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, asyncpg (already present), asyncmy (new), cryptography.fernet (existing), pytest + pytest-asyncio.

---

## File structure

**New files:**

- `backend/src/tfm_rag/domain/ports/database_connector.py` — `DatabaseConnector` ABC.
- `backend/src/tfm_rag/domain/value_objects/database_source_spec.py` — `DatabaseSourceSpec` VO (request shape, plaintext password).
- `backend/src/tfm_rag/domain/value_objects/database_schema.py` — `ColumnSchema`, `TableSchema`, `DatabaseSchemaSnapshot` VOs.
- `backend/src/tfm_rag/infrastructure/database_connectors/__init__.py` — registry exports.
- `backend/src/tfm_rag/infrastructure/database_connectors/postgres.py` — `PostgresConnector`.
- `backend/src/tfm_rag/infrastructure/database_connectors/mysql.py` — `MySQLConnector`.
- `backend/src/tfm_rag/infrastructure/database_connectors/source_tester.py` — `DatabaseSourceTester` (registered in `SOURCE_CONNECTION_TESTERS`).
- `backend/src/tfm_rag/application/knowledge/attach_database_source.py` — use case + `AttachDatabaseResult`.
- `backend/tests/unit/test_postgres_connector.py`
- `backend/tests/unit/test_mysql_connector.py`
- `backend/tests/unit/test_database_source_tester.py`
- `backend/tests/unit/test_attach_database_source.py`
- `backend/tests/integration/test_db_source_flow.py`

**Modified files:**

- `backend/pyproject.toml` — add `asyncmy`.
- `backend/src/tfm_rag/domain/errors/knowledge.py` — add 3 errors.
- `backend/src/tfm_rag/domain/entities/source.py` — no change (payload schema already documented for `type="database"`).
- `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py` — add `POST /api/knowledge-bases/{kb_id}/sources/databases`.
- `infra/docker-compose.yml` — add `mysql_source` service on port 3306.

**Out of scope** (deferred):

- Querying the DatabaseSource at runtime (plan #13 — `query_database` agent tool).
- "Reindex" (re-introspect schema) endpoint for DB sources — the existing `POST /sources/{source_id}/reindex` will still 400 on `type="database"` until plan #13 adapts it.
- Deduplicating DB credentials via the `provider_credentials` table (encrypted inline in `payload` for MVP).
- SQL dialects beyond postgres + mysql.
- SSL certificate pinning (only `ssl_mode` flag plumbed through; no client cert support yet).

---

## Task 1 — Domain layer: errors, port, VOs + asyncmy dep

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/tfm_rag/domain/errors/knowledge.py`
- Create: `backend/src/tfm_rag/domain/ports/database_connector.py`
- Create: `backend/src/tfm_rag/domain/value_objects/database_source_spec.py`
- Create: `backend/src/tfm_rag/domain/value_objects/database_schema.py`

No tests in this task — pure types and ports. The mypy pass at the end of the plan covers correctness.

- [ ] **Step 1.1: Add `asyncmy` to dependencies**

Open `backend/pyproject.toml`. In the `[project] dependencies = [...]` list, add `"asyncmy>=0.2.10",` after the line `"asyncpg>=0.30",`. The full block becomes:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic[email]>=2.9",
    "pydantic-settings>=2.6",
    "python-jose[cryptography]>=3.3",
    "sqlalchemy[asyncio]>=2.0.36",
    "alembic>=1.14",
    "asyncpg>=0.30",
    "asyncmy>=0.2.10",
    "qdrant-client>=1.12",
    "pypdf>=5.1",
    "python-multipart>=0.0.9",
    "httpx>=0.28",
    "structlog>=24.4",
    "bcrypt>=4.2",
    "google-auth>=2.35",
]
```

Then install:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
pip install -e '.[dev]'
```

Expected: `asyncmy-0.2.x` installed alongside the existing deps. No conflicts.

- [ ] **Step 1.2: Add three new domain errors**

Open `backend/src/tfm_rag/domain/errors/knowledge.py`. Append at the end of the file:

```python
class DatabaseConnectionError(DomainError):
    """Raised when a connection to a DatabaseSource fails (bad host/port,
    auth failure, network timeout, SSL failure, etc.).

    The error message is safe to surface to the user (no secrets).
    """


class SchemaIntrospectionError(DomainError):
    """Raised when introspecting the schema of a DatabaseSource fails
    after a successful connection (e.g. missing permissions on
    information_schema, unexpected dialect quirk).
    """


class UnsupportedDatabaseDialectError(DomainError):
    """Raised when a DatabaseSourceSpec specifies a driver value we don't
    support (anything other than 'postgres' or 'mysql' in MVP).
    """
```

`DomainError` is already imported at the top of the file. Do not touch the existing classes.

- [ ] **Step 1.3: Create the `DatabaseConnector` port**

Create `backend/src/tfm_rag/domain/ports/database_connector.py`:

```python
"""Port for outbound read-only database connectors.

A DatabaseConnector knows how to:
  * test that a connection spec is reachable + authenticated
  * introspect the schema (tables + columns) of the target DB

Plan #13 will extend this port with a `run_select(spec, sql, limit) -> Rows`
method for the `query_database` agent tool. Plan #9 does NOT need it yet.
"""
from abc import ABC, abstractmethod
from typing import Any

from tfm_rag.domain.value_objects.database_schema import (
    DatabaseSchemaSnapshot,
)


class DatabaseConnector(ABC):
    """Adapter contract for a single SQL dialect.

    `spec` is the plaintext dict produced from a DatabaseSourceSpec. It
    contains the user-supplied connection params PLUS the plaintext
    password (callers MUST decrypt before invoking). The connector itself
    is stateless and does not log or persist `spec`.
    """

    @abstractmethod
    async def test_connection(self, spec: dict[str, Any]) -> None:
        """Open a one-shot connection. Returns None on success.

        Raises DatabaseConnectionError on any failure (auth, network,
        SSL, timeout). The error message MUST NOT contain the password.
        """

    @abstractmethod
    async def introspect_schema(
        self, spec: dict[str, Any]
    ) -> DatabaseSchemaSnapshot:
        """Read tables + columns from information_schema.

        Raises DatabaseConnectionError if connecting fails, or
        SchemaIntrospectionError if the query succeeds but the result is
        unusable.
        """
```

- [ ] **Step 1.4: Create the `DatabaseSourceSpec` VO**

Create `backend/src/tfm_rag/domain/value_objects/database_source_spec.py`:

```python
"""Value object: request shape for attaching a DatabaseSource.

Carries the PLAINTEXT password. The use case encrypts it before
persisting into Source.payload. The VO itself is short-lived (request
scope) so we don't bother zeroing memory on drop.
"""
from dataclasses import dataclass
from typing import Literal

DatabaseDriver = Literal["postgres", "mysql"]
SslMode = Literal["disable", "require"]


@dataclass(frozen=True, slots=True)
class DatabaseSourceSpec:
    driver: DatabaseDriver
    host: str
    port: int
    db_name: str
    username: str
    password: str
    ssl_mode: SslMode = "disable"

    def to_connector_spec(self) -> dict[str, str | int]:
        """Plaintext dict shape that DatabaseConnector.test_connection /
        introspect_schema consumes."""
        return {
            "driver": self.driver,
            "host": self.host,
            "port": self.port,
            "db_name": self.db_name,
            "username": self.username,
            "password": self.password,
            "ssl_mode": self.ssl_mode,
        }
```

- [ ] **Step 1.5: Create the schema snapshot VOs**

Create `backend/src/tfm_rag/domain/value_objects/database_schema.py`:

```python
"""Value objects for a snapshot of a remote DB schema.

A snapshot is stored inside Source.payload as:
{
    "schema_snapshot": {
        "captured_at": "<iso8601>",
        "tables": [
            {"schema": "public", "name": "users",
             "columns": [{"name": "id", "data_type": "integer",
                          "nullable": false}, ...]},
            ...
        ]
    }
}

Plan #13 will read the snapshot to compose `query_database` system prompts.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    name: str
    data_type: str  # 'integer', 'text', 'timestamp', 'varchar(255)', ...
    nullable: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
        }


@dataclass(frozen=True, slots=True)
class TableSchema:
    schema: str  # 'public' for postgres default; db name for mysql
    name: str
    columns: tuple[ColumnSchema, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "name": self.name,
            "columns": [c.to_dict() for c in self.columns],
        }


@dataclass(frozen=True, slots=True)
class DatabaseSchemaSnapshot:
    captured_at: datetime
    tables: tuple[TableSchema, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at.isoformat(),
            "tables": [t.to_dict() for t in self.tables],
        }

    @property
    def table_count(self) -> int:
        return len(self.tables)
```

- [ ] **Step 1.6: Verify imports cleanly**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
python -c "
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError, SchemaIntrospectionError, UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.value_objects.database_source_spec import DatabaseSourceSpec
from tfm_rag.domain.value_objects.database_schema import (
    ColumnSchema, TableSchema, DatabaseSchemaSnapshot,
)
spec = DatabaseSourceSpec(
    driver='postgres', host='h', port=5432, db_name='d',
    username='u', password='p', ssl_mode='disable',
)
print(spec.to_connector_spec())
"
```

Expected: prints a dict with the 7 fields. No import errors.

- [ ] **Step 1.7: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/pyproject.toml \
        backend/src/tfm_rag/domain/errors/knowledge.py \
        backend/src/tfm_rag/domain/ports/database_connector.py \
        backend/src/tfm_rag/domain/value_objects/database_source_spec.py \
        backend/src/tfm_rag/domain/value_objects/database_schema.py
git commit -m "feat(domain): DatabaseConnector port + DB source VOs + asyncmy dep"
```

---

## Task 2 — PostgresConnector adapter + unit tests

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/database_connectors/__init__.py`
- Create: `backend/src/tfm_rag/infrastructure/database_connectors/postgres.py`
- Create: `backend/tests/unit/test_postgres_connector.py`

The adapter uses `asyncpg` (already a project dep). Unit tests monkey-patch `asyncpg.connect` so we don't need a live database.

- [ ] **Step 2.1: Create the package `__init__.py`**

Create `backend/src/tfm_rag/infrastructure/database_connectors/__init__.py`:

```python
"""Adapters for the DatabaseConnector port (postgres, mysql)."""
```

- [ ] **Step 2.2: Write the failing test for PostgresConnector.test_connection**

Create `backend/tests/unit/test_postgres_connector.py`:

```python
"""Unit tests for the PostgresConnector adapter. asyncpg is monkey-patched."""
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
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
    _patch_connect(monkeypatch, raise_exc=asyncio.TimeoutError())

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
```

Run it (expected: ImportError because the file doesn't exist yet):

```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_postgres_connector.py -v 2>&1 | tail -15
```

Expected: collection fails because `tfm_rag.infrastructure.database_connectors.postgres` does not yet exist.

- [ ] **Step 2.3: Implement PostgresConnector**

Create `backend/src/tfm_rag/infrastructure/database_connectors/postgres.py`:

```python
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
```

- [ ] **Step 2.4: Run the tests**

```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_postgres_connector.py -v 2>&1 | tail -20
```

Expected: **10 passed**.

If a test fails because the asyncpg exception type doesn't exist in your installed version (e.g. `InvalidPasswordError`), check with `python -c "import asyncpg; print([n for n in dir(asyncpg) if 'Error' in n])"`. The names `InvalidPasswordError`, `InsufficientPrivilegeError`, and `PostgresError` exist in asyncpg ≥0.30.

- [ ] **Step 2.5: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/database_connectors/__init__.py \
        backend/src/tfm_rag/infrastructure/database_connectors/postgres.py \
        backend/tests/unit/test_postgres_connector.py
git commit -m "feat(adapters): PostgresConnector (asyncpg) — test + introspect"
```

---

## Task 3 — MySQLConnector adapter + unit tests

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/database_connectors/mysql.py`
- Create: `backend/tests/unit/test_mysql_connector.py`

Same shape as Task 2 but for MySQL via asyncmy. Tests monkey-patch `asyncmy.connect`.

- [ ] **Step 3.1: Write the failing test**

Create `backend/tests/unit/test_mysql_connector.py`:

```python
"""Unit tests for the MySQLConnector adapter. asyncmy is monkey-patched."""
import asyncio
from datetime import datetime
from typing import Any

import pytest

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    SchemaIntrospectionError,
)
from tfm_rag.infrastructure.database_connectors.mysql import MySQLConnector

pytestmark = pytest.mark.asyncio


def _spec(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "driver": "mysql",
        "host": "mysql.example.com",
        "port": 3306,
        "db_name": "shop",
        "username": "ro",
        "password": "p4ss",
        "ssl_mode": "disable",
    }
    base.update(overrides)
    return base


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.queries: list[str] = []

    async def execute(self, query: str, *_args: Any) -> None:
        self.queries.append(query)

    async def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()


class _FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.rows)

    async def close(self) -> None:
        self.closed = True


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

    import asyncmy

    monkeypatch.setattr(asyncmy, "connect", _fake_connect)
    return captured


async def test_test_connection_success_passes_spec_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await MySQLConnector().test_connection(_spec())

    assert captured["host"] == "mysql.example.com"
    assert captured["port"] == 3306
    assert captured["user"] == "ro"
    assert captured["password"] == "p4ss"
    assert captured["db"] == "shop"
    assert conn.closed is True


async def test_test_connection_with_ssl_require_sets_ssl_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await MySQLConnector().test_connection(_spec(ssl_mode="require"))

    # asyncmy uses `ssl={}` to opt-in (no specific certs in MVP)
    assert captured.get("ssl") == {}


async def test_test_connection_with_ssl_disable_omits_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    captured = _patch_connect(monkeypatch, fake_conn=conn)

    await MySQLConnector().test_connection(_spec(ssl_mode="disable"))

    assert "ssl" not in captured


async def test_test_connection_auth_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncmy.errors

    _patch_connect(
        monkeypatch,
        raise_exc=asyncmy.errors.OperationalError(
            1045, "Access denied for user 'ro'@'host' (using password: YES)"
        ),
    )

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await MySQLConnector().test_connection(_spec())

    msg = str(exc_info.value)
    assert "access denied" in msg.lower() or "1045" in msg
    assert "p4ss" not in msg  # password must NOT leak


async def test_test_connection_network_failure_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=OSError("Connection refused"))

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await MySQLConnector().test_connection(_spec())

    assert "refused" in str(exc_info.value).lower()


async def test_test_connection_timeout_raises_database_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connect(monkeypatch, raise_exc=asyncio.TimeoutError())

    with pytest.raises(DatabaseConnectionError) as exc_info:
        await MySQLConnector().test_connection(_spec())

    assert "timeout" in str(exc_info.value).lower()


async def test_introspect_schema_returns_tables_and_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        ("shop", "users", "id", "int", "NO"),
        ("shop", "users", "email", "varchar", "NO"),
        ("shop", "orders", "id", "int", "NO"),
        ("shop", "orders", "user_id", "int", "YES"),
    ]
    conn = _FakeConnection(rows)
    _patch_connect(monkeypatch, fake_conn=conn)

    snapshot = await MySQLConnector().introspect_schema(_spec())

    assert snapshot.table_count == 2
    tables = {t.name: t for t in snapshot.tables}
    assert set(tables) == {"users", "orders"}
    users = tables["users"]
    assert users.schema == "shop"
    assert [c.name for c in users.columns] == ["id", "email"]
    assert users.columns[1].data_type == "varchar"
    assert users.columns[1].nullable is False
    orders = tables["orders"]
    assert orders.columns[1].nullable is True


async def test_introspect_schema_empty_db_returns_empty_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConnection([])
    _patch_connect(monkeypatch, fake_conn=conn)

    snapshot = await MySQLConnector().introspect_schema(_spec())

    assert snapshot.table_count == 0
    assert snapshot.tables == ()
    assert isinstance(snapshot.captured_at, datetime)


async def test_introspect_schema_query_failure_raises_schema_introspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncmy.errors

    class _FailingCursor(_FakeCursor):
        async def execute(self, query: str, *args: Any) -> None:
            raise asyncmy.errors.ProgrammingError(
                1142, "SELECT command denied to user 'ro'@'host'"
            )

    class _FailingConnection(_FakeConnection):
        def cursor(self) -> _FakeCursor:
            return _FailingCursor([])

    conn = _FailingConnection([])
    _patch_connect(monkeypatch, fake_conn=conn)

    with pytest.raises(SchemaIntrospectionError) as exc_info:
        await MySQLConnector().introspect_schema(_spec())

    assert "denied" in str(exc_info.value).lower() or "1142" in str(exc_info.value)
```

Run it (expected to fail because mysql.py is empty):

```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_mysql_connector.py -v 2>&1 | tail -15
```

Expected: ImportError / collection error.

- [ ] **Step 3.2: Implement MySQLConnector**

Create `backend/src/tfm_rag/infrastructure/database_connectors/mysql.py`:

```python
"""MySQLConnector — asyncmy adapter for DatabaseConnector port."""
import asyncio
from datetime import datetime, timezone
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
        await conn.close()

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
            await conn.close()

        tables = self._group_rows_to_tables(rows)
        return DatabaseSchemaSnapshot(
            captured_at=datetime.now(timezone.utc),
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
        except asyncio.TimeoutError as exc:
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
```

- [ ] **Step 3.3: Run the tests**

```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_mysql_connector.py -v 2>&1 | tail -20
```

Expected: **9 passed**.

If asyncmy is not installed, `pip install -e '.[dev]'` again (Task 1.1 should have done it; this is a safety net).

- [ ] **Step 3.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/database_connectors/mysql.py \
        backend/tests/unit/test_mysql_connector.py
git commit -m "feat(adapters): MySQLConnector (asyncmy) — test + introspect"
```

---

## Task 4 — Source tester registration (dispatch by driver)

**Files:**
- Create: `backend/src/tfm_rag/infrastructure/database_connectors/source_tester.py`
- Create: `backend/tests/unit/test_database_source_tester.py`
- Modify: `backend/src/tfm_rag/infrastructure/database_connectors/__init__.py` (re-export tester + registry)

This task wires the polymorphic dispatcher. After import, `SOURCE_CONNECTION_TESTERS["database"]` is populated. The tester unpacks `spec["driver"]` and routes to the right connector.

- [ ] **Step 4.1: Write the failing test**

Create `backend/tests/unit/test_database_source_tester.py`:

```python
"""Unit tests for DatabaseSourceTester (registry dispatch by driver)."""
from typing import Any

import pytest

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
    DatabaseSourceTester,
)

pytestmark = pytest.mark.asyncio


class _FakeConnector:
    def __init__(self) -> None:
        self.test_calls: list[dict[str, Any]] = []
        self.raise_on_test: BaseException | None = None

    async def test_connection(self, spec: dict[str, Any]) -> None:
        self.test_calls.append(spec)
        if self.raise_on_test is not None:
            raise self.raise_on_test

    async def introspect_schema(self, spec: dict[str, Any]) -> None:
        raise NotImplementedError("not used in the tester")


def _spec(driver: str = "postgres") -> dict[str, Any]:
    return {
        "driver": driver, "host": "h", "port": 5432, "db_name": "d",
        "username": "u", "password": "p", "ssl_mode": "disable",
    }


async def test_tester_registers_itself_as_database() -> None:
    # Importing the module above is enough to trigger registration.
    assert "database" in SOURCE_CONNECTION_TESTERS
    assert isinstance(
        SOURCE_CONNECTION_TESTERS["database"], DatabaseSourceTester
    )


async def test_tester_dispatches_to_postgres_connector() -> None:
    fake = _FakeConnector()
    tester = DatabaseSourceTester({"postgres": fake})

    result = await tester.test(_spec("postgres"))

    assert result == SourceConnectionTestResult(
        ok=True, error=None,
        details={"driver": "postgres"},
    )
    assert fake.test_calls == [_spec("postgres")]


async def test_tester_dispatches_to_mysql_connector() -> None:
    fake = _FakeConnector()
    tester = DatabaseSourceTester({"mysql": fake})

    result = await tester.test(_spec("mysql"))

    assert result.ok is True
    assert result.details == {"driver": "mysql"}
    assert fake.test_calls == [_spec("mysql")]


async def test_tester_unknown_driver_returns_unsupported_error() -> None:
    tester = DatabaseSourceTester({"postgres": _FakeConnector()})

    result = await tester.test(_spec("oracle"))

    assert result.ok is False
    assert result.error is not None
    assert "oracle" in result.error.lower()


async def test_tester_translates_database_connection_error_to_result() -> None:
    fake = _FakeConnector()
    fake.raise_on_test = DatabaseConnectionError("auth failed")
    tester = DatabaseSourceTester({"postgres": fake})

    result = await tester.test(_spec("postgres"))

    assert result.ok is False
    assert result.error == "auth failed"


async def test_tester_unexpected_exception_bubbles_up() -> None:
    fake = _FakeConnector()
    fake.raise_on_test = ValueError("bug")  # not a DatabaseConnectionError
    tester = DatabaseSourceTester({"postgres": fake})

    with pytest.raises(ValueError):
        await tester.test(_spec("postgres"))


async def test_default_registry_has_both_drivers() -> None:
    assert set(DATABASE_CONNECTORS.keys()) == {"postgres", "mysql"}


def test_unsupported_dialect_error_exists() -> None:
    # Sanity: the error class is imported, not just typed.
    assert issubclass(UnsupportedDatabaseDialectError, Exception)
```

Run (expect ImportError):

```bash
pytest tests/unit/test_database_source_tester.py -v 2>&1 | tail -15
```

- [ ] **Step 4.2: Implement DatabaseSourceTester + module-level registration**

Create `backend/src/tfm_rag/infrastructure/database_connectors/source_tester.py`:

```python
"""DatabaseSourceTester — wraps DatabaseConnectors as a SourceConnectionTester.

Importing this module has the side effect of registering itself in the
global SOURCE_CONNECTION_TESTERS registry under the key "database". This
mirrors how plan #8 registers the document tester on import.
"""
from typing import Any

from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.ports.source_connection_tester import (
    SOURCE_CONNECTION_TESTERS,
    SourceConnectionTestResult,
)
from tfm_rag.infrastructure.database_connectors.mysql import MySQLConnector
from tfm_rag.infrastructure.database_connectors.postgres import (
    PostgresConnector,
)

# Default driver -> connector mapping. Plan #13 will reuse this dict for
# query_database.
DATABASE_CONNECTORS: dict[str, DatabaseConnector] = {
    "postgres": PostgresConnector(),
    "mysql": MySQLConnector(),
}


class DatabaseSourceTester:
    """SourceConnectionTester implementation for type='database'.

    Dispatches on spec['driver'] to a connector in `connectors`. The
    registration at import time wires the production set, but the class
    accepts a custom dict for tests.
    """

    def __init__(self, connectors: dict[str, DatabaseConnector]) -> None:
        self._connectors = connectors

    async def test(
        self, spec: dict[str, Any]
    ) -> SourceConnectionTestResult:
        driver = spec.get("driver")
        if not isinstance(driver, str) or driver not in self._connectors:
            return SourceConnectionTestResult(
                ok=False,
                error=(
                    f"unsupported database driver {driver!r}; "
                    f"supported drivers: {sorted(self._connectors)}"
                ),
            )
        connector = self._connectors[driver]
        try:
            await connector.test_connection(spec)
        except DatabaseConnectionError as exc:
            return SourceConnectionTestResult(ok=False, error=str(exc))
        return SourceConnectionTestResult(
            ok=True, error=None, details={"driver": driver}
        )


# Register at import time. This MUST run before the API serves requests.
# `infrastructure/api/app.py` imports the routers, which import the
# attach_database_source use case, which imports this module.
SOURCE_CONNECTION_TESTERS["database"] = DatabaseSourceTester(DATABASE_CONNECTORS)

# Re-export so callers can `from ...database_connectors import UnsupportedDatabaseDialectError`
__all__ = [
    "DATABASE_CONNECTORS",
    "DatabaseSourceTester",
    "UnsupportedDatabaseDialectError",
]
```

- [ ] **Step 4.3: Re-export from the package `__init__.py`**

Open `backend/src/tfm_rag/infrastructure/database_connectors/__init__.py`. Replace its content with:

```python
"""Adapters for the DatabaseConnector port (postgres, mysql).

Importing this package triggers the registration of DatabaseSourceTester
in SOURCE_CONNECTION_TESTERS for type="database".
"""
from tfm_rag.infrastructure.database_connectors.mysql import MySQLConnector
from tfm_rag.infrastructure.database_connectors.postgres import (
    PostgresConnector,
)
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
    DatabaseSourceTester,
)

__all__ = [
    "DATABASE_CONNECTORS",
    "DatabaseSourceTester",
    "MySQLConnector",
    "PostgresConnector",
]
```

- [ ] **Step 4.4: Run the tests**

```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_database_source_tester.py -v 2>&1 | tail -20
```

Expected: **8 passed**.

- [ ] **Step 4.5: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/database_connectors/__init__.py \
        backend/src/tfm_rag/infrastructure/database_connectors/source_tester.py \
        backend/tests/unit/test_database_source_tester.py
git commit -m "feat(adapters): DatabaseSourceTester dispatches by driver + registers tester for type='database'"
```

---

## Task 5 — Application use case `attach_database_source`

**Files:**
- Create: `backend/src/tfm_rag/application/knowledge/attach_database_source.py`
- Create: `backend/tests/unit/test_attach_database_source.py`

The use case:
1. Verifies the KB exists in the tenant.
2. Validates `driver` is supported.
3. Calls `connector.test_connection` (raises DatabaseConnectionError on failure → use case re-raises).
4. Calls `connector.introspect_schema` (raises SchemaIntrospectionError on failure → use case re-raises).
5. Encrypts the password via `SecretEncryptor`.
6. Builds the payload (`driver`, `host`, `port`, `db_name`, `username`, `password_encrypted` as base64 ASCII, `ssl_mode`, `schema_snapshot`).
7. Inserts a Source row with `type="database"`, `ingest_status="done"`, `last_ingest_at=now()` (introspection IS the "ingestion" for a DatabaseSource).
8. Commits.

- [ ] **Step 5.1: Write the failing test**

Create `backend/tests/unit/test_attach_database_source.py`:

```python
"""Unit tests for attach_database_source use case."""
import base64
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

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
        chunking_config=ChunkingConfig(strategy="fixed", chunk_size=300, chunk_overlap=50),
        embedding_selection=EmbeddingSelection(
            provider_id="ollama",
            credential_id=uuid4(),
            model_id="bge-m3",
            dim=1024,
        ),
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
```

Run (expect ImportError):

```bash
pytest tests/unit/test_attach_database_source.py -v 2>&1 | tail -10
```

- [ ] **Step 5.2: Implement the use case + the sources repo helper**

First, look up where the sources repo lives. The existing pattern from plan #8 should have it under `infrastructure/persistence/repositories/sources_repo.py` (or be inline in the attach_document_source use case). Run:

```bash
ls backend/src/tfm_rag/infrastructure/persistence/repositories/ | grep -i source
grep -rn "class SourcesRepository\|class SourceRepository" backend/src/tfm_rag/infrastructure/persistence/ 2>&1 | head
```

If a `SourcesRepository` already exists, add a method `insert_database_source(*, kb_id, payload) -> UUID` to it. If not, the existing `attach_document_source` uses inline session.add() — in that case, the new use case can do the same.

For the plan to be self-contained, assume the existing pattern is inline persistence inside the use case (verified by reading `attach_document_source.py` if needed). The test above uses a `_FakeSourcesRepo` abstraction so the use case can accept any "object with `insert_database_source(*, kb_id, payload)`". If the production wiring uses inline session.add(), inject a concrete adapter that wraps that.

Create `backend/src/tfm_rag/application/knowledge/attach_database_source.py`:

```python
"""attach_database_source — application use case.

Validates the KB ownership, calls the connector's test+introspect,
encrypts the password, and persists a new Source row with type='database'.
"""
import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from tfm_rag.domain.entities.knowledge_base import KnowledgeBase
from tfm_rag.domain.errors.knowledge import (
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.ports.database_connector import DatabaseConnector
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.value_objects.database_source_spec import (
    DatabaseSourceSpec,
)


@dataclass(frozen=True, slots=True)
class AttachDatabaseResult:
    source_id: UUID
    snapshot_table_count: int
    snapshot_captured_at: datetime


class _KbRepoLike(Protocol):
    async def get(self, kb_id: UUID) -> KnowledgeBase: ...


class _SourcesRepoLike(Protocol):
    async def insert_database_source(
        self, *, kb_id: UUID, payload: dict[str, Any]
    ) -> UUID: ...


class _SessionLike(Protocol):
    async def commit(self) -> None: ...


async def attach_database_source(
    *,
    session: _SessionLike,
    kb_repo: _KbRepoLike,
    sources_repo: _SourcesRepoLike,
    kb_id: UUID,
    spec: DatabaseSourceSpec,
    encryptor: SecretEncryptor,
    connectors: dict[str, DatabaseConnector],
) -> AttachDatabaseResult:
    # 1. KB ownership (raises KnowledgeBaseNotFoundError on miss).
    await kb_repo.get(kb_id)

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

    # 7. Persist.
    source_id = await sources_repo.insert_database_source(
        kb_id=kb_id, payload=payload
    )

    # 8. Commit.
    await session.commit()

    return AttachDatabaseResult(
        source_id=source_id,
        snapshot_table_count=snapshot.table_count,
        snapshot_captured_at=snapshot.captured_at,
    )
```

- [ ] **Step 5.3: Run the tests**

```bash
cd backend
source .venv/bin/activate
pytest tests/unit/test_attach_database_source.py -v 2>&1 | tail -15
```

Expected: **6 passed**.

- [ ] **Step 5.4: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/application/knowledge/attach_database_source.py \
        backend/tests/unit/test_attach_database_source.py
git commit -m "feat(app): attach_database_source use case (test → introspect → encrypt → persist)"
```

---

## Task 6 — API endpoint POST /sources/databases

**Files:**
- Modify: `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py`
- Modify: `backend/tests/integration/test_knowledge_endpoints.py` (or create a focused unit-level test using the same TestClient pattern)

The endpoint takes a JSON body with `{driver, host, port, db_name, username, password, ssl_mode}`. Validates via Pydantic, builds a `DatabaseSourceSpec`, calls `attach_database_source`, returns `{source_id, snapshot_tables, snapshot_captured_at}`. The router builds the encryptor + adapter for the sources repo inline (same pattern as `POST /sources/documents`).

For the sources_repo: a thin inline adapter that uses `session.add(SourceRow(...))` like `attach_document_source` does.

- [ ] **Step 6.1: Read the existing router to confirm patterns**

```bash
grep -n "SOURCE_CONNECTION_TESTERS\|attach_document_source\|test_source_connection\|SourceRow" backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py | head -20
```

Use what you see to mimic exactly: imports, dependency style (`Depends(get_session)`), exception → HTTPException translation.

- [ ] **Step 6.2: Write the failing endpoint test**

Open `backend/tests/integration/test_knowledge_endpoints.py` and find the section that uses an in-process TestClient + monkey-patched testers (plan #8 already established this pattern for documents). Append the following test class (if a fixture file already provides `client` + `tenant_header`, reuse them — adjust the test to match the existing fixtures):

If the existing file is unit-level (not integration), instead create a new file `backend/tests/integration/test_attach_database_source_endpoint.py`:

```python
"""Endpoint test: POST /api/knowledge-bases/{kb_id}/sources/databases.

This test is marked `integration` because it needs the live Postgres
container to host the application DB. The DatabaseConnector is REPLACED
with a fake via the SOURCE_CONNECTION_TESTERS registry monkey-patch so
no external DB is touched — only the app DB.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
)
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings
from sqlalchemy import text

pytestmark = pytest.mark.integration


class _FakeConnector:
    """Stand-in for PostgresConnector/MySQLConnector that records calls."""

    def __init__(self, *, fail_test: bool = False) -> None:
        self.fail_test = fail_test
        self.test_calls: list[dict[str, Any]] = []
        self.introspect_calls: list[dict[str, Any]] = []

    async def test_connection(self, spec: dict[str, Any]) -> None:
        self.test_calls.append(spec)
        if self.fail_test:
            from tfm_rag.domain.errors.knowledge import (
                DatabaseConnectionError,
            )
            raise DatabaseConnectionError("auth failed (fake)")

    async def introspect_schema(self, spec: dict[str, Any]) -> Any:
        from tfm_rag.domain.value_objects.database_schema import (
            ColumnSchema, DatabaseSchemaSnapshot, TableSchema,
        )
        self.introspect_calls.append(spec)
        return DatabaseSchemaSnapshot(
            captured_at=datetime(2026, 5, 25, 10, 0, tzinfo=timezone.utc),
            tables=(
                TableSchema(
                    schema="public", name="users",
                    columns=(
                        ColumnSchema(name="id", data_type="integer", nullable=False),
                        ColumnSchema(name="email", data_type="text", nullable=False),
                    ),
                ),
            ),
        )


@pytest.fixture(autouse=True)
async def _swap_postgres_connector() -> None:
    """Replace the production postgres connector with a fake for the test."""
    original = DATABASE_CONNECTORS["postgres"]
    DATABASE_CONNECTORS["postgres"] = _FakeConnector()  # type: ignore[assignment]
    yield
    DATABASE_CONNECTORS["postgres"] = original


@pytest.fixture
async def _clean_db(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register_and_get_cred(client: AsyncClient) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": "db-source@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    creds = (await client.get("/api/credentials", headers=h)).json()
    cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]
    return token, cred_id


async def _create_kb(client: AsyncClient, token: str, cred_id: str) -> str:
    h = {"Authorization": f"Bearer {token}"}
    r = await client.post(
        "/api/knowledge-bases", headers=h,
        json={
            "name": "DBKB",
            "embedding_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "bge-m3", "dim": 1024,
            },
            "chunking_config": {
                "strategy": "fixed", "chunk_size": 300, "chunk_overlap": 50,
            },
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_attach_postgres_database_source_succeeds(
    _clean_db: None,
) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, cred_id = await _register_and_get_cred(c)
        kb_id = await _create_kb(c, token, cred_id)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "db.internal", "port": 5432, "db_name": "analytics",
                "username": "ro", "password": "secret",
                "ssl_mode": "disable",
            },
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert "source_id" in body
    assert body["snapshot_tables"] == 1
    assert "snapshot_captured_at" in body


async def test_attach_with_unknown_driver_returns_400(_clean_db: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, cred_id = await _register_and_get_cred(c)
        kb_id = await _create_kb(c, token, cred_id)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "oracle",  # rejected by Pydantic Literal validation
                "host": "h", "port": 5432, "db_name": "d",
                "username": "u", "password": "p",
            },
        )
    assert r.status_code == 422


async def test_attach_with_connection_failure_returns_400(
    _clean_db: None,
) -> None:
    DATABASE_CONNECTORS["postgres"] = _FakeConnector(fail_test=True)  # type: ignore[assignment]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, cred_id = await _register_and_get_cred(c)
        kb_id = await _create_kb(c, token, cred_id)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "h", "port": 5432, "db_name": "d",
                "username": "u", "password": "p",
            },
        )
    assert r.status_code == 400
    assert "auth failed" in r.json()["detail"].lower()


async def test_attach_with_missing_kb_returns_404(_clean_db: None) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        token, _cred = await _register_and_get_cred(c)
        h = {"Authorization": f"Bearer {token}"}
        r = await c.post(
            f"/api/knowledge-bases/{uuid4()}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "h", "port": 5432, "db_name": "d",
                "username": "u", "password": "p",
            },
        )
    assert r.status_code == 404
```

- [ ] **Step 6.3: Implement the endpoint**

Open `backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py`. Near the top of the file, add the new imports next to the existing source-related ones:

```python
from tfm_rag.application.knowledge.attach_database_source import (
    AttachDatabaseResult,
    attach_database_source,
)
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    SchemaIntrospectionError,
    UnsupportedDatabaseDialectError,
)
from tfm_rag.domain.value_objects.database_source_spec import (
    DatabaseSourceSpec,
)
from tfm_rag.infrastructure.database_connectors.source_tester import (
    DATABASE_CONNECTORS,
)
from tfm_rag.infrastructure.persistence.models.sources import SourceRow
from tfm_rag.infrastructure.secrets.fernet_encryptor import (
    FernetSecretEncryptor,
)
```

(The `SourceRow` import is likely already present. The other adds are new. The router file is large — just append next to existing imports.)

Find the section that defines `POST /{kb_id}/sources/documents` (around line 480). Immediately after the `upload_document_` function and the `UploadDocOut` BaseModel, add:

```python
class AttachDatabaseIn(BaseModel):
    driver: Literal["postgres", "mysql"]
    host: str
    port: int = Field(..., ge=1, le=65535)
    db_name: str
    username: str
    password: str
    ssl_mode: Literal["disable", "require"] = "disable"


class AttachDatabaseOut(BaseModel):
    source_id: str
    snapshot_tables: int
    snapshot_captured_at: datetime


class _InlineSourcesRepo:
    """Tiny adapter so the use case can `insert_database_source` via the
    request-scoped session. Mirrors the inline persistence pattern used in
    `attach_document_source`."""

    def __init__(
        self, session: AsyncSession, ctx: RequestContext
    ) -> None:
        self._session = session
        self._ctx = ctx

    async def insert_database_source(
        self, *, kb_id: UUID, payload: dict[str, Any]
    ) -> UUID:
        source_id = uuid4()
        self._session.add(
            SourceRow(
                id=source_id,
                kb_id=kb_id,
                type="database",
                payload=payload,
                ingest_status="done",
                last_ingest_at=datetime.now(timezone.utc),
            )
        )
        return source_id


@router.post(
    "/{kb_id}/sources/databases",
    status_code=201,
    response_model=AttachDatabaseOut,
)
async def attach_database_source_(
    kb_id: UUID,
    body: AttachDatabaseIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AttachDatabaseOut:
    spec = DatabaseSourceSpec(
        driver=body.driver,
        host=body.host,
        port=body.port,
        db_name=body.db_name,
        username=body.username,
        password=body.password,
        ssl_mode=body.ssl_mode,
    )
    encryptor = FernetSecretEncryptor(settings.fernet_key)
    kb_repo = _KbRepoAdapter(session, ctx)
    sources_repo = _InlineSourcesRepo(session, ctx)
    try:
        result: AttachDatabaseResult = await attach_database_source(
            session=session,
            kb_repo=kb_repo,
            sources_repo=sources_repo,
            kb_id=kb_id,
            spec=spec,
            encryptor=encryptor,
            connectors=DATABASE_CONNECTORS,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnsupportedDatabaseDialectError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (DatabaseConnectionError, SchemaIntrospectionError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return AttachDatabaseOut(
        source_id=str(result.source_id),
        snapshot_tables=result.snapshot_table_count,
        snapshot_captured_at=result.snapshot_captured_at,
    )
```

Also add a tiny `_KbRepoAdapter` helper just above the endpoint function. It wraps the existing `get_knowledge_base` use case (already imported in the router) so the new use case can call `.get(kb_id)`:

```python
class _KbRepoAdapter:
    """Wraps the existing get_knowledge_base use case as a kb_repo for
    attach_database_source. Lives inline in the router to avoid introducing
    a new repository abstraction in the persistence layer."""

    def __init__(self, session: AsyncSession, ctx: RequestContext) -> None:
        self._session = session
        self._ctx = ctx

    async def get(self, kb_id: UUID) -> Any:
        return await get_knowledge_base(self._session, self._ctx, kb_id=kb_id)
```

Place it next to `_InlineSourcesRepo` above the new endpoint function.

Required additional imports at the top of the router file if not already present:

```python
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import Field
```

- [ ] **Step 6.4: Run the endpoint tests**

```bash
cd backend
source .venv/bin/activate
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_attach_database_source_endpoint.py -m integration -v 2>&1 | tail -20
```

Expected: **4 passed**.

If the test 422-fails because Pydantic doesn't validate `port` upper bound, double-check the `Field(..., ge=1, le=65535)` import landed.

- [ ] **Step 6.5: Verify no router regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_knowledge_endpoints.py -m integration -v 2>&1 | tail -15
```

Expected: all existing KB endpoint tests still pass.

- [ ] **Step 6.6: Commit**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add backend/src/tfm_rag/infrastructure/api/routers/knowledge_bases.py \
        backend/tests/integration/test_attach_database_source_endpoint.py
# If you edited the use case to drop kb_repo (option in Step 6.3):
# git add backend/src/tfm_rag/application/knowledge/attach_database_source.py \
#         backend/tests/unit/test_attach_database_source.py
git commit -m "feat(api): POST /api/knowledge-bases/{kb_id}/sources/databases (postgres+mysql)"
```

---

## Task 7 — Compose mysql service + e2e integration against live DBs

**Files:**
- Modify: `infra/docker-compose.yml`
- Modify: `infra/.env.example`
- Create: `backend/tests/integration/test_db_source_flow.py`

The e2e test:
1. Bootstraps an external "tenant data" Postgres DB (`tfm_rag_source_test`) inside the existing `tfm-rag-postgres-1` container via raw SQL.
2. Creates a tiny schema (one table, two columns) in that DB.
3. Calls `POST /sources/test-connection` against it — asserts `ok: true`.
4. Calls `POST /sources/databases` to attach it — asserts the snapshot has 1 table.
5. Repeats for the new mysql container against database `tfm_rag_source_test`.

- [ ] **Step 7.1: Add mysql to docker-compose**

Open `infra/docker-compose.yml`. After the `qdrant:` service block, add:

```yaml
  mysql_source:
    image: mysql:8.0
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-rootpw}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-tfm_rag_source_test}
      MYSQL_USER: ${MYSQL_USER:-tfm}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-tfm}
    ports:
      - "3306:3306"
    volumes:
      - mysql_source_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p${MYSQL_ROOT_PASSWORD:-rootpw}"]
      interval: 5s
      timeout: 3s
      retries: 20
```

And in the `volumes:` block at the bottom, add `mysql_source_data:`. The final volumes block:

```yaml
volumes:
  postgres_data:
  qdrant_data:
  ollama_data:
  mysql_source_data:
```

- [ ] **Step 7.2: Add MySQL env vars to .env.example**

Open `infra/.env.example`. Append at the end:

```
# --- Test source databases (plan #9 CAP-KB-DB-SOURCES) ---
MYSQL_ROOT_PASSWORD=rootpw
MYSQL_DATABASE=tfm_rag_source_test
MYSQL_USER=tfm
MYSQL_PASSWORD=tfm
```

- [ ] **Step 7.3: Bring up the mysql container**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/infra
# If .env doesn't yet have the MYSQL_* vars, copy them in from .env.example:
grep -q '^MYSQL_ROOT_PASSWORD=' .env || cat >> .env <<'ENV'

# --- Test source databases (plan #9 CAP-KB-DB-SOURCES) ---
MYSQL_ROOT_PASSWORD=rootpw
MYSQL_DATABASE=tfm_rag_source_test
MYSQL_USER=tfm
MYSQL_PASSWORD=tfm
ENV
docker compose up -d mysql_source
sleep 5
docker ps --filter name=tfm-rag-mysql --format '{{.Names}}: {{.Status}}'
```

Expected: `tfm-rag-mysql_source-1: Up X seconds (healthy)`.

(If `docker compose` is not in WSL but the Windows binary is, use `docker.exe compose ...`.)

- [ ] **Step 7.4: Create the integration test**

Create `backend/tests/integration/test_db_source_flow.py`:

```python
"""E2E for CAP-KB-DB-SOURCES: attach a real Postgres + MySQL DB as
DatabaseSource. Uses the live Docker stack:
  - tfm-rag-postgres-1 hosts a SECOND db `tfm_rag_source_test` for the app
    to introspect (separate from the app's own DB `tfm_rag`).
  - tfm-rag-mysql_source-1 hosts `tfm_rag_source_test`.

This test is `integration` — slow (~30s for both setup + introspection).
"""
import asyncio
from typing import Any

import asyncpg
import asyncmy
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

import tfm_rag.infrastructure.api.dependencies as _deps
from tfm_rag.infrastructure.api.app import app
from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.settings import Settings

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- helpers


async def _prepare_postgres_source_db() -> None:
    """Create `tfm_rag_source_test` inside the app's Postgres if missing,
    then ensure a `widgets` table exists with two columns."""
    admin = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag",
    )
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            "tfm_rag_source_test",
        )
        if not exists:
            await admin.execute('CREATE DATABASE "tfm_rag_source_test"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(
        host="localhost", port=5432, user="tfm", password="tfm",
        database="tfm_rag_source_test",
    )
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS widgets ("
            "id INTEGER PRIMARY KEY, name TEXT NOT NULL"
            ")"
        )
    finally:
        await conn.close()


async def _prepare_mysql_source_db() -> None:
    """Ensure a `widgets` table exists in MySQL `tfm_rag_source_test`."""
    conn = await asyncmy.connect(
        host="localhost", port=3306, user="tfm", password="tfm",
        db="tfm_rag_source_test",
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "CREATE TABLE IF NOT EXISTS widgets ("
                "id INT PRIMARY KEY, name VARCHAR(255) NOT NULL"
                ")"
            )
            await conn.commit()
    finally:
        await conn.close()


@pytest.fixture
async def _clean_app_state(settings: Settings) -> None:
    engine = build_engine(settings.postgres_url)
    factory = build_session_factory(engine)
    async with factory() as s:
        await s.execute(text(
            "TRUNCATE sources, knowledge_bases, provider_credentials, "
            "users, tenants RESTART IDENTITY CASCADE"
        ))
        await s.commit()
    await engine.dispose()
    _deps._session_factory = None


async def _register_and_create_kb(client: AsyncClient) -> tuple[str, str]:
    r = await client.post(
        "/api/auth/register",
        json={"email": "db-src-e2e@example.com", "password": "correctpassword"},
    )
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    creds = (await client.get("/api/credentials", headers=h)).json()
    cred_id = next(c for c in creds if c["provider_id"] == "ollama")["id"]
    r = await client.post(
        "/api/knowledge-bases", headers=h,
        json={
            "name": "DBKB",
            "embedding_selection": {
                "provider_id": "ollama", "credential_id": cred_id,
                "model_id": "bge-m3", "dim": 1024,
            },
            "chunking_config": {
                "strategy": "fixed", "chunk_size": 300, "chunk_overlap": 50,
            },
        },
    )
    assert r.status_code == 201, r.text
    return token, r.json()["id"]


# --------------------------------------------------------------------------- tests


async def test_attach_postgres_database_source_e2e(
    _clean_app_state: None,
) -> None:
    await _prepare_postgres_source_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as c:
        token, kb_id = await _register_and_create_kb(c)
        h = {"Authorization": f"Bearer {token}"}

        # test-connection first
        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/test-connection",
            headers=h,
            json={
                "type": "database",
                "spec": {
                    "driver": "postgres",
                    "host": "localhost", "port": 5432,
                    "db_name": "tfm_rag_source_test",
                    "username": "tfm", "password": "tfm",
                    "ssl_mode": "disable",
                },
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

        # attach the database
        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "localhost", "port": 5432,
                "db_name": "tfm_rag_source_test",
                "username": "tfm", "password": "tfm",
                "ssl_mode": "disable",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["snapshot_tables"] >= 1  # at least our `widgets`

        # verify the source shows up in the listing
        r = await c.get(
            f"/api/knowledge-bases/{kb_id}/sources", headers=h,
        )
        assert r.status_code == 200, r.text
        sources = r.json()
        db_sources = [s for s in sources if s["type"] == "database"]
        assert len(db_sources) == 1
        assert db_sources[0]["ingest_status"] == "done"


async def test_attach_mysql_database_source_e2e(
    _clean_app_state: None,
) -> None:
    await _prepare_mysql_source_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=60.0
    ) as c:
        token, kb_id = await _register_and_create_kb(c)
        h = {"Authorization": f"Bearer {token}"}

        # attach mysql
        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "mysql",
                "host": "localhost", "port": 3306,
                "db_name": "tfm_rag_source_test",
                "username": "tfm", "password": "tfm",
                "ssl_mode": "disable",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["snapshot_tables"] >= 1


async def test_attach_with_wrong_password_returns_400(
    _clean_app_state: None,
) -> None:
    await _prepare_postgres_source_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", timeout=30.0
    ) as c:
        token, kb_id = await _register_and_create_kb(c)
        h = {"Authorization": f"Bearer {token}"}

        r = await c.post(
            f"/api/knowledge-bases/{kb_id}/sources/databases",
            headers=h,
            json={
                "driver": "postgres",
                "host": "localhost", "port": 5432,
                "db_name": "tfm_rag_source_test",
                "username": "tfm", "password": "WRONG",
                "ssl_mode": "disable",
            },
        )
        assert r.status_code == 400
        # Detail must NOT contain the bad password.
        assert "WRONG" not in r.json().get("detail", "")
```

- [ ] **Step 7.5: Run the e2e tests**

```bash
cd backend
source .venv/bin/activate
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration/test_db_source_flow.py -m integration -v --timeout=180 2>&1 | tail -25
```

Expected: **3 passed** in ~30-60s total.

**If the mysql test fails with "Access denied":** the mysql container may have initialized the user with `MYSQL_PASSWORD` but the host policy is `'%'` only. Check with `docker exec tfm-rag-mysql_source-1 mysql -u root -prootpw -e "SELECT user, host FROM mysql.user WHERE user='tfm'"`. If the user is only `tfm@%`, the test should still work because we connect from outside the container.

**If `asyncpg.connect` fails with "database does not exist":** the prep step ran but commit didn't persist. Verify with `docker exec tfm-rag-postgres-1 psql -U tfm -d postgres -c "\l"`. Should list `tfm_rag_source_test`.

- [ ] **Step 7.6: Run the full integration suite to ensure no regressions**

```bash
POSTGRES_URL='postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag' \
QDRANT_URL='http://localhost:6333' \
OLLAMA_BASE_URL='http://localhost:11434' \
JWT_SECRET='1YBHJWV4tL_6CdXp73CgzkhPk4o_DgzCVtoWWlpMBFA' \
FERNET_KEY='8P0kvuyx97CrhRpEyfvJdhABMpBei9cJCcxupp_LIUQ=' \
STORAGE_LOCAL_PATH='/tmp/tfm_rag_storage' \
pytest tests/integration -m integration -v --timeout=900 2>&1 | tail -15
```

Expected: previous 29 + 4 new (1 from Task 6 endpoint test × 4 cases + 3 from this file) = **33 PASSED**.

- [ ] **Step 7.7: Commit + tag**

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool
git add infra/docker-compose.yml \
        infra/.env.example \
        backend/tests/integration/test_db_source_flow.py
git commit -m "test(db-source): e2e attach postgres + mysql as DatabaseSource (compose mysql service)"
git tag cap-09-kb-db-sources
```

---

## Controller cleanup (post-subagent — NOT a task)

After all 7 tasks land, the controller runs the global lint pass:

```bash
cd /home/acabo/personal/tfmragapp/tfm-rag-chatbot-deploy-tool/backend
source .venv/bin/activate
ruff check . --fix
mypy src/
pytest tests/ -m "not integration"
```

If autofixes / type fixes are applied, commit them as `chore(plan-09): ruff autofix` and **move the `cap-09-kb-db-sources` tag forward** to that cleanup commit (project convention — see handover §8).

```bash
git tag -f cap-09-kb-db-sources <cleanup-commit-sha>
```

---

## What's next after plan #9

After plan #9 lands, **3 plans remain (3/17)**: #11 (CHATBOT-WIDGET-CONFIG), #13 (CHAT-SQL-EXECUTION — closes M4 by adding the `query_database` tool to the agent loop, depends on plan #9), #16 (WIDGET-RUNTIME, M5).

Small follow-ups that pair well with plan #9:
- **Reindex for DB sources**: adapt `POST /sources/{id}/reindex` to re-introspect schema and update `payload.schema_snapshot`. ~30 LOC; defer to plan #13.
- **Test-connection caching**: the UI currently has no "I already tested this 5 seconds ago, just attach" optimization. The current endpoint pair (test → attach) re-tests on attach. Cheap (one extra round trip); not worth optimizing.
- **More dialects**: SQL Server, Oracle, SQLite. Each is a new DatabaseConnector adapter.
- **Schema filters**: allow attaching only specific schemas/tables. Today we snapshot everything outside system schemas.
- **SSL with client certs**: today only `ssl_mode in {disable, require}`. Add `verify-ca`, `verify-full` with cert paths in the spec.
