from dataclasses import dataclass, field
from typing import Literal

ConfigSource = Literal["SERVER_ENV", "TENANT_CREDENTIAL"]


@dataclass(frozen=True, slots=True)
class LLMProviderDescriptor:
    id: str
    display_name: str
    description: str
    config_source: ConfigSource
    requires_base_url_input: bool
    supports_tool_calling: bool
    default_models: tuple[str, ...] = field(default_factory=tuple)
    # Recommended rate limits applied when a credential leaves them unset. Only
    # meaningful for providers with well-known limits (OpenAI). Consumed by the
    # evaluation judge via `resolve_rate_limits`; None = fall back to the global
    # default. Not used to throttle live chat.
    recommended_max_concurrency: int | None = None
    recommended_min_request_interval_seconds: float | None = None


LLM_PROVIDER_CATALOG: dict[str, LLMProviderDescriptor] = {
    "ollama": LLMProviderDescriptor(
        id="ollama",
        display_name="Ollama (local)",
        description="Local LLM via Ollama. Configured via OLLAMA_BASE_URL env.",
        config_source="SERVER_ENV",
        requires_base_url_input=False,
        supports_tool_calling=True,
        default_models=("llama3.1", "mistral", "gemma2"),
    ),
    "openai": LLMProviderDescriptor(
        id="openai",
        display_name="OpenAI",
        description="OpenAI chat completions API.",
        config_source="TENANT_CREDENTIAL",
        requires_base_url_input=False,
        supports_tool_calling=True,
        default_models=("gpt-4o-mini", "gpt-4o"),
        # OpenAI's tiers comfortably handle this; 429s are retried. Conservative
        # so it is safe across account tiers without being prompted for.
        recommended_max_concurrency=8,
    ),
    "openai_compat": LLMProviderDescriptor(
        id="openai_compat",
        display_name="OpenAI-compatible endpoint",
        description=(
            "Any provider exposing a Chat Completions-compatible API "
            "(Groq, Together, OpenRouter, DeepSeek, NIM, GitHub Models, ...)."
        ),
        config_source="TENANT_CREDENTIAL",
        requires_base_url_input=True,
        supports_tool_calling=True,
        default_models=(),
    ),
}


def resolve_rate_limits(
    provider_id: str,
    *,
    cred_max_concurrency: int | None,
    cred_min_interval: float | None,
) -> tuple[int | None, float | None]:
    """Effective judge rate limits for a credential.

    Precedence: an explicit credential value wins; otherwise the provider's
    recommended default (OpenAI); otherwise None, meaning the caller uses its
    own global default (e.g. RAGAS_MAX_WORKERS). Evaluation-only — this does not
    throttle live chat generation.
    """
    descriptor = LLM_PROVIDER_CATALOG.get(provider_id)
    max_concurrency = (
        cred_max_concurrency
        if cred_max_concurrency is not None
        else (descriptor.recommended_max_concurrency if descriptor else None)
    )
    min_interval = (
        cred_min_interval
        if cred_min_interval is not None
        else (
            descriptor.recommended_min_request_interval_seconds
            if descriptor
            else None
        )
    )
    return max_concurrency, min_interval
