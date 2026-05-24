import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


def test_evaluation_case_minimal_input_fields() -> None:
    case = EvaluationCase(
        question="When did the war end?",
        ground_truth="In 1939.",
        scenario="doc_only",
        metadata={"difficulty": "easy"},
    )
    assert case.question == "When did the war end?"
    assert case.ground_truth == "In 1939."
    assert case.scenario == "doc_only"
    assert case.metadata == {"difficulty": "easy"}
    assert case.predicted_answer is None
    assert case.retrieved_contexts == []
    assert case.citations == []
    assert case.iterations == []
    assert case.scores is None
    assert case.error is None


def test_evaluation_case_with_prediction_and_scores() -> None:
    case = EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario="doc_only",
        metadata={},
        predicted_answer="a",
        retrieved_contexts=["chunk-a", "chunk-b"],
        citations=[{"source_name": "f.pdf"}],
        iterations=[{"index": 0, "tool": "search_docs"}],
        scores={"faithfulness": 0.87, "answer_relevancy": 0.95},
    )
    assert case.predicted_answer == "a"
    assert case.retrieved_contexts == ["chunk-a", "chunk-b"]
    assert case.scores["faithfulness"] == 0.87


def test_evaluation_case_empty_question_rejected() -> None:
    with pytest.raises(ValidationError):
        EvaluationCase(
            question="   ",
            ground_truth="gt",
            scenario="doc_only",
            metadata={},
        )


def test_evaluation_case_to_dict_round_trip() -> None:
    case = EvaluationCase(
        question="q",
        ground_truth="gt",
        scenario="doc_only",
        metadata={"d": "easy"},
        predicted_answer="a",
        retrieved_contexts=["x"],
        scores={"faithfulness": 0.7},
    )
    data = case.to_dict()
    assert data["question"] == "q"
    assert data["scenario"] == "doc_only"
    assert data["predicted_answer"] == "a"
    assert data["retrieved_contexts"] == ["x"]
    assert data["scores"] == {"faithfulness": 0.7}
    assert data["error"] is None
