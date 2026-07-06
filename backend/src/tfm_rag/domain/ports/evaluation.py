"""Ports for the evaluation module's inference-side collaborators.

`EvaluationJudgePort` is the contract `run_ragas_evaluation` depends on to
score a batch of cases — implemented by the RAGAS adapter in
`infrastructure/evaluation`. Keeping it a Protocol lets the use case stay
free of the (heavy, optional) RAGAS / LangChain imports.
"""
from typing import Protocol

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


class EvaluationJudgePort(Protocol):
    """Scores answered evaluation cases and exposes judge metadata/token tallies.

    Declared as read-only properties (rather than plain attributes) because
    the RAGAS adapter is a frozen dataclass; implementers only need to expose
    these for reading, never for external mutation.
    """

    @property
    def judge_model(self) -> str: ...

    # Token totals from the most recent `evaluate()` call (cost accounting).
    @property
    def last_judge_prompt_tokens(self) -> int: ...

    @property
    def last_judge_completion_tokens(self) -> int: ...

    def evaluate(self, cases: list[EvaluationCase]) -> list[dict[str, float]]:
        """Return per-case metric dicts, positionally aligned with `cases`.

        Cases that cannot be scored (errored / no context / abstain handled
        deterministically) get `{}` (or the deterministic metric) for their slot.
        """
        ...
