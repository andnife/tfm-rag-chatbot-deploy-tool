from typing import Protocol


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
    ) -> list[list[float]]: ...
