import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.pipeline_config import (
    GenerationConfig,
    PipelineConfig,
)


def test_default_is_valid() -> None:
    p = PipelineConfig.default()
    assert p.top_k == 5
    assert p.max_self_correction_retries == 1
    assert p.enable_reranker is False
    assert isinstance(p.generation, GenerationConfig)


def test_default_has_self_correction_retries_one() -> None:
    pc = PipelineConfig.default()
    assert pc.max_self_correction_retries == 1
    assert not hasattr(pc, "agentic_mode")
    assert not hasattr(pc, "max_retrieval_iterations")


def test_self_correction_retries_round_trip() -> None:
    pc = PipelineConfig(max_self_correction_retries=3)
    assert PipelineConfig.from_dict(pc.to_dict()) == pc
    assert "max_self_correction_retries" in pc.to_dict()
    assert "agentic_mode" not in pc.to_dict()
    assert "max_retrieval_iterations" not in pc.to_dict()


@pytest.mark.parametrize("bad", [-1, 4])
def test_self_correction_retries_out_of_range_rejected(bad: int) -> None:
    with pytest.raises(ValidationError, match="max_self_correction_retries"):
        PipelineConfig(max_self_correction_retries=bad)


def test_from_dict_defaults_when_key_absent() -> None:
    # Legacy blob without the new key → default 1; old keys ignored.
    pc = PipelineConfig.from_dict({"top_k": 7, "agentic_mode": False,
                                   "max_retrieval_iterations": 5})
    assert pc.max_self_correction_retries == 1
    assert pc.top_k == 7


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


def test_round_trip_with_generation() -> None:
    p = PipelineConfig(
        top_k=10,
        score_threshold=0.3,
        max_self_correction_retries=2,
        enable_reranker=True,
        reranker_initial_top_k=30,
        abstain_when_insufficient=False,
        generation=GenerationConfig(temperature=0.7, top_p=0.9, max_tokens=2048),
    )
    assert PipelineConfig.from_dict(p.to_dict()) == p


def test_round_trip_default() -> None:
    p = PipelineConfig.default()
    assert PipelineConfig.from_dict(p.to_dict()) == p
