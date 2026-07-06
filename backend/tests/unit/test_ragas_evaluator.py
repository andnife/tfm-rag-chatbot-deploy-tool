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
    did_abstain,
)


def _case(
    question: str,
    answer: str,
    contexts: list[str],
    gt: str,
    *,
    scenario: str = "doc_only",
    iterations: list | None = None,
) -> EvaluationCase:
    return EvaluationCase(
        question=question,
        ground_truth=gt,
        scenario=scenario,
        metadata={},
        predicted_answer=answer,
        retrieved_contexts=contexts,
        citations=[],
        iterations=iterations or [],
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


# --- abstain scoring ---------------------------------------------------------


def test_did_abstain_detects_abstain_iteration() -> None:
    case = _case("Q?", "I don't know: no data", [], "I have no information.",
                 scenario="abstain", iterations=[{"tool": "abstain"}])
    assert did_abstain(case) is True


def test_did_abstain_detects_idk_prefix_without_iteration() -> None:
    case = _case("Q?", "I don't know: out of scope", [], "No info.",
                 scenario="abstain", iterations=[])
    assert did_abstain(case) is True


def test_did_abstain_false_when_chatbot_answered() -> None:
    case = _case("Q?", "The capital is Madrid.", ["ctx"], "No info.",
                 scenario="abstain", iterations=[{"tool": "final_answer"}])
    assert did_abstain(case) is False


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_abstain_cases_scored_by_judge_not_ragas_metrics(
    mock_emb_cls, mock_llm_cls, mock_emb_wrapper, mock_llm_wrapper, mock_evaluate,
) -> None:
    """Abstain cases must NOT go through RAGAS (faithfulness/answer_relevancy
    are meaningless for an 'I don't know'); the judge LLM decides abstention
    and they get a binary abstain_accuracy. Judge verdicts: first case abstained
    (SI), second answered (NO).
    """
    mock_llm_cls.return_value.invoke.side_effect = ["SI", "NO"]
    correct = _case("Q?", "I don't know: out of scope", [], "No info.",
                    scenario="abstain", iterations=[{"tool": "abstain"}])
    wrong = _case("Q?", "It is Madrid.", ["leaked ctx"], "No info.",
                  scenario="abstain", iterations=[{"tool": "final_answer"}])

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434", judge_model="llama3.1", embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([correct, wrong])

    mock_evaluate.assert_not_called()  # no scorable non-abstain rows
    assert scores[0] == {RagasMetric.ABSTAIN_ACCURACY: 1.0}
    assert scores[1] == {RagasMetric.ABSTAIN_ACCURACY: 0.0}


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
def test_abstain_scored_semantically_by_judge_not_string_match(mock_ollama_cls) -> None:
    """Abstention detection is semantic (judge LLM), not string matching: a
    genuine Spanish abstention with NO hard-coded phrase ('no tengo información'
    / 'I don't know') must still score 1.0 because the judge recognises it."""
    mock_ollama_cls.return_value.invoke.return_value = "SI"
    case = _case(
        "¿Cuál es la tasa de paro actual de España?",
        "Ese dato no figura en los documentos ni en la base de datos consultada.",
        [], "No hay información disponible.", scenario="abstain",
    )
    evaluator = RagasEvaluator(
        base_url="http://ollama:11434", judge_model="llama3.1", embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([case])
    assert scores[0] == {RagasMetric.ABSTAIN_ACCURACY: 1.0}
    mock_ollama_cls.return_value.invoke.assert_called_once()


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
def test_abstain_judge_detects_non_abstention_answer(mock_ollama_cls) -> None:
    """When the model actually answered (did not abstain), the judge says NO
    and abstain_accuracy is 0.0."""
    mock_ollama_cls.return_value.invoke.return_value = "NO"
    case = _case(
        "¿Cuál es la tasa de paro actual de España?",
        "La tasa de paro de España es del 12 %.",
        [], "No hay información disponible.", scenario="abstain",
    )
    evaluator = RagasEvaluator(
        base_url="http://ollama:11434", judge_model="llama3.1", embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([case])
    assert scores[0] == {RagasMetric.ABSTAIN_ACCURACY: 0.0}


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_abstain_and_doc_cases_mixed(
    mock_emb_cls, mock_llm_cls, mock_emb_wrapper, mock_llm_wrapper, mock_evaluate,
) -> None:
    """Abstain cases are scored by the judge LLM; the doc_only case still goes
    to RAGAS. Positional alignment is preserved.
    """
    mock_llm_cls.return_value.invoke.return_value = "SI"  # judge: abstained
    fake_result = MagicMock()
    fake_result.to_pandas.return_value.to_dict.return_value = {
        "faithfulness": {0: 0.9},
        "answer_relevancy": {0: 0.9},
        "context_precision": {0: 0.9},
        "context_recall": {0: 0.9},
    }
    mock_evaluate.return_value = fake_result

    abstain = _case("Q1?", "I don't know: nope", [], "No info.",
                    scenario="abstain", iterations=[{"tool": "abstain"}])
    doc = _case("Q2?", "Madrid.", ["ctx"], "Madrid is the capital.")

    evaluator = RagasEvaluator(
        base_url="http://ollama:11434", judge_model="llama3.1", embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([abstain, doc])

    mock_evaluate.assert_called_once()
    assert scores[0] == {RagasMetric.ABSTAIN_ACCURACY: 1.0}
    assert scores[1]["faithfulness"] == 0.9


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


# --- judge provider selection (judge ≠ generator) ---------------------------

import pytest  # noqa: E402


def _evaluator(**kw) -> RagasEvaluator:
    base = dict(base_url="http://ollama:11434", judge_model="llama3.1", embedding_model="bge-m3")
    base.update(kw)
    return RagasEvaluator(**base)


def test_build_judge_llm_defaults_to_ollama() -> None:
    w = _evaluator()._build_judge_llm()
    assert type(w.langchain_llm).__name__ == "OllamaLLM"
    assert w.langchain_llm.base_url == "http://ollama:11434"
    assert w.langchain_llm.model == "llama3.1"


def test_build_judge_llm_openai_with_explicit_key() -> None:
    w = _evaluator(
        judge_model="gpt-4o-mini", judge_provider="openai", judge_api_key="sk-test"
    )._build_judge_llm()
    assert type(w.langchain_llm).__name__ == "ChatOpenAI"



def test_build_judge_llm_openai_without_key_raises() -> None:
    ev = _evaluator(judge_model="gpt-4o-mini", judge_provider="openai")
    with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError):
        ev._build_judge_llm()


def test_build_judge_llm_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        _evaluator(judge_provider="bogus")._build_judge_llm()


# --- routing_accuracy (deterministic metric) ---------------------------------

from tfm_rag.infrastructure.evaluation.ragas_evaluator import routing_accuracy  # noqa: E402


def _case_routed(scenario: str, route: str | None) -> EvaluationCase:
    trace = {"route": route} if route is not None else {}
    return EvaluationCase(
        question="Q?", ground_truth="GT", scenario=scenario,
        predicted_answer="A", retrieved_contexts=["c"], routing_trace=trace,
    )


def test_routing_accuracy_correct_route_scores_one() -> None:
    assert routing_accuracy(_case_routed("doc_only", "docs")) == 1.0
    assert routing_accuracy(_case_routed("sql_only", "sql")) == 1.0
    assert routing_accuracy(_case_routed("mixed", "both")) == 1.0


def test_routing_accuracy_wrong_route_scores_zero() -> None:
    assert routing_accuracy(_case_routed("doc_only", "sql")) == 0.0
    assert routing_accuracy(_case_routed("mixed", "docs")) == 0.0


def test_routing_accuracy_not_applicable_returns_none() -> None:
    assert routing_accuracy(_case_routed("abstain", "docs")) is None
    assert routing_accuracy(_case_routed("doc_only", None)) is None


def test_routing_accuracy_metric_constant() -> None:
    assert RagasMetric.ROUTING_ACCURACY == "routing_accuracy"


@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.evaluate")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainLLMWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.LangchainEmbeddingsWrapper")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaLLM")
@patch("tfm_rag.infrastructure.evaluation.ragas_evaluator.OllamaEmbeddings")
def test_evaluate_adds_routing_accuracy(
    mock_emb_cls, mock_llm_cls, mock_emb_wrapper, mock_llm_wrapper, mock_evaluate,
) -> None:
    fake_result = MagicMock()
    fake_df = MagicMock()
    fake_df.to_dict.return_value = {
        "faithfulness": {0: 0.8}, "answer_relevancy": {0: 0.9},
        "context_precision": {0: 0.85}, "context_recall": {0: 0.75},
    }
    fake_result.to_pandas.return_value = fake_df
    mock_evaluate.return_value = fake_result

    case = EvaluationCase(
        question="Q?", ground_truth="GT", scenario="doc_only",
        predicted_answer="A", retrieved_contexts=["ctx"],
        routing_trace={"route": "docs"},
    )
    evaluator = RagasEvaluator(
        base_url="http://o:11434", judge_model="llama3.1", embedding_model="bge-m3",
    )
    scores = evaluator.evaluate([case])
    assert scores[0]["routing_accuracy"] == 1.0
    assert scores[0]["faithfulness"] == 0.8
