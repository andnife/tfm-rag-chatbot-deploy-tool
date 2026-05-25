from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tfm_rag.application.chat.answer_query import AnswerView, answer_query
from tfm_rag.application.chat.list_sessions import (
    SessionSummaryView,
    list_sessions,
)
from tfm_rag.application.chatbot_config.create_chatbot import (
    ChatbotView,
    create_chatbot,
)
from tfm_rag.application.chatbot_config.delete_chatbot import delete_chatbot
from tfm_rag.application.chatbot_config.get_chatbot import get_chatbot
from tfm_rag.application.chatbot_config.list_chatbots import list_chatbots
from tfm_rag.application.chatbot_config.update_chatbot import update_chatbot
from tfm_rag.domain.errors.chat import LLMError, LLMTimeoutError
from tfm_rag.domain.errors.chatbot import (
    ChatbotAlreadyExistsError,
    ChatbotNotFoundError,
)
from tfm_rag.domain.errors.common import ValidationError
from tfm_rag.domain.errors.knowledge import (
    IncompatibleEmbeddingsError,
    KnowledgeBaseNotFoundError,
)
from tfm_rag.domain.value_objects.citation import Citation
from tfm_rag.domain.value_objects.llm_selection import LLMSelection
from tfm_rag.domain.value_objects.pipeline_config import (
    GenerationConfig,
    PipelineConfig,
)
from tfm_rag.domain.value_objects.retrieval_iteration import RetrievalIteration
from tfm_rag.domain.value_objects.widget_config import WidgetConfig
from tfm_rag.infrastructure.api.dependencies import (
    get_current_context,
    get_session,
)
from tfm_rag.infrastructure.embedders.dispatcher import EmbedderDispatcher
from tfm_rag.infrastructure.llm_providers.dispatcher import LLMDispatcher
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings, get_settings
from tfm_rag.infrastructure.vector_store.qdrant_client import QdrantStore

router = APIRouter(prefix="/api/chatbots", tags=["chatbots"])


# --- Input models -----------------------------------------------------------

class LLMSelectionIn(BaseModel):
    provider_id: str
    credential_id: UUID
    model_id: str

    def to_vo(self) -> LLMSelection:
        return LLMSelection(
            provider_id=self.provider_id,
            credential_id=self.credential_id,
            model_id=self.model_id,
        )


class GenerationConfigIn(BaseModel):
    temperature: float = 0.2
    top_p: float = 1.0
    max_tokens: int = Field(default=1024, ge=1, le=32_000)

    def to_vo(self) -> GenerationConfig:
        return GenerationConfig(
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
        )


class PipelineConfigIn(BaseModel):
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    agentic_mode: bool = True
    max_retrieval_iterations: int = Field(default=3, ge=1, le=5)
    enable_reranker: bool = False
    reranker_initial_top_k: int = Field(default=30, ge=1, le=200)
    abstain_when_insufficient: bool = True
    router_llm_selection: LLMSelectionIn | None = None
    generation: GenerationConfigIn = Field(default_factory=GenerationConfigIn)

    def to_vo(self) -> PipelineConfig:
        return PipelineConfig(
            top_k=self.top_k,
            score_threshold=self.score_threshold,
            agentic_mode=self.agentic_mode,
            max_retrieval_iterations=self.max_retrieval_iterations,
            enable_reranker=self.enable_reranker,
            reranker_initial_top_k=self.reranker_initial_top_k,
            abstain_when_insufficient=self.abstain_when_insufficient,
            router_llm_selection=(
                self.router_llm_selection.to_vo()
                if self.router_llm_selection
                else None
            ),
            generation=self.generation.to_vo(),
        )


class WidgetConfigIn(BaseModel):
    theme: Literal["light", "dark"] = "light"
    primary_color: str = "#3b82f6"
    position: Literal["bottom-right", "bottom-left"] = "bottom-right"
    title: str = Field(default="Asistente", min_length=1, max_length=60)
    welcome_message: str = Field(
        default="¿En qué puedo ayudarte?", min_length=1, max_length=500
    )
    placeholder: str = Field(
        default="Escribe tu pregunta...", min_length=1, max_length=100
    )
    allowed_origins: list[str] = Field(default_factory=list, max_length=50)

    def to_domain(self) -> WidgetConfig:
        return WidgetConfig.from_dict(self.model_dump())


class WidgetConfigOut(BaseModel):
    theme: str
    primary_color: str
    position: str
    title: str
    welcome_message: str
    placeholder: str
    allowed_origins: list[str]

    @classmethod
    def from_domain(cls, raw: dict[str, Any]) -> "WidgetConfigOut":
        # Use VO's tolerant from_dict so legacy partial rows still work.
        vo = WidgetConfig.from_dict(raw or {})
        return cls(**vo.to_dict())


