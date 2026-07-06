from tfm_rag.domain.value_objects.evaluation_case import EvaluationCase


def test_evaluation_case_carries_and_serializes_routing_trace() -> None:
    trace = {"route": "docs", "rationale": "factual", "attempts": [], "verdicts": []}
    case = EvaluationCase(
        question="Q?", ground_truth="GT", scenario="doc_only",
        predicted_answer="A", retrieved_contexts=["ctx"],
        routing_trace=trace,
    )
    assert case.routing_trace == trace
    assert case.to_dict()["routing_trace"] == trace


def test_evaluation_case_routing_trace_defaults_empty() -> None:
    case = EvaluationCase(question="Q?", ground_truth="GT", scenario="doc_only")
    assert case.routing_trace == {}
    assert case.to_dict()["routing_trace"] == {}


def test_evaluation_case_token_fields_default_zero() -> None:
    case = EvaluationCase(question="Q?", ground_truth="GT", scenario="doc_only")
    assert case.prompt_tokens == 0
    assert case.completion_tokens == 0


def test_evaluation_case_token_fields_round_trip_in_to_dict() -> None:
    case = EvaluationCase(
        question="Q?", ground_truth="GT", scenario="doc_only",
        prompt_tokens=42, completion_tokens=17,
    )
    data = case.to_dict()
    assert data["prompt_tokens"] == 42
    assert data["completion_tokens"] == 17


def test_evaluation_case_token_fields_settable() -> None:
    case = EvaluationCase(question="Q?", ground_truth="GT", scenario="doc_only")
    case.prompt_tokens = 10
    case.completion_tokens = 4
    assert case.to_dict()["prompt_tokens"] == 10
    assert case.to_dict()["completion_tokens"] == 4
