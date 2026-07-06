from tfm_rag.domain.catalog.routes import ROUTE_DOCS
from tfm_rag.domain.value_objects.grade_verdict import GradeVerdict
from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration
from tfm_rag.domain.value_objects.routing_trace import RoutingTrace


def test_round_trip() -> None:
    trace = RoutingTrace(
        route=ROUTE_DOCS, rationale="factual",
        attempts=[RetrievalIteration(index=0, tool="docs", query="q",
                                     num_chunks=3, latency_ms=12.0)],
    )
    d = trace.to_dict()
    assert d["route"] == ROUTE_DOCS
    assert RoutingTrace.from_dict(d) == trace


def test_empty_attempts() -> None:
    trace = RoutingTrace(route="normal", rationale="greeting", attempts=[])
    assert RoutingTrace.from_dict(trace.to_dict()) == trace


def test_round_trip_with_verdicts() -> None:
    trace = RoutingTrace(
        route=ROUTE_DOCS, rationale="factual",
        attempts=[RetrievalIteration(index=0, tool="docs", query="q",
                                     num_chunks=3, latency_ms=1.0)],
        verdicts=[GradeVerdict(sufficient=False, reformulated_query="q2"),
                  GradeVerdict(sufficient=True)],
    )
    d = trace.to_dict()
    assert len(d["verdicts"]) == 2
    assert RoutingTrace.from_dict(d) == trace


def test_from_dict_b1_blob_without_verdicts() -> None:
    trace = RoutingTrace.from_dict(
        {"route": "normal", "rationale": "greeting", "attempts": []}
    )
    assert trace.verdicts == []