class CreateChatbotIn(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    llm_selection: LLMSelectionIn
    kb_ids: list[UUID] = Field(default_factory=list)
    pipeline_config: PipelineConfigIn = Field(default_factory=PipelineConfigIn)
    widget_config: WidgetConfigIn = Field(default_factory=WidgetConfigIn)


class UpdateChatbotIn(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    llm_selection: LLMSelectionIn | None = None
    kb_ids: list[UUID] | None = None
    pipeline_config: PipelineConfigIn | None = None
    widget_config: WidgetConfigIn | None = None


# --- Output models ----------------------------------------------------------

class ChatbotOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: str | None
    system_prompt: str
    llm_selection: dict[str, Any]
    pipeline_config: dict[str, Any]
    widget_config: WidgetConfigOut
    kb_ids: list[str]
    public_key: str

    @classmethod
    def from_view(cls, v: ChatbotView) -> "ChatbotOut":
        return cls(
            id=str(v.id),
            tenant_id=str(v.tenant_id),
            name=v.name,
            description=v.description,
            system_prompt=v.system_prompt,
            llm_selection=v.llm_selection.to_dict(),
            pipeline_config=v.pipeline_config.to_dict(),
            widget_config=WidgetConfigOut.from_domain(v.widget_config),
            kb_ids=[str(i) for i in v.kb_ids],
            public_key=v.public_key,
        )


# --- Routes -----------------------------------------------------------------

@router.post("", status_code=201, response_model=ChatbotOut)
async def create_(
    body: CreateChatbotIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotOut:
    try:
        view = await create_chatbot(
            session, ctx,
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            llm_selection=body.llm_selection.to_vo(),
            kb_ids=body.kb_ids,
            pipeline_config=body.pipeline_config.to_vo(),
            widget_config=body.widget_config.to_domain(),
        )
    except ChatbotAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ChatbotOut.from_view(view)


@router.get("", response_model=list[ChatbotOut])
async def list_(
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[ChatbotOut]:
    views = await list_chatbots(session, ctx, limit=limit, offset=offset)
    return [ChatbotOut.from_view(v) for v in views]


@router.get("/{chatbot_id}", response_model=ChatbotOut)
async def get_(
    chatbot_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotOut:
    try:
        view = await get_chatbot(session, ctx, chatbot_id=chatbot_id)
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ChatbotOut.from_view(view)


@router.patch("/{chatbot_id}", response_model=ChatbotOut)
async def patch_(
    chatbot_id: UUID,
    body: UpdateChatbotIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> ChatbotOut:
    try:
        view = await update_chatbot(
            session, ctx,
            chatbot_id=chatbot_id,
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            llm_selection=body.llm_selection.to_vo() if body.llm_selection else None,
            kb_ids=body.kb_ids,
            pipeline_config=body.pipeline_config.to_vo() if body.pipeline_config else None,
            widget_config=(
                body.widget_config.to_domain() if body.widget_config is not None else None
            ),
        )
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ChatbotOut.from_view(view)


@router.delete("/{chatbot_id}", status_code=204)
async def delete_(
    chatbot_id: UUID,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> None:
    try:
        await delete_chatbot(session, ctx, chatbot_id=chatbot_id)
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


class SessionSummaryOut(BaseModel):
    id: str
    chatbot_id: str
    origin: str
    created_at: str
    last_activity_at: str

    @classmethod
    def from_view(cls, v: SessionSummaryView) -> "SessionSummaryOut":
        return cls(
            id=str(v.id),
            chatbot_id=str(v.chatbot_id),
            origin=v.origin,
            created_at=v.created_at.isoformat(),
            last_activity_at=v.last_activity_at.isoformat(),
        )


@router.get("/{chatbot_id}/sessions", response_model=list[SessionSummaryOut])
async def list_sessions_(
    chatbot_id: UUID,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> list[SessionSummaryOut]:
    try:
        views = await list_sessions(
            session, ctx,
            chatbot_id=chatbot_id,
            limit=limit, offset=offset,
        )
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [SessionSummaryOut.from_view(v) for v in views]


# --- Chat endpoint ----------------------------------------------------------

class ChatIn(BaseModel):
    session_id: UUID | None = None
    message: str = Field(..., min_length=1, max_length=8000)


class _CitationOut(BaseModel):
    chunk_id: str
    source_id: str
    source_name: str
    location: str
    score: float

    @classmethod
    def from_vo(cls, c: Citation) -> "_CitationOut":
        return cls(
            chunk_id=c.chunk_id,
            source_id=str(c.source_id),
            source_name=c.source_name,
            location=c.location,
            score=c.score,
        )


class _IterationOut(BaseModel):
    index: int
    tool: str
    query: str | None
    num_chunks: int | None
    latency_ms: float

    @classmethod
    def from_vo(cls, it: RetrievalIteration) -> "_IterationOut":
        return cls(
            index=it.index, tool=it.tool, query=it.query,
            num_chunks=it.num_chunks, latency_ms=it.latency_ms,
        )


class ChatOut(BaseModel):
    session_id: str
    message_id: str
    content: str
    citations: list[_CitationOut]
    iterations: list[_IterationOut]

    @classmethod
    def from_view(cls, v: AnswerView) -> "ChatOut":
        return cls(
            session_id=str(v.session_id),
            message_id=str(v.message_id),
            content=v.content,
            citations=[_CitationOut.from_vo(c) for c in v.citations],
            iterations=[_IterationOut.from_vo(i) for i in v.iterations],
        )


@router.post("/{chatbot_id}/chat", response_model=ChatOut)
async def chat_(
    chatbot_id: UUID,
    body: ChatIn,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ChatOut:
    # Match the existing per-request pattern in knowledge_bases.py: create
    # QdrantStore here and close it in `finally`. Dispatchers are stateless
    # and rebuilt per-request (cheap — see EmbedderDispatcher.default()).
    qdrant = QdrantStore(settings.qdrant_url, settings.qdrant_api_key)
    try:
        view = await answer_query(
            session, ctx,
            llm_dispatcher=LLMDispatcher.default(),
            qdrant=qdrant,
            embedder_dispatcher=EmbedderDispatcher.default(),
            settings=settings,
            chatbot_id=chatbot_id,
            session_id=body.session_id,
            user_message=body.message,
        )
    except ChatbotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except IncompatibleEmbeddingsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        await qdrant.close()
    return ChatOut.from_view(view)
