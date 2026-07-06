import os
from pathlib import Path

# Set env defaults BEFORE importing any tfm_rag modules so that pydantic
# Settings validation does not fail during test collection.
os.environ.setdefault("POSTGRES_URL", "postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("JWT_SECRET", "x" * 32)
os.environ.setdefault("FERNET_KEY", "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=")
os.environ.setdefault("STORAGE_LOCAL_PATH", "/tmp/tfm_rag_storage")

import pytest

from tfm_rag.infrastructure.settings import Settings

_INTEGRATION_DIR = Path(__file__).parent / "integration"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Safety gate for destructive integration tests.

    Integration tests TRUNCATE the database they point at, and POSTGRES_URL
    defaults to the local *dev* DB (see top of this file). Running them by
    accident — e.g. ``pytest tests/integration/...`` to verify one fix — wipes
    real dev data (users, KBs, chatbots, eval datasets) via TRUNCATE … CASCADE.

    To make that impossible by accident:

    1. Every item collected from *any* file under ``tests/integration/`` is
       auto-marked ``integration``, whether or not the file itself carries
       ``@pytest.mark.integration``/``pytestmark``. This closes the gap where
       a file simply forgets the marker and silently evades the gate below.
    2. Every ``integration``-marked test is then SKIPPED unless
       ``TFM_RUN_INTEGRATION=1`` is explicitly set. CI and intentional local
       runs opt in; casual/agent runs do not.
    """
    for item in items:
        item_path = Path(str(item.path if hasattr(item, "path") else item.fspath))
        if item_path.is_relative_to(_INTEGRATION_DIR):
            item.add_marker(pytest.mark.integration)

    if os.environ.get("TFM_RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(
        reason="destructive integration test (TRUNCATEs the DB); "
        "set TFM_RUN_INTEGRATION=1 to run"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings from the running environment (.env or docker-compose env)."""
    # Defaults for local dev if not set; integration tests expect compose up
    monkeypatch.setenv(
        "POSTGRES_URL",
        os.environ.get(
            "POSTGRES_URL",
            "postgresql+asyncpg://tfm:tfm@localhost:5432/tfm_rag",
        ),
    )
    monkeypatch.setenv(
        "QDRANT_URL",
        os.environ.get("QDRANT_URL", "http://localhost:6333"),
    )
    monkeypatch.setenv(
        "OLLAMA_BASE_URL",
        os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv(
        "FERNET_KEY", "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="
    )
    monkeypatch.setenv(
        "STORAGE_LOCAL_PATH",
        os.environ.get("STORAGE_LOCAL_PATH", "/tmp/tfm_rag_storage"),
    )
    return Settings()  # type: ignore[call-arg]
