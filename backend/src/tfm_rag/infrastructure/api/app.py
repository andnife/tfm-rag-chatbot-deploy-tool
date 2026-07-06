from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tfm_rag.domain.errors.common import DomainError
from tfm_rag.infrastructure.api.error_handler import (
    domain_error_handler,
    unhandled_error_handler,
)
from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.middleware.widget_cors import (
    PathScopedCORSMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    admin_overview,
    auth,
    chatbots,
    credentials,
    eval_datasets,
    eval_reports,
    eval_runs,
    health,
    incidents,
    ingestion_jobs,
    knowledge_bases,
    ollama_models,
    public_chat,
    sessions,
)
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    # Structured error envelopes ({"error": {code, message}}) + incident
    # recording. Without these, domain errors fall through to FastAPI's
    # default 500 and the frontend can't surface a useful message.
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    # T12: the authenticated API surface is restricted to
    # `settings.frontend_origin` (comma-separated list allowed). The public
    # widget surface (`/api/public/*`) stays permissive at the preflight
    # level — the chatbot owner's `allowed_origins` narrows the actual
    # response per-chatbot inside the route handler (see
    # `application/chat/widget_cors.py`). See `PathScopedCORSMiddleware`
    # docstring for why these can't be a single CORSMiddleware instance.
    frontend_origins = [
        origin.strip()
        for origin in settings.frontend_origin.split(",")
        if origin.strip()
    ]
    app.add_middleware(
        PathScopedCORSMiddleware,
        restricted_origins=frontend_origins,
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credentials.router)
    app.include_router(knowledge_bases.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(chatbots.router)
    app.include_router(sessions.router)
    app.include_router(ollama_models.router)
    app.include_router(eval_datasets.router)
    app.include_router(eval_reports.router)
    app.include_router(eval_runs.router)
    app.include_router(admin_overview.router)
    app.include_router(incidents.router)
    app.include_router(public_chat.router)
    # Serve the embeddable widget JS + demo HTML from the `widget/` directory
    # at the repo root. The path is resolved relative to this file so it
    # works regardless of cwd.
    widget_dir = Path(__file__).resolve().parents[5] / "widget"
    if widget_dir.is_dir():
        app.mount(
            "/widget",
            StaticFiles(directory=str(widget_dir), html=True),
            name="widget",
        )
    return app


app = create_app()
