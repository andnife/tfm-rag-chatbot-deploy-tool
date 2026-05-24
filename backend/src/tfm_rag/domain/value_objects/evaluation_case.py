from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=False, slots=True)
class EvaluationCase:
    """One entry in an evaluation run. Combines:

    - input from the dataset: ``question``, ``ground_truth``, ``scenario``, ``metadata``
    - prediction from the chatbot (filled after ``answer_query`` runs):
      ``predicted_answer``, ``retrieved_contexts``, ``citations``, ``iterations``
    - judge output (filled after ragas runs): ``scores`` (per-metric float in [0,1])
    - error path: ``error`` non-None means the case failed (LLM error,
      retrieval error, ragas crash); the rest may be partially filled.

    Mutable (``frozen=False``) on purpose — the pipeline fills fields in
    stages. Use ``to_dict()`` for JSON serialisation.
    """

    question: str
    ground_truth: str
    scenario: str
    metadata: dict[str, Any] = field(default_factory=dict)

    predicted_answer: str | None = None
    retrieved_contexts: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    iterations: list[dict[str, Any]] = field(default_factory=list)

    scores: dict[str, float] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.question or not self.question.strip():
            raise ValidationError("EvaluationCase.question must not be empty")
        if not self.scenario or not self.scenario.strip():
            raise ValidationError("EvaluationCase.scenario must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "ground_truth": self.ground_truth,
            "scenario": self.scenario,
            "metadata": self.metadata,
            "predicted_answer": self.predicted_answer,
            "retrieved_contexts": self.retrieved_contexts,
            "citations": self.citations,
            "iterations": self.iterations,
            "scores": self.scores,
            "error": self.error,
        }
