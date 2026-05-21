import pytest
from uuid import uuid4

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import (
    GenerationConfig,
    PipelineConfig,
)


def test_default_is_valid() -> None:
    p = PipelineConfig.default()
    assert p.top_k == 5
    assert p.max_retrieval_iterations == 3
    assert p.agentic_mode is True
    assert p.enable_reranker is False
    assert isinstance(p.generation, GenerationConfig)


def test_max_iterations_above_5_rejected() -> None:
    with pytest.raises(ValidationError, match="max_retrieval_iterations"):
        PipelineConfig(max_retrieval_iterations=6)


def test_max_iterations_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="max_retrieval_iterations"):
        PipelineConfig(max_retrieval_iterations=0)


def test_top_k_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="top_k"):
        PipelineConfig(top_k=0)


def test_score_threshold_above_1_rejected() -> None:
    with pytest.raises(ValidationError, match="score_threshold"):
        PipelineConfig(score_threshold=1.5)


def test_generation_temperature_above_2_rejected() -> None:
    with pytest.raises(ValidationError, match="temperature"):
        GenerationConfig(temperature=3.0)


def test_generation_max_tokens_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="max_tokens"):
        GenerationConfig(max_tokens=0)


def test_round_trip_with_router_and_generation() -> None:
    router = LLMSelection(provider_id="ollama", credential_id=uuid4(), model_id="llama3.1")
    p = PipelineConfig(
        top_k=10,
        score_threshold=0.3,
        agentic_mode=False,
        max_retrieval_iterations=2,
        enable_reranker=True,
        reranker_initial_top_k=30,
        abstain_when_insufficient=False,
        router_llm_selection=router,
        generation=GenerationConfig(temperature=0.7, top_p=0.9, max_tokens=2048),
    )
    assert PipelineConfig.from_dict(p.to_dict()) == p


def test_round_trip_default() -> None:
    p = PipelineConfig.default()
    assert PipelineConfig.from_dict(p.to_dict()) == p
