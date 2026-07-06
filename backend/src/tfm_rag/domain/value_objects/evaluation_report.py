import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


def _mean_and_std(
    cases: list[EvaluationCase],
) -> tuple[dict[str, float], dict[str, float]]:
    """Per-metric mean and sample stdev over the scored cases.

    stdev is the sample standard deviation (n-1); 0.0 when n < 2 so a
    single-case run still reports a number rather than blowing up.
    """
    metric_names: set[str] = set()
    for c in cases:
        if c.scores:
            metric_names.update(c.scores.keys())
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for name in metric_names:
        vals = [c.scores[name] for c in cases if c.scores and name in c.scores]
        if vals:
            means[name] = sum(vals) / len(vals)
            stds[name] = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return means, stds


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Aggregated metrics across the cases in an evaluation run.

    Cases are partitioned into: ``num_errors`` (``case.error`` set),
    ``num_scored`` (have ``scores``), and ``num_skipped`` (no error but no
    scores — e.g. empty contexts). Means come with a sample ``metrics_std``
    so OFAT comparisons (CAP-21) can judge whether differences exceed noise,
    and ``per_scenario`` breaks the same stats down by scenario so doc/sql/
    abstain results aren't blended into one misleading average.
    """

    num_cases: int
    num_errors: int
    num_scored: int
    num_skipped: int = 0
    metrics: dict[str, float] = field(default_factory=dict, hash=False)
    metrics_std: dict[str, float] = field(default_factory=dict, hash=False)
    per_scenario: dict[str, dict[str, Any]] = field(
        default_factory=dict, hash=False
    )
    gen_prompt_tokens: int = 0
    gen_completion_tokens: int = 0

    @classmethod
    def from_cases(cls, cases: list[EvaluationCase]) -> "EvaluationSummary":
        scored = [c for c in cases if c.error is None and c.scores]
        errored = [c for c in cases if c.error is not None]
        skipped = [c for c in cases if c.error is None and not c.scores]

        means, stds = _mean_and_std(scored)

        per_scenario: dict[str, dict[str, Any]] = {}
        scenarios = {c.scenario for c in cases}
        for scenario in scenarios:
            in_scope = [c for c in cases if c.scenario == scenario]
            scored_in_scope = [c for c in in_scope if c.error is None and c.scores]
            s_means, s_stds = _mean_and_std(scored_in_scope)
            per_scenario[scenario] = {
                "num_cases": len(in_scope),
                "num_scored": len(scored_in_scope),
                "metrics": s_means,
                "metrics_std": s_stds,
            }

        gen_prompt_tokens = sum(c.prompt_tokens for c in cases)
        gen_completion_tokens = sum(c.completion_tokens for c in cases)

        return cls(
            num_cases=len(cases),
            num_errors=len(errored),
            num_scored=len(scored),
            num_skipped=len(skipped),
            metrics=means,
            metrics_std=stds,
            per_scenario=per_scenario,
            gen_prompt_tokens=gen_prompt_tokens,
            gen_completion_tokens=gen_completion_tokens,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_cases": self.num_cases,
            "num_errors": self.num_errors,
            "num_scored": self.num_scored,
            "num_skipped": self.num_skipped,
            "metrics": self.metrics,
            "metrics_std": self.metrics_std,
            "per_scenario": self.per_scenario,
            "tokens": {
                "gen_prompt": self.gen_prompt_tokens,
                "gen_completion": self.gen_completion_tokens,
            },
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
    # Main generator model (chatbot.llm_selection.model_id). Snapshotted at
    # report time so a later chatbot edit can't rewrite history. Defaulted so
    # existing call sites stay valid; dataclass ordering requires it last.
    generator_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chatbot_id": str(self.chatbot_id),
            "chatbot_name": self.chatbot_name,
            "dataset_path": self.dataset_path,
            "scenario_filter": self.scenario_filter,
            "run_started_at": self.run_started_at.isoformat(),
            "run_finished_at": self.run_finished_at.isoformat(),
            "ragas_judge_model": self.ragas_judge_model,
            "generator_model": self.generator_model,
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
