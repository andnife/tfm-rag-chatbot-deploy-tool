"""Unified abstention message generation.

All three abstention paths (docs grader insufficient, SQL no data, and the
synthesis-time self-refusal) converge here so the bot declines with ONE
consistent, LLM-generated message — in the conversation's language, with the
bot's persona — instead of the previous mix of hardcoded English strings and
free-form refusals. Each caller passes the *cause* so the message can state
accurately why it could not answer.
"""

from enum import StrEnum
from typing import Any, Protocol

from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMResponse,
    LLMTextResponse,
    LLMToolCall,
)


class _LLM(Protocol):
    async def generate(self, **kwargs: Any) -> LLMResponse: ...


class AbstainCause(StrEnum):
    DOCS_INSUFFICIENT = "docs_insufficient"
    SQL_NO_DATA = "sql_no_data"
    BOTH_INSUFFICIENT = "both_insufficient"
    SYNTHESIS_DECLINED = "synthesis_declined"


# Internal context per cause (kept in English like the other pipeline prompts;
# this is CONTEXT for the model, not the output text — the output language is
# fixed by the "same language as the question" rule + the bot persona).
_CAUSE_CONTEXT: dict[AbstainCause, str] = {
    AbstainCause.DOCS_INSUFFICIENT:
        "The knowledge-base documents do not contain the requested information.",
    AbstainCause.SQL_NO_DATA:
        "The database query returned no results for what was asked.",
    AbstainCause.BOTH_INSUFFICIENT:
        "Neither the documents nor the database contain the requested information.",
    AbstainCause.SYNTHESIS_DECLINED:
        "The retrieved information is not enough to answer the question confidently.",
}

_ABSTAIN_SYSTEM = (
    "The system could not find the information needed to answer. Write ONE short, "
    "polite, honest reply, in the same language as the user's question, stating "
    "that you don't have that information. Do not invent data or cite sources; if "
    "natural, suggest rephrasing or another channel. Follow the assistant persona "
    "above for tone."
)


def _text_of(resp: LLMResponse) -> str:
    if isinstance(resp, LLMTextResponse):
        return resp.text
    if isinstance(resp, LLMToolCall):
        return str(resp.arguments.get("answer", ""))
    return ""


async def generate_abstention(
    *,
    llm: _LLM,
    base_url: str,
    api_key: str | None,
    model_id: str,
    generation: GenerationConfig,
    system_prompt: str,
    user_message: str,
    cause: AbstainCause,
    detail: str | None = None,
) -> str:
    """Produce a single polite abstention message via the answer LLM."""
    context = _CAUSE_CONTEXT[cause]
    if detail:
        context += f" Detail: {detail}"
    system = f"{system_prompt}\n\n{_ABSTAIN_SYSTEM}\n\nContext: {context}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]
    resp = await llm.generate(
        base_url=base_url, api_key=api_key, model_id=model_id,
        messages=messages, tools=None,
        temperature=generation.temperature, top_p=generation.top_p,
        max_tokens=generation.max_tokens,
    )
    return _text_of(resp)
