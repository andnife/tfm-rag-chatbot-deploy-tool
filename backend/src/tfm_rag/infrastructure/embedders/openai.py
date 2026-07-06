import httpx

from tfm_rag.domain.ports.embedder import EmbedProgress


class OpenAIEmbedder:
    """Embedder for the OpenAI /embeddings API and compatible endpoints.

    Batches all texts into a single request. `transport` is an optional
    httpx transport for testing (MockTransport).
    """

    DEFAULT_TIMEOUT_SECS = 120.0

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        self._transport = transport
        self._timeout = timeout or self.DEFAULT_TIMEOUT_SECS

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        texts: list[str],
        on_progress: EmbedProgress | None = None,
    ) -> list[list[float]]:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                r = await client.post(
                    "/embeddings",
                    json={"model": model_id, "input": texts},
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"OpenAI /embeddings transport failed (model={model_id!r}): {exc}"
            ) from exc

        if r.status_code != 200:
            raise RuntimeError(
                f"OpenAI /embeddings returned HTTP {r.status_code}: {r.text[:500]}"
            )

        data = r.json().get("data") or []
        if len(data) != len(texts):
            raise RuntimeError(
                f"OpenAI /embeddings returned {len(data)} vectors for "
                f"{len(texts)} inputs (model={model_id!r})"
            )
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        if on_progress is not None:
            await on_progress(len(texts), len(texts))
        return [list(item["embedding"]) for item in ordered]
