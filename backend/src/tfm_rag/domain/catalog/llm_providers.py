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
