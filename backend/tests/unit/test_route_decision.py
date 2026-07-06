import pytest

from tfm_rag.domain.catalog.routes import (
    ROUTE_BOTH,
    ROUTE_DOCS,
    ROUTE_NAMES,
    ROUTE_NORMAL,
    ROUTE_SQL,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.route_decision import RouteDecision


def test_route_names_are_the_four() -> None:
    assert ROUTE_NAMES == (ROUTE_NORMAL, ROUTE_DOCS, ROUTE_SQL, ROUTE_BOTH)


def test_round_trip() -> None:
    d = RouteDecision(route=ROUTE_DOCS, rationale="factual", raw={"x": 1})
    assert RouteDecision.from_dict(d.to_dict()) == d


def test_unknown_route_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown route"):
        RouteDecision(route="nope", rationale="", raw={})
