from uuid import uuid4

import pytest

from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.value_objects.sql_plan import SqlPlan


def test_round_trip_serialises_source_id_as_str() -> None:
    sid = uuid4()
    plan = SqlPlan(source_id=sid, sql="SELECT count(*) FROM users")
    d = plan.to_dict()
    assert d["source_id"] == str(sid)
    assert d["sql"] == "SELECT count(*) FROM users"
    assert SqlPlan.from_dict(d) == plan


def test_blank_sql_rejected() -> None:
    with pytest.raises(ValidationError, match="sql"):
        SqlPlan(source_id=uuid4(), sql="   ")


def test_from_dict_ignores_legacy_is_final_key() -> None:
    # Old traces may carry an is_final key; from_dict must not choke on it.
    sid = uuid4()
    legacy = {"source_id": str(sid), "sql": "SELECT 1", "is_final": False}
    assert SqlPlan.from_dict(legacy) == SqlPlan(source_id=sid, sql="SELECT 1")
