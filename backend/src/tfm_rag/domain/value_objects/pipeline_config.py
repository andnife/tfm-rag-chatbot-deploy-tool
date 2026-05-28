from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection

# Bounds — match the spec §6 fiche.
TOP_K_MIN = 1
TOP_K_MAX = 50
SCORE_THRESHOLD_MIN = 0.0
SCORE_THRESHOLD_MAX = 1.0
MAX_RETRIEVAL_ITERATIONS_MIN = 1
MAX_RETRIEVAL_ITERATIONS_MAX = 5
RERANKER_INITIAL_TOP_K_MIN = 1
RERANKER_INITIAL_TOP_K_MAX = 200


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    """LLM sampling knobs. Nested inside PipelineConfig under `generation`."""

    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if not (0.0 <= self.temperature <= 2.0):
            raise ValidationError(
                f"temperature must be in [0, 2], got {self.temperature}"
            )
        if not (0.0 < self.top_p <= 1.0):
            raise ValidationError(
                f"top_p must be in (0, 1], got {self.top_p}"
            )
        if not (1 <= self.max_tokens <= 4_096):
            raise ValidationError(
                f"max_tokens must be in [1, 4096], got {self.max_tokens}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationConfig":
        return cls(
            temperature=float(data.get("temperature", 0.2)),
            top_p=float(data.get("top_p", 1.0)),
            max_tokens=int(data.get("max_tokens", 1024)),
        )


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Runtime config of a Chatbot's RAG pipeline.

    Lives at the Chatbot level (per spec §6 reparto-de-configuración table).
    Stored as a single JSONB blob in `chatbots.pipeline_config` plus the
    invariant CHECK at the SQL layer (`max_retrieval_iterations BETWEEN 1 AND 5`).
    """

    top_k: int = 5
    score_threshold: float = 0.0
    agentic_mode: bool = True
    max_retrieval_iterations: int = 3
    enable_reranker: bool = False
    reranker_initial_top_k: int = 30
    abstain_when_insufficient: bool = True
    router_llm_selection: LLMSelection | None = None
    generation: GenerationConfig = field(default_factory=GenerationConfig)

    def __post_init__(self) -> None:
        if not (TOP_K_MIN <= self.top_k <= TOP_K_MAX):
            raise ValidationError(
                f"top_k must be in [{TOP_K_MIN},{TOP_K_MAX}], got {self.top_k}"
            )
        if not (SCORE_THRESHOLD_MIN <= self.score_threshold <= SCORE_THRESHOLD_MAX):
            raise ValidationError(
                f"score_threshold must be in [0, 1], got {self.score_threshold}"
            )
        if not (
            MAX_RETRIEVAL_ITERATIONS_MIN
            <= self.max_retrieval_iterations
            <= MAX_RETRIEVAL_ITERATIONS_MAX
        ):
            raise ValidationError(
                "max_retrieval_iterations must be in "
                f"[{MAX_RETRIEVAL_ITERATIONS_MIN},{MAX_RETRIEVAL_ITERATIONS_MAX}], "
                f"got {self.max_retrieval_iterations}"
            )
        if self.enable_reranker and not (
            RERANKER_INITIAL_TOP_K_MIN
            <= self.reranker_initial_top_k
            <= RERANKER_INITIAL_TOP_K_MAX
        ):
            raise ValidationError(
                "reranker_initial_top_k must be in "
                f"[{RERANKER_INITIAL_TOP_K_MIN},{RERANKER_INITIAL_TOP_K_MAX}], "
                f"got {self.reranker_initial_top_k}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "top_k": self.top_k,
            "score_threshold": self.score_threshold,
            "agentic_mode": self.agentic_mode,
            "max_retrieval_iterations": self.max_retrieval_iterations,
            "enable_reranker": self.enable_reranker,
            "reranker_initial_top_k": self.reranker_initial_top_k,
            "abstain_when_insufficient": self.abstain_when_insufficient,
            "router_llm_selection": (
                self.router_llm_selection.to_dict()
                if self.router_llm_selection
                else None
            ),
            "generation": self.generation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineConfig":
        router = data.get("router_llm_selection")
        gen = data.get("generation") or {}
        return cls(
            top_k=int(data.get("top_k", 5)),
            score_threshold=float(data.get("score_threshold", 0.0)),
            agentic_mode=bool(data.get("agentic_mode", True)),
            max_retrieval_iterations=int(
                data.get("max_retrieval_iterations", 3)
            ),
            enable_reranker=bool(data.get("enable_reranker", False)),
            reranker_initial_top_k=int(data.get("reranker_initial_top_k", 30)),
            abstain_when_insufficient=bool(
                data.get("abstain_when_insufficient", True)
            ),
            router_llm_selection=(
                LLMSelection.from_dict(router) if router else None
            ),
            generation=GenerationConfig.from_dict(gen),
        )

    @classmethod
    def default(cls) -> "PipelineConfig":
        return cls()
