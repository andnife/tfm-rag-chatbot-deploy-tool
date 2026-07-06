"""The structured error handlers must be registered on the app, otherwise
domain errors leak as FastAPI's default {detail} envelope and incidents are
never recorded. Also guards the envelope shape the frontend parses.
"""
from unittest.mock import MagicMock

import pytest

from tfm_rag.domain.errors.common import DomainError
from tfm_rag.domain.errors.knowledge import KnowledgeBaseInUseError
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.error_handler import domain_error_handler


def test_app_registers_exception_handlers() -> None:
    app = create_app()
    handlers = app.exception_handlers
    assert DomainError in handlers
    assert Exception in handlers


@pytest.mark.asyncio
async def test_domain_error_handler_emits_structured_envelope() -> None:
    request = MagicMock()
    request.method = "DELETE"
    request.url.path = "/api/knowledge-bases/x"
    request.url.query = ""

    resp = await domain_error_handler(request, KnowledgeBaseInUseError("in use"))

    assert resp.status_code == 409
    import json
    body = json.loads(resp.body)
    assert body["error"]["code"] == "KB_IN_USE"
    assert body["error"]["message"] == "in use"
