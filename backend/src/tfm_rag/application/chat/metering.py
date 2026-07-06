from dataclasses import dataclass
from typing import Any, cast

from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    TokenUsage,
)


@dataclass
class TokenMeter:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def record(self, usage: TokenUsage | None) -> None:
        if usage is None:
            return
        self.prompt_tokens += usage.prompt_tokens
        self.completion_tokens += usage.completion_tokens


@dataclass(frozen=True, slots=True)
class MeteringLLM:
    """Wraps an LLMProvider, accumulating per-call token usage into a meter.
    Pass-through: the response is returned unchanged."""
    inner: object
    meter: TokenMeter

    async def generate(self, **kwargs: Any) -> LLMResponse:
        result = await self.inner.generate(**kwargs)  # type: ignore[attr-defined]
        self.meter.record(getattr(result, "usage", None))
        return cast(LLMResponse, result)
