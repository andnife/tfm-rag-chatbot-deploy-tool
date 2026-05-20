from dataclasses import dataclass

from tfm_rag.domain.catalog.llm_providers import ConfigSource


@dataclass(frozen=True, slots=True)
class EmbeddingProviderDescriptor:
    id: str
    display_name: str
    description: str
    config_source: ConfigSource
    requires_base_url_input: bool
    default_models: tuple[tuple[str, int], ...]  # (model_id, dim)


EMBEDDING_PROVIDER_CATALOG: dict[str, EmbeddingProviderDescriptor] = {
    "ollama": EmbeddingProviderDescriptor(
        id="ollama",
        display_name="Ollama (local)",
        description="Local embeddings via Ollama.",
        config_source="SERVER_ENV",
        requires_base_url_input=False,
        default_models=(
            ("bge-m3", 1024),
            ("nomic-embed-text", 768),
            ("embeddinggemma:300m", 768),
        ),
    ),
    "openai_compat": EmbeddingProviderDescriptor(
        id="openai_compat",
        display_name="OpenAI (or compatible)",
        description="OpenAI embeddings or any compatible endpoint.",
        config_source="TENANT_CREDENTIAL",
        requires_base_url_input=False,
        default_models=(
            ("text-embedding-3-small", 1536),
            ("text-embedding-3-large", 3072),
        ),
    ),
}
