from dataclasses import dataclass, field
from typing import Any

from tfm_rag.domain.catalog.routes import ROUTE_NAMES
from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """The evaluator's ROUTE output: which route to execute + why."""

    route: str
    rationale: str
    raw: dict[str, Any] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        if self.route not in ROUTE_NAMES:
            raise ValidationError(f"Unknown route: {self.route!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"route": self.route, "rationale": self.rationale, "raw": self.raw}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouteDecision":
        return cls(
            route=str(data["route"]),
            rationale=str(data.get("rationale", "")),
            raw=dict(data.get("raw") or {}),
        )
