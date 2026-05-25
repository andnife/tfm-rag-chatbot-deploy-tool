from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tfm_rag.infrastructure.api.middleware.tenant_scoping import (
    TenantScopingMiddleware,
)
from tfm_rag.infrastructure.api.routers import (
    auth,
    chatbots,
    credentials,
    health,
    ingestion_jobs,
    knowledge_bases,
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
        CORSMiddleware,
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
    return app


app = create_app()
