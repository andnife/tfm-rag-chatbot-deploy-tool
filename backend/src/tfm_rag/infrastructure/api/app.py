from fastapi import FastAPI

from tfm_rag.infrastructure.api.routers import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="TFM RAG Chatbot Platform",
        version="0.1.0",
    )
    app.include_router(health.router)
    return app


app = create_app()
