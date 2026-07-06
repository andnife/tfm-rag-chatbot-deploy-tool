"""Unit tests for judge credential resolution in the entity eval run path.

The judge is now always credential-first: resolve_inference_target is always
called with judge_credential_id (required). There is no env/base_url fallback.

We test the resolver logic directly using the same fake repo/encryptor pattern as
test_endpoint_resolver.py; we don't spin up FastAPI or a DB connection.
"""
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.infrastructure.evaluation.ragas_evaluator import RagasEvaluator


@dataclass
class _Row:
    api_key_encrypted: bytes
    base_url: str | None
    provider_id: str = "openai_compat"


class _FakeRepo:
    def __init__(self, row: _Row | None) -> None:
        self._row = row
        self.called = False

    async def get_credential(self, credential_id: UUID) -> _Row:
        self.called = True
        assert self._row is not None
        return self._row


class _FakeEncryptor:
    def decrypt(self, ciphertext: bytes) -> bytes:
        return ciphertext


# ---------------------------------------------------------------------------
# credential resolution → RagasEvaluator wiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_judge_credential_resolves_provider_base_url_and_key() -> None:
    """resolve_inference_target returns (provider_id, base_url, api_key) from the
    credential row; these are then passed to RagasEvaluator."""
    credential_id = uuid4()
    repo = _FakeRepo(_Row(
        api_key_encrypted=b"groq-secret",
        base_url="https://api.groq.com/openai/v1",
        provider_id="openai_compat",
    ))
    encryptor = _FakeEncryptor()

    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=credential_id,
        ollama_base_url="http://localhost:11434",
        credentials_repo=repo,
        encryptor=encryptor,
    )

    # Credential was fetched exactly once
    assert repo.called is True
    # Resolved values come from the credential row
    assert provider_id == "openai_compat"
    assert base_url == "https://api.groq.com/openai/v1"
    assert api_key == "groq-secret"

    # These resolved values can wire into RagasEvaluator without error
    evaluator = RagasEvaluator(
        base_url="http://localhost:11434",
        judge_model="llama-3.3-70b-versatile",
        embedding_model="bge-m3",
        judge_provider=provider_id,
        judge_base_url=base_url,
        judge_api_key=api_key,
    )
    assert evaluator.judge_provider == "openai_compat"
    assert evaluator.judge_base_url == "https://api.groq.com/openai/v1"
    assert evaluator.judge_api_key == "groq-secret"


@pytest.mark.asyncio
async def test_judge_ollama_credential_resolves_to_server_url_no_key() -> None:
    """An Ollama credential resolves to (ollama, ollama_base_url, None)."""
    credential_id = uuid4()
    repo = _FakeRepo(_Row(
        api_key_encrypted=b"",
        base_url=None,
        provider_id="ollama",
    ))
    encryptor = _FakeEncryptor()

    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=credential_id,
        ollama_base_url="http://localhost:11434",
        credentials_repo=repo,
        encryptor=encryptor,
    )

    assert provider_id == "ollama"
    assert base_url == "http://localhost:11434"
    assert api_key is None

    evaluator = RagasEvaluator(
        base_url="http://localhost:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
        judge_provider=provider_id,
        judge_base_url=base_url,
        judge_api_key=api_key,
    )
    assert evaluator.judge_provider == "ollama"
    assert evaluator.judge_api_key is None


@pytest.mark.asyncio
async def test_judge_openai_credential_forces_public_url() -> None:
    """openai credential always resolves to the canonical public base URL."""
    credential_id = uuid4()
    repo = _FakeRepo(_Row(
        api_key_encrypted=b"sk-openai",
        base_url=None,
        provider_id="openai",
    ))
    encryptor = _FakeEncryptor()

    provider_id, base_url, api_key = await resolve_inference_target(
        credential_id=credential_id,
        ollama_base_url="http://localhost:11434",
        credentials_repo=repo,
        encryptor=encryptor,
    )

    assert provider_id == "openai"
    assert base_url == "https://api.openai.com/v1"
    assert api_key == "sk-openai"
