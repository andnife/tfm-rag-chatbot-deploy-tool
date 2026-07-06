import httpx

from tfm_rag.domain.ports.embedder import EmbedProgress


class OllamaEmbedder:
    """Calls Ollama's /api/embeddings endpoint, one text at a time.

    Ollama supports batch via /api/embed (newer), but /api/embeddings is the
    older, more stable surface and what the M2 demo runs against.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str | None,  # noqa: ARG002 — Ollama is keyless
        model_id: str,
        texts: list[str],
        on_progress: EmbedProgress | None = None,
    ) -> list[list[float]]:
        results: list[list[float]] = []
        async with httpx.AsyncClient(
            base_url=base_url, timeout=120.0, transport=self._transport
        ) as client:
            for t in texts:
                r = await client.post(
                    "/api/embeddings", json={"model": model_id, "prompt": t}
                )
                if r.status_code == 404:
                    body = r.json() if r.content else {}
                    msg = body.get("error") or "model not found"
                    raise RuntimeError(
                        f"Ollama: {msg}. Run `ollama pull {model_id}` "
                        f"(host) or `docker exec tfm-rag-ollama-1 ollama pull "
                        f"{model_id}` (container)."
                    )
                r.raise_for_status()
                body = r.json()
                vec = body.get("embedding") or []
                if not vec:
                    raise RuntimeError(
                        f"Ollama returned no embedding for model {model_id!r}"
                    )
                results.append(list(vec))
                if on_progress is not None:
                    await on_progress(len(results), len(texts))
        return results
