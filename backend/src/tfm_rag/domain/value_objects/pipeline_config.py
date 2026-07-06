from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.errors.common import ValidationError

# Bounds — match the spec §6 fiche.
TOP_K_MIN = 1
TOP_K_MAX = 50
SCORE_THRESHOLD_MIN = 0.0
SCORE_THRESHOLD_MAX = 1.0
MAX_SELF_CORRECTION_RETRIES_MIN = 0
MAX_SELF_CORRECTION_RETRIES_MAX = 3
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
    invariant CHECK at the SQL layer
    (`max_self_correction_retries BETWEEN 0 AND 3`).
    """

    top_k: int = 5
    score_threshold: float = 0.0
    max_self_correction_retries: int = 1
    enable_reranker: bool = False
    reranker_initial_top_k: int = 30
    abstain_when_insufficient: bool = True
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
            MAX_SELF_CORRECTION_RETRIES_MIN
            <= self.max_self_correction_retries
            <= MAX_SELF_CORRECTION_RETRIES_MAX
        ):
            raise ValidationError(
                "max_self_correction_retries must be in "
                f"[{MAX_SELF_CORRECTION_RETRIES_MIN},{MAX_SELF_CORRECTION_RETRIES_MAX}], "
                f"got {self.max_self_correction_retries}"
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
            "max_self_correction_retries": self.max_self_correction_retries,
            "enable_reranker": self.enable_reranker,
            "reranker_initial_top_k": self.reranker_initial_top_k,
            "abstain_when_insufficient": self.abstain_when_insufficient,
            "generation": self.generation.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineConfig":
        gen = data.get("generation") or {}
        return cls(
            top_k=int(data.get("top_k", 5)),
            score_threshold=float(data.get("score_threshold", 0.0)),
            max_self_correction_retries=int(
                data.get("max_self_correction_retries", 1)
            ),
            enable_reranker=bool(data.get("enable_reranker", False)),
            reranker_initial_top_k=int(data.get("reranker_initial_top_k", 30)),
            abstain_when_insufficient=bool(
                data.get("abstain_when_insufficient", True)
            ),
            generation=GenerationConfig.from_dict(gen),
        )

    @classmethod
    def default(cls) -> "PipelineConfig":
        return cls()
