from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.middleware.widget_cors import (
    NonOverwritingCORSMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    auth,
    chatbots,
    credentials,
    health,
    ingestion_jobs,
    knowledge_bases,
    public_chat,
    sessions,
)
from tfm_rag.infrastructure.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    settings = get_settings()
    app.add_middleware(TenantScopingMiddleware, settings=settings)
    # Plan #16 will tighten this to per-chatbot allowed_origins (in the
    # widget public endpoint, the chatbot's allowed_origins list narrows
    # the response). Plan #11 ships permissive defaults so the embeddable
    # widget can prototype against a dev backend.
    app.add_middleware(
        NonOverwritingCORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(credentials.router)
    app.include_router(knowledge_bases.router)
    app.include_router(ingestion_jobs.router)
    app.include_router(chatbots.router)
    app.include_router(sessions.router)
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
