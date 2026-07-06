from dataclasses import dataclass
from typing import Any

from tfm_rag.domain.catalog.llm_roles import ROLE_NAMES
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection


@dataclass(frozen=True, slots=True)
class RoleLLMSelections:
    """Per-role LLM model overrides for a chatbot.

    Each role is optional; an unset role falls back to the chatbot's main
    `llm_selection` via `resolve()`. Stored as a JSONB blob in
    `chatbots.role_llm_selections` (keys for unset roles are omitted).
    """

    evaluator: LLMSelection | None = None
    sql_generator: LLMSelection | None = None
    answer_generator: LLMSelection | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.evaluator is not None:
            out["evaluator"] = self.evaluator.to_dict()
        if self.sql_generator is not None:
            out["sql_generator"] = self.sql_generator.to_dict()
        if self.answer_generator is not None:
            out["answer_generator"] = self.answer_generator.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RoleLLMSelections":
        data = data or {}

        def _opt(key: str) -> LLMSelection | None:
            raw = data.get(key)
            return LLMSelection.from_dict(raw) if raw else None

        return cls(
            evaluator=_opt("evaluator"),
            sql_generator=_opt("sql_generator"),
            answer_generator=_opt("answer_generator"),
        )

    @classmethod
    def default(cls) -> "RoleLLMSelections":
        return cls()

    def resolve(self, role: str, default: LLMSelection) -> LLMSelection:
        """Return the model configured for `role`, or `default` if unset.

        `default` is the chatbot's main `llm_selection`.
        """
        if role not in ROLE_NAMES:
            raise ValidationError(f"Unknown LLM role: {role!r}")
        selected: LLMSelection | None = getattr(self, role)
        return selected if selected is not None else default
