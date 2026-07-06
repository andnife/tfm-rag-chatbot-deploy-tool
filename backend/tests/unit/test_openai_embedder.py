import json

import httpx
import pytest

from tfm_rag.infrastructure.embedders.openai import OpenAIEmbedder


def _embedder(handler) -> OpenAIEmbedder:  # noqa: ANN001
    return OpenAIEmbedder(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_batch_embeddings_returned_in_input_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer sk-test"
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-3-small"
        assert body["input"] == ["a", "b"]
        # Return out of order to prove we sort by index.
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            },
        )

    vecs = await _embedder(handler).embed(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_id="text-embedding-3-small",
        texts=["a", "b"],
    )
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_http_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    with pytest.raises(RuntimeError):
        await _embedder(handler).embed(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="text-embedding-3-small",
            texts=["a"],
        )


@pytest.mark.asyncio
async def test_count_mismatch_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1]}]})

    with pytest.raises(RuntimeError):
        await _embedder(handler).embed(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="text-embedding-3-small",
            texts=["a", "b"],
        )


@pytest.mark.asyncio
async def test_on_progress_called_once_with_total() -> None:
    """OpenAI embeds in a single batch → reports (total, total) exactly once."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": i, "embedding": [float(i)]} for i in range(3)]},
        )

    calls: list[tuple[int, int]] = []

    async def on_progress(done: int, total: int) -> None:
        calls.append((done, total))

    await _embedder(handler).embed(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model_id="text-embedding-3-small",
        texts=["a", "b", "c"],
        on_progress=on_progress,
    )
    assert calls == [(3, 3)]


@pytest.mark.asyncio
async def test_transport_error_raises_runtime_error() -> None:
    """httpx transport errors (ConnectError, etc.) must be wrapped in RuntimeError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(RuntimeError, match="transport failed"):
        await _embedder(handler).embed(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="text-embedding-3-small",
            texts=["hello"],
        )
