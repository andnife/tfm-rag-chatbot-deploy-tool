import os

import pytest

from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse, LLMToolCall
from tfm_rag.infrastructure.embedders.openai import OpenAIEmbedder
from tfm_rag.infrastructure.llm_providers.openai import OpenAILLMAdapter

# Reads an OpenAI-compatible endpoint from the environment. Set:
#   OPENAI_TEST_BASE_URL (default https://api.openai.com/v1)
#   OPENAI_TEST_API_KEY  (required — test skips if missing)
#   OPENAI_TEST_CHAT_MODEL (default gpt-4o-mini)
#   OPENAI_TEST_EMBED_MODEL (default text-embedding-3-small)
_API_KEY = os.getenv("OPENAI_TEST_API_KEY")
_BASE_URL = os.getenv("OPENAI_TEST_BASE_URL", "https://api.openai.com/v1")
_CHAT_MODEL = os.getenv("OPENAI_TEST_CHAT_MODEL", "gpt-4o-mini")
_EMBED_MODEL = os.getenv("OPENAI_TEST_EMBED_MODEL", "text-embedding-3-small")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _API_KEY, reason="OPENAI_TEST_API_KEY not set"),
]


async def test_live_chat_completion() -> None:
    resp = await OpenAILLMAdapter().generate(
        base_url=_BASE_URL,
        api_key=_API_KEY,
        model_id=_CHAT_MODEL,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        tools=None,
        temperature=0.0,
        top_p=1.0,
        max_tokens=16,
    )
    assert isinstance(resp, (LLMTextResponse, LLMToolCall))
    if isinstance(resp, LLMTextResponse):
        assert resp.text.strip() != ""


async def test_live_embeddings() -> None:
    vecs = await OpenAIEmbedder().embed(
        base_url=_BASE_URL,
        api_key=_API_KEY,
        model_id=_EMBED_MODEL,
        texts=["hello", "world"],
    )
    assert len(vecs) == 2
    assert len(vecs[0]) > 0
