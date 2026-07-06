from dataclasses import dataclass
from typing import Any
from uuid import UUID

from tfm_rag.domain.errors.common import ValidationError


@dataclass(frozen=True, slots=True)
class SqlPlan:
    """One query the sql_generator wants to run: which database source + the
    READ-ONLY SELECT. The generator runs queries in a conversational loop
    (each result is fed back) and self-terminates when it has enough data;
    there is no explore/answer distinction — every query just gathers info."""

    source_id: UUID
    sql: str

    def __post_init__(self) -> None:
        if not self.sql.strip():
            raise ValidationError("SqlPlan.sql must not be blank")

    def to_dict(self) -> dict[str, Any]:
        return {"source_id": str(self.source_id), "sql": self.sql}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SqlPlan":
        return cls(
            source_id=UUID(str(data["source_id"])),
            sql=str(data["sql"]),
        )
