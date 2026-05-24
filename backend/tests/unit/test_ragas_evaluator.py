"""Unit tests for RagasEvaluator with the ragas library stubbed.

We don't call the real RAGAS in unit tests (it would hit a real LLM,
slow + flaky). Instead we mock `ragas.evaluate` and the langchain
wrappers to verify our adapter:
- builds the right ragas EvaluationDataset
- passes the right metrics
- maps ragas results back onto EvaluationCase.scores
"""
from unittest.mock import MagicMock, patch

from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase
from tfm_rag.infrastructure.evaluation.ragas_evaluator import (
    RagasEvaluator,
    RagasMetric,
)


def _case(question: str, answer: str, contexts: list[str], gt: str) -> EvaluationCase:
    return EvaluationCase(
        question=question,
        ground_truth=gt,
        scenario="doc_only",
        metadata={},
        predicted_answer=answer,
        retrieved_contexts=contexts,
        citations=[],
        iterations=[],
    )


def test_ragas_metric_constants_match_ragas_internal_names() -> None:
    """The metric names we expose to callers map 1:1 to RAGAS internal
    column names. This guards against ragas renaming a metric without us
    noticing (the integration test would fail with a missing column).
    """
    assert RagasMetric.FAITHFULNESS == "faithfulness"
    assert RagasMetric.ANSWER_RELEVANCY == "answer_relevancy"
    assert RagasMetric.CONTEXT_PRECISION == "context_precision"
    assert RagasMetric.CONTEXT_RECALL == "context_recall"


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluator_calls_ragas_with_expected_dataset(
    mock_emb_cls,
    mock_llm_cls,
    mock_emb_wrapper,
    mock_llm_wrapper,
    mock_evaluate,
) -> None:
    fake_result = MagicMock()
    fake_df = MagicMock()
    fake_df.to_dict.return_value = {
        "faithfulness": {0: 0.8, 1: 0.6},
        "answer_relevancy": {0: 0.9, 1: 0.7},
        "context_precision": {0: 0.85, 1: 0.55},
        "context_recall": {0: 0.75, 1: 0.5},
    }
    fake_result.to_pandas.return_value = fake_df
    mock_evaluate.return_value = fake_result

    cases = [
        _case("Q1?", "A1.", ["ctx1"], "GT1"),
        _case("Q2?", "A2.", ["ctx2a", "ctx2b"], "GT2"),
    ]

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
    )
    scores = evaluator.evaluate(cases)

    mock_evaluate.assert_called_once()
    kwargs = mock_evaluate.call_args.kwargs
    assert "dataset" in kwargs
    assert "metrics" in kwargs
    metric_names = {m.name for m in kwargs["metrics"]}
    assert metric_names == {
        "faithfulness", "answer_relevancy",
        "context_precision", "context_recall",
    }
    assert len(scores) == 2
    assert scores[0]["faithfulness"] == 0.8
    assert scores[1]["faithfulness"] == 0.6


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluator_skips_cases_with_errors_or_no_contexts(
    mock_emb_cls,
    mock_llm_cls,
    mock_emb_wrapper,
    mock_llm_wrapper,
    mock_evaluate,
) -> None:
    """Cases with .error set or empty retrieved_contexts can't be scored
    (RAGAS needs both contexts AND an answer). The adapter skips them and
    returns an empty score-dict for those positions, preserving alignment.
    """
    fake_result = MagicMock()
    fake_result.to_pandas.return_value.to_dict.return_value = {
        "faithfulness": {0: 0.7},
        "answer_relevancy": {0: 0.8},
        "context_precision": {0: 0.8},
        "context_recall": {0: 0.6},
    }
    mock_evaluate.return_value = fake_result

    good = _case("Q1?", "A1.", ["ctx1"], "GT1")
    err = _case("Q2?", "A2.", ["ctx2"], "GT2")
    err.error = "LLM timeout"
    no_ctx = _case("Q3?", "A3.", [], "GT3")

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([good, err, no_ctx])

    assert len(scores) == 3
    assert scores[0]["faithfulness"] == 0.7
    assert scores[1] == {}
    assert scores[2] == {}


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluator_with_zero_scorable_cases_returns_empty_dicts(
    mock_emb_cls,
    mock_llm_cls,
    mock_emb_wrapper,
    mock_llm_wrapper,
    mock_evaluate,
) -> None:
    """If no cases are scorable, ragas.evaluate is never called and we
    return a same-length list of empty dicts.
    """
    err = _case("Q?", "A", ["c"], "gt")
    err.error = "boom"
    no_ctx = _case("Q?", "A", [], "gt")

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="llama3.1",
        embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([err, no_ctx])

    mock_evaluate.assert_not_called()
    assert scores == [{}, {}]


def test_judge_model_attribute_exposed() -> None:
    """The CLI / report writer reads `evaluator.judge_model` to record it
    in the EvaluationReport. Guard this minimal surface.
    """
    evaluator = RagasEvaluator(
        base_url="http://ollama:11434",
        judge_model="custom-model",
        embedding_model="bge-m3",
    )
    assert evaluator.judge_model == "custom-model"
