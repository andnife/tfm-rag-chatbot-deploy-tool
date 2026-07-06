import pytest

from tfm_rag.application.chat.metering import MeteringLLM, TokenMeter
from tfm_rag.domain.value_objects.retrieval_iteration import (
    LLMTextResponse,
    TokenUsage,
)


class _FakeLLM:
    async def generate(self, **kwargs):
        return LLMTextResponse(text="ok", usage=TokenUsage(11, 4))


@pytest.mark.asyncio
async def test_metering_llm_accumulates_and_passes_through() -> None:
    meter = TokenMeter()
    llm = MeteringLLM(_FakeLLM(), meter)
    r1 = await llm.generate(
        base_url="b", api_key=None, model_id="m", messages=[], tools=None,
        temperature=0.0, top_p=1.0, max_tokens=10,
    )
    await llm.generate(
        base_url="b", api_key=None, model_id="m", messages=[], tools=None,
        temperature=0.0, top_p=1.0, max_tokens=10,
    )
    assert r1.text == "ok"  # pass-through unchanged
    assert meter.prompt_tokens == 22
    assert meter.completion_tokens == 8


def test_token_meter_record_ignores_none() -> None:
    m = TokenMeter()
    m.record(None)
    m.record(TokenUsage(5, 1))
    assert m.prompt_tokens == 5 and m.completion_tokens == 1
