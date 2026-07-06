import httpx
import pytest

from tfm_rag.infrastructure.embedders.ollama import OllamaEmbedder


def _embedder(handler) -> OllamaEmbedder:  # noqa: ANN001
    return OllamaEmbedder(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_embeds_each_text_in_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.1, 0.2]})

    vecs = await _embedder(handler).embed(
        base_url="http://localhost:11434",
        api_key=None,
        model_id="bge-m3",
        texts=["a", "b", "c"],
    )
    assert vecs == [[0.1, 0.2], [0.1, 0.2], [0.1, 0.2]]


@pytest.mark.asyncio
async def test_on_progress_called_per_chunk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embedding": [0.5]})

    calls: list[tuple[int, int]] = []

    async def on_progress(done: int, total: int) -> None:
        calls.append((done, total))

    await _embedder(handler).embed(
        base_url="http://localhost:11434",
        api_key=None,
        model_id="bge-m3",
        texts=["a", "b", "c"],
        on_progress=on_progress,
    )
    assert calls == [(1, 3), (2, 3), (3, 3)]


@pytest.mark.asyncio
async def test_model_not_found_raises_with_pull_hint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'bge-m3' not found"})

    with pytest.raises(RuntimeError, match="ollama pull"):
        await _embedder(handler).embed(
            base_url="http://localhost:11434",
            api_key=None,
            model_id="bge-m3",
            texts=["a"],
        )
