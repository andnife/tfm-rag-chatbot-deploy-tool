from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class RetrievalIteration:
    """Telemetry for one turn of the agent loop. Persisted as a dict inside
    `chat_messages.metadata.iterations[]`.

    `tool` is one of the constants in `domain/catalog/agent_tools.py`. For
    `final_answer` and `abstain` turns, `query` and `num_chunks` will be
    None — the iteration captures the LLM decision, not a retrieval.
    """

    index: int
    tool: str
    query: str | None
    num_chunks: int | None
    latency_ms: float

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValidationError(
                f"RetrievalIteration.index must be >= 0, got {self.index}"
            )
        if self.latency_ms < 0:
            raise ValidationError(
                f"RetrievalIteration.latency_ms must be >= 0, got {self.latency_ms}"
            )
        if self.num_chunks is not None and self.num_chunks < 0:
            raise ValidationError(
                f"RetrievalIteration.num_chunks must be >= 0 if set, got {self.num_chunks}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tool": self.tool,
            "query": self.query,
            "num_chunks": self.num_chunks,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalIteration":
        return cls(
            index=int(data["index"]),
            tool=str(data["tool"]),
            query=(str(data["query"]) if data.get("query") is not None else None),
            num_chunks=(
                int(data["num_chunks"]) if data.get("num_chunks") is not None else None
            ),
            latency_ms=float(data["latency_ms"]),
        )


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """Returned by `LLMProvider.generate` when the model invoked a tool.

    `tool` is one of the constants in `domain/catalog/agent_tools.py`.
    `arguments` is the parsed JSON object passed to the tool.
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True, slots=True)
class LLMTextResponse:
    """Returned by `LLMProvider.generate` when the model produced raw text
    without calling a tool. The agent loop treats this as an implicit
    final answer (defensive: if a model ignores the tool schema we still
    return SOMETHING to the user).
    """

    text: str


type LLMResponse = LLMToolCall | LLMTextResponse
