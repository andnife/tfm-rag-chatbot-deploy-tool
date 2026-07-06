"""Global exception handler for DomainError → structured JSON responses.

Replaces the ad-hoc try/except blocks in every router with a single
handler that returns a consistent error envelope:

    {
      "error": {
        "code": "NOT_FOUND",
        "message": "Human-readable message",
        "detail": { ... }   // optional extra context
      }
    }
"""

import logging
import traceback
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from tfm_rag.domain.errors.auth import InvalidCredentialsError, UserAlreadyExistsError
from tfm_rag.domain.errors.chat import (
    LLMError,
    LLMTimeoutError,
    RetrievalError,
    UnsupportedProviderError,
)
from tfm_rag.domain.errors.chatbot import (
    ChatbotAlreadyExistsError,
    ChatbotNotFoundError,
)
from tfm_rag.domain.errors.common import (
    DomainError,
    NotFoundError,
    TenantScopeViolationError,
    ValidationError,
)
from tfm_rag.domain.errors.evaluation import EvalDatasetError
from tfm_rag.domain.errors.integrations import (
    CredentialNotFoundError,
    CredentialTestFailedError,
    SecretDecryptError,
)
from tfm_rag.domain.errors.knowledge import (
    DatabaseConnectionError,
    IncompatibleEmbeddingsError,
    IngestionFailedError,
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
    SchemaIntrospectionError,
    SourceNotFoundError,
    UnsupportedDatabaseDialectError,
    UnsupportedSourceTypeError,
)

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain error → HTTP status code mapping
# ---------------------------------------------------------------------------
_ERROR_STATUS_MAP: dict[type, int] = {
    # 400 Bad Request
    ValidationError: 400,
    EvalDatasetError: 400,
    UnsupportedDatabaseDialectError: 400,
    DatabaseConnectionError: 400,
    SchemaIntrospectionError: 400,
    IncompatibleEmbeddingsError: 409,
    CredentialTestFailedError: 400,
    # 401 Unauthorized
    InvalidCredentialsError: 401,
    # 404 Not Found
    NotFoundError: 404,
    KnowledgeBaseNotFoundError: 404,
    SourceNotFoundError: 404,
    ChatbotNotFoundError: 404,
    CredentialNotFoundError: 404,
    # 409 Conflict
    UserAlreadyExistsError: 409,
    ChatbotAlreadyExistsError: 409,
    KnowledgeBaseInUseError: 409,
    # 403
    TenantScopeViolationError: 403,
    # 422
    UnsupportedSourceTypeError: 422,
    IngestionFailedError: 422,
    # 501 Not Implemented
    UnsupportedProviderError: 501,
    # 502 Bad Gateway
    LLMError: 502,
    # 504 Gateway Timeout
    LLMTimeoutError: 504,
    RetrievalError: 502,
    SecretDecryptError: 502,
}


# Domain error → human-readable error code string
_ERROR_CODE_MAP: dict[type, str] = {
    ValidationError: "VALIDATION_ERROR",
    EvalDatasetError: "EVAL_DATASET_ERROR",
    NotFoundError: "NOT_FOUND",
    KnowledgeBaseNotFoundError: "KB_NOT_FOUND",
    SourceNotFoundError: "SOURCE_NOT_FOUND",
    ChatbotNotFoundError: "CHATBOT_NOT_FOUND",
    CredentialNotFoundError: "CREDENTIAL_NOT_FOUND",
    IncompatibleEmbeddingsError: "INCOMPATIBLE_EMBEDDINGS",
    KnowledgeBaseInUseError: "KB_IN_USE",
    InvalidCredentialsError: "INVALID_CREDENTIALS",
    UserAlreadyExistsError: "USER_ALREADY_EXISTS",
    ChatbotAlreadyExistsError: "CHATBOT_ALREADY_EXISTS",
    TenantScopeViolationError: "TENANT_SCOPE_VIOLATION",
    UnsupportedProviderError: "UNSUPPORTED_PROVIDER",
    UnsupportedSourceTypeError: "UNSUPPORTED_SOURCE_TYPE",
    UnsupportedDatabaseDialectError: "UNSUPPORTED_DATABASE_DIALECT",
    DatabaseConnectionError: "DATABASE_CONNECTION_ERROR",
    SchemaIntrospectionError: "SCHEMA_INTROSPECTION_ERROR",
    IngestionFailedError: "INGESTION_FAILED",
    LLMError: "LLM_ERROR",
    LLMTimeoutError: "LLM_TIMEOUT",
    RetrievalError: "RETRIEVAL_ERROR",
    CredentialTestFailedError: "CREDENTIAL_TEST_FAILED",
    SecretDecryptError: "SECRET_DECRYPT_ERROR",
}


