from uuid import uuid4

import pytest
from fastapi import HTTPException

from tfm_rag.infrastructure.api.dependencies import require_superadmin
from tfm_rag.infrastructure.persistence.repository import RequestContext


def test_require_superadmin_allows_superadmin() -> None:
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4(), is_superadmin=True)
    assert require_superadmin(ctx) is ctx


def test_require_superadmin_forbids_normal_user() -> None:
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4(), is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        require_superadmin(ctx)
    assert exc.value.status_code == 403


def test_request_context_defaults_not_superadmin() -> None:
    ctx = RequestContext(tenant_id=uuid4())
    assert ctx.is_superadmin is False
