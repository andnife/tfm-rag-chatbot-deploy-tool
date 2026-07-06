from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class GradeVerdict:
    """The evaluator's GRADE output: is the retrieved/queried context enough
    to answer? If not, optionally a reformulated query (docs), a corrected
    SQL (sql), or a reason to abstain. Persisted inside RoutingTrace.
    """

    sufficient: bool
    reformulated_query: str | None = None
    fixed_sql: str | None = None
    abstain_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "reformulated_query": self.reformulated_query,
            "fixed_sql": self.fixed_sql,
            "abstain_reason": self.abstain_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GradeVerdict":
        def _opt(key: str) -> str | None:
            val = data.get(key)
            return str(val) if val is not None else None

        return cls(
            sufficient=bool(data["sufficient"]),
            reformulated_query=_opt("reformulated_query"),
            fixed_sql=_opt("fixed_sql"),
            abstain_reason=_opt("abstain_reason"),
        )
