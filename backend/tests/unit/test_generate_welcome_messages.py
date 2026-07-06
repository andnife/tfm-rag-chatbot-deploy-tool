"""Unit tests for the welcome-message generation use case (P0.2)."""
import json

import pytest

from tfm_rag.application.chatbot_config.generate_welcome_messages import (
    DEFAULT_ANONYMOUS,
    DEFAULT_NAMED,
    WelcomeMessages,
    generate_welcome_messages,
)
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    LLMToolCall,
)


class _FakeLLM:
    """Stand-in for the LLMProvider port. Returns a canned response or
    raises, and records the messages it was called with."""

    def __init__(self, *, text: str | None = None, exc: Exception | None = None,
                 response: object | None = None) -> None:
        self._text = text
        self._exc = exc
        self._response = response
        self.calls: list[dict[str, object]] = []

    async def generate(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self._exc is not None:
            raise self._exc
        if self._response is not None:
            return self._response
        return LLMTextResponse(text=self._text or "")


async def _run(llm: _FakeLLM) -> WelcomeMessages:
    return await generate_welcome_messages(
        llm=llm,
        base_url="http://x",
        api_key=None,
        model_id="m",
        system_prompt="Eres el asistente de la tienda.",
        kb_summaries=["Catálogo de productos", "FAQ de devoluciones"],
        temperature=0.7,
    )


@pytest.mark.asyncio
async def test_generates_two_variants_from_llm_json() -> None:
    llm = _FakeLLM(text=(
        '{"anonymous": "¡Hola! Pregúntame sobre productos y devoluciones.", '
        '"named": "¡Hola {name}! Pregúntame sobre productos y devoluciones."}'
    ))
    out = await _run(llm)
    assert out.anonymous == "¡Hola! Pregúntame sobre productos y devoluciones."
    assert out.named == "¡Hola {name}! Pregúntame sobre productos y devoluciones."
    assert "{name}" in out.named


@pytest.mark.asyncio
async def test_json_extracted_from_markdown_fences() -> None:
    llm = _FakeLLM(text=(
        "```json\n"
        '{"anonymous": "Bienvenido.", "named": "Bienvenido, {name}."}\n'
        "```"
    ))
    out = await _run(llm)
    assert out.anonymous == "Bienvenido."
    assert out.named == "Bienvenido, {name}."


@pytest.mark.asyncio
async def test_kb_summaries_and_prompt_passed_to_llm() -> None:
    llm = _FakeLLM(text='{"anonymous": "a", "named": "{name} a"}')
    await _run(llm)
    sent = " ".join(
        str(m.get("content", "")) for m in llm.calls[0]["messages"]  # type: ignore[union-attr]
    )
    assert "Catálogo de productos" in sent
    assert "tienda" in sent  # the chatbot system prompt informs the greeting


@pytest.mark.asyncio
async def test_fallback_on_llm_error() -> None:
    llm = _FakeLLM(exc=RuntimeError("endpoint down"))
    out = await _run(llm)
    assert out.anonymous == DEFAULT_ANONYMOUS
    assert out.named == DEFAULT_NAMED


@pytest.mark.asyncio
async def test_fallback_on_unparseable_json() -> None:
    llm = _FakeLLM(text="lo siento, aquí tienes tu saludo: hola!")
    out = await _run(llm)
    assert out == WelcomeMessages(DEFAULT_ANONYMOUS, DEFAULT_NAMED)


@pytest.mark.asyncio
async def test_fallback_when_named_missing_name_placeholder() -> None:
    # If the model forgets {name} in the personalised variant, fall back so
    # the named greeting always supports substitution.
    llm = _FakeLLM(text='{"anonymous": "Hola.", "named": "Hola amigo."}')
    out = await _run(llm)
    assert out == WelcomeMessages(DEFAULT_ANONYMOUS, DEFAULT_NAMED)


@pytest.mark.asyncio
async def test_fallback_on_tool_call_response() -> None:
    # tools=None, but defensively a tool-call reply must not crash.
    llm = _FakeLLM(response=LLMToolCall(tool="final_answer", arguments={}))
    out = await _run(llm)
    assert out == WelcomeMessages(DEFAULT_ANONYMOUS, DEFAULT_NAMED)


@pytest.mark.asyncio
async def test_overlong_variants_are_clamped_to_widget_limit() -> None:
    long = "x" * 800
    llm = _FakeLLM(text=json.dumps({"anonymous": long, "named": "{name} " + long}))
    out = await _run(llm)
    assert len(out.anonymous) <= 500
    assert len(out.named) <= 500
    assert "{name}" in out.named
