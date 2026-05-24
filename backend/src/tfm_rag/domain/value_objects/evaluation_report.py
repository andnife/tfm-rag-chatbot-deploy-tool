from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Aggregated metrics across the cases in an evaluation run.

    Errored cases (``case.error is not None``) are skipped when computing
    averages — they're counted in ``num_errors``.
    """

    num_cases: int
    num_errors: int
    num_scored: int
    metrics: dict[str, float] = field(default_factory=dict, hash=False)

    @classmethod
    def from_cases(cls, cases: list[EvaluationCase]) -> "EvaluationSummary":
        scored = [c for c in cases if c.error is None and c.scores]
        errored = [c for c in cases if c.error is not None]

        averages: dict[str, float] = {}
        if scored:
            metric_names: set[str] = set()
            for c in scored:
                metric_names.update(c.scores.keys())  # type: ignore[union-attr]
            for name in metric_names:
                vals = [
                    c.scores[name]  # type: ignore[index]
                    for c in scored
                    if c.scores and name in c.scores
                ]
                if vals:
                    averages[name] = sum(vals) / len(vals)

        return cls(
            num_cases=len(cases),
            num_errors=len(errored),
            num_scored=len(scored),
            metrics=averages,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_cases": self.num_cases,
            "num_errors": self.num_errors,
            "num_scored": self.num_scored,
            "metrics": self.metrics,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Full output of one CLI invocation.

    Persisted as JSON via ``to_dict()`` + ``json.dumps``, and rendered as a
    human-readable Markdown digest by ``report_writer``.
    """

    chatbot_id: UUID
    chatbot_name: str
    dataset_path: str
    scenario_filter: str | None
    run_started_at: datetime
    run_finished_at: datetime
    ragas_judge_model: str
    cases: list[EvaluationCase]
    summary: EvaluationSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatbot_id": str(self.chatbot_id),
            "chatbot_name": self.chatbot_name,
            "dataset_path": self.dataset_path,
            "scenario_filter": self.scenario_filter,
            "run_started_at": self.run_started_at.isoformat(),
            "run_finished_at": self.run_finished_at.isoformat(),
            "ragas_judge_model": self.ragas_judge_model,
            "cases": [c.to_dict() for c in self.cases],
            "summary": self.summary.to_dict(),
        }

    def top_failures(self, *, metric: str, n: int = 3) -> list[EvaluationCase]:
        """Return the ``n`` scored cases with the lowest score on ``metric``.

        Errored cases are excluded. Cases missing this metric are excluded.
        Used by the Markdown report to flag worst offenders per metric.
        """
        candidates = [
            c for c in self.cases
            if c.error is None and c.scores and metric in c.scores
        ]
        candidates.sort(key=lambda c: c.scores[metric])  # type: ignore[index]
        return candidates[:n]
