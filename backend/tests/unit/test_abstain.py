import pytest

from tfm_rag.application.chat.abstain import (
    AbstainCause,
    generate_abstention,
)
from tfm_rag.domain.value_objects.pipeline_config import GenerationConfig
from tfm_rag.domain.value_objects.retrieval_iteration import LLMTextResponse


class _FakeLLM:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    async def generate(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return LLMTextResponse(text=self._text)


async def _call(llm: _FakeLLM, cause: AbstainCause, detail: str | None = None) -> str:
    return await generate_abstention(
        llm=llm, base_url="http://x", api_key=None, model_id="m",
        generation=GenerationConfig(), system_prompt="Eres el asistente X.",
        user_message="¿Quién es el rector?", cause=cause, detail=detail,
    )


@pytest.mark.asyncio
async def test_returns_llm_text() -> None:
    llm = _FakeLLM("No dispongo de esa información.")
    out = await _call(llm, AbstainCause.DOCS_INSUFFICIENT)
    assert out == "No dispongo de esa información."


@pytest.mark.asyncio
async def test_persona_and_question_reach_the_model() -> None:
    llm = _FakeLLM("...")
    await _call(llm, AbstainCause.DOCS_INSUFFICIENT)
    messages = llm.calls[0]["messages"]
    system = messages[0]["content"]
    user = messages[-1]["content"]
    # Persona (bot's configured language/tone) is preserved.
    assert "Eres el asistente X." in system
    # Language rule is delegated to the model, not hardcoded to Spanish.
    assert "same language as the user's question".lower() in system.lower()
    # The user's actual question is passed so the reply can be contextual.
    assert "¿Quién es el rector?" in user


@pytest.mark.asyncio
async def test_cause_context_differs_per_cause() -> None:
    docs = _FakeLLM("x")
    sql = _FakeLLM("x")
    await _call(docs, AbstainCause.DOCS_INSUFFICIENT)
    await _call(sql, AbstainCause.SQL_NO_DATA)
    docs_system = docs.calls[0]["messages"][0]["content"].lower()
    sql_system = sql.calls[0]["messages"][0]["content"].lower()
    assert "document" in docs_system
    assert "database" in sql_system
    assert docs_system != sql_system


@pytest.mark.asyncio
async def test_detail_is_included_when_provided() -> None:
    llm = _FakeLLM("x")
    await _call(llm, AbstainCause.DOCS_INSUFFICIENT, detail="no rector data in files")
    system = llm.calls[0]["messages"][0]["content"]
    assert "no rector data in files" in system
