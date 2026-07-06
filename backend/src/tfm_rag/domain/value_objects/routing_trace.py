from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.value_objects.grade_verdict import GradeVerdict
from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration


@dataclass(frozen=True, slots=True)
class RoutingTrace:
    """Telemetry for one explicit-router turn. Persisted in
    `chat_messages.metadata['routing']`. Includes the grader verdicts (B2).
    """

    route: str
    rationale: str
    attempts: list[RetrievalIteration] = field(default_factory=list, hash=False)
    verdicts: list[GradeVerdict] = field(default_factory=list, hash=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "rationale": self.rationale,
            "attempts": [a.to_dict() for a in self.attempts],
            "verdicts": [v.to_dict() for v in self.verdicts],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoutingTrace":
        return cls(
            route=str(data["route"]),
            rationale=str(data.get("rationale", "")),
            attempts=[
                RetrievalIteration.from_dict(a) for a in data.get("attempts", [])
            ],
            verdicts=[
                GradeVerdict.from_dict(v) for v in data.get("verdicts", [])
            ],
        )
