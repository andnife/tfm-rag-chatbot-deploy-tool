import httpx


class OllamaEmbedder:
    """Calls Ollama's /api/embeddings endpoint, one text at a time.

    Ollama supports batch via /api/embed (newer), but /api/embeddings is the
    older, more stable surface and what the M2 demo runs against.
    """

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str | None,  # noqa: ARG002 — Ollama is keyless
        model_id: str,
        texts: list[str],
    ) -> list[list[float]]:
        results: list[list[float]] = []
        async with httpx.AsyncClient(base_url=base_url, timeout=120.0) as client:
            for t in texts:
                r = await client.post(
                    "/api/embeddings", json={"model": model_id, "prompt": t}
                )
                r.raise_for_status()
                body = r.json()
                vec = body.get("embedding") or []
                if not vec:
                    raise RuntimeError(
                        f"Ollama returned no embedding for model {model_id!r}"
                    )
                results.append(list(vec))
        return results