def _error_code_for(exc: DomainError) -> str:
    for cls in type(exc).__mro__:
        if cls in _ERROR_CODE_MAP:
            return _ERROR_CODE_MAP[cls]
    return "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Incident store (in-memory, persists for process lifetime)
# ---------------------------------------------------------------------------
_incidents: list[dict[str, Any]] = []
_MAX_INCIDENTS = 500  # circular buffer


def _record_incident(
    *,
    status_code: int,
    error_code: str,
    message: str,
    detail: Any,
    path: str,
    method: str,
    tb_str: str,
    source: str = "server",
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    incident_id = str(uuid.uuid4())[:8]
    incident = {
        "id": incident_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "status_code": status_code,
        "error_code": error_code,
        "message": message,
        "detail": detail,
        "path": path,
        "method": method,
        "traceback": tb_str,
        "source": source,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }
    _incidents.append(incident)
    # Keep only the last N incidents
    if len(_incidents) > _MAX_INCIDENTS:
        del _incidents[: len(_incidents) - _MAX_INCIDENTS]
    return incident


def record_client_incident(
    *,
    status_code: int,
    error_code: str,
    message: str,
    detail: Any,
    tenant_id: str,
    user_id: str | None,
    path: str,
) -> dict[str, Any]:
    """Record an incident reported by the frontend (React `ErrorBoundary`).

    Unlike server-side exceptions there's no traceback to capture; instead
    we tag the incident with the reporting tenant/user so operators can
    correlate client-side crashes with a specific account. Same in-memory,
    process-lifetime store as server-side incidents (`get_incidents`) —
    it does NOT survive a restart and is NOT shared across workers.
    """
    return _record_incident(
        status_code=status_code,
        error_code=error_code,
        message=message,
        detail=detail,
        path=path,
        method="CLIENT",
        tb_str="",
        source="frontend",
        tenant_id=tenant_id,
        user_id=user_id,
    )


def get_incidents(
    *,
    limit: int = 50,
    status_code: int | None = None,
) -> list[dict[str, Any]]:
    """Return recent incidents, optionally filtered by status code."""
    items = _incidents
    if status_code is not None:
        items = [i for i in items if i["status_code"] == status_code]
    return list(reversed(items[-limit:]))


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------

async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Global handler registered via app.add_exception_handler."""
    status_code = _ERROR_STATUS_MAP.get(type(exc), 500)
    # Walk MRO to find the closest match
    for cls in type(exc).__mro__:
        if cls in _ERROR_STATUS_MAP:
            status_code = _ERROR_STATUS_MAP[cls]
            break

    error_code = _error_code_for(exc)
    message = str(exc)

    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # Structured log for developers
    _log.error(
        "[%s] %s %s → %d %s: %s",
        request.method,
        request.url.path,
        request.url.query or "",
        status_code,
        error_code,
        message,
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    # Record incident for later querying
    _record_incident(
        status_code=status_code,
        error_code=error_code,
        message=message,
        detail=None,
        path=str(request.url.path),
        method=str(request.method),
        tb_str=tb_str,
    )

    body = {
        "error": {
            "code": error_code,
            "message": message,
        }
    }
    return JSONResponse(status_code=status_code, content=body)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for non-DomainError exceptions (bugs)."""
    incident_id = str(uuid.uuid4())[:8]
    tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    _log.error(
        "[%s] %s → 500 INTERNAL_ERROR [%s]: %s",
        request.method,
        request.url.path,
        incident_id,
        str(exc),
        exc_info=(type(exc), exc, exc.__traceback__),
    )

    _record_incident(
        status_code=500,
        error_code="INTERNAL_ERROR",
        message=f"Internal error [{incident_id}]: {type(exc).__name__}",
        detail=str(exc)[:500],
        path=str(request.url.path),
        method=str(request.method),
        tb_str=tb_str,
    )

    # Never leak internals to the client
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": f"Error interno del servidor [{incident_id}]",
            }
        },
    )
