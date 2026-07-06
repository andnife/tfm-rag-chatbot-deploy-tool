from collections.abc import Awaitable, Callable
from typing import Protocol

# Called as texts are embedded: (done, total). Lets the ingestion pipeline
# turn the embedding phase into a real per-chunk progress ramp. Optional —
# adapters that embed in a single batch call it once with (total, total).
EmbedProgress = Callable[[int, int], Awaitable[None]]


class Embedder(Protocol):
    """Turns texts into vectors. One model per call.

    `base_url` is the provider endpoint; for SERVER_ENV providers (Ollama)
    use cases inject the value from Settings. For TENANT_CREDENTIAL
    providers, the caller decrypts the credential and supplies it.
    """

    async def embed(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_id: str,
        texts: list[str],
        on_progress: EmbedProgress | None = None,
    ) -> list[list[float]]: ...


class EmbedderDispatcherPort(Protocol):
    """Resolves a `provider_id` to the matching `Embedder` adapter.

    Lets use cases pick an embedder at runtime (the provider is derived from
    the credential) without depending on the concrete infrastructure
    dispatcher. Raises `UnsupportedProviderError` for unknown providers.
    """

    def for_provider(self, provider_id: str) -> Embedder: ...
