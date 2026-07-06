"""Orchestrator: suggest welcome-message variants for a chatbot.

Loads the chatbot (tenant-scoped), gathers its knowledge-base summaries,
resolves the chatbot's LLM endpoint, and delegates to
`generate_welcome_messages`. Returns suggestions WITHOUT persisting — the
admin reviews/edits them in the panel before saving. Used by the
`POST /api/chatbots/{id}/welcome-suggestions` endpoint.
"""
from collections.abc import Awaitable, Callable
from uuid import UUID

from tfm_rag.application.chatbot_config.generate_welcome_messages import (
    WelcomeMessages,
    generate_welcome_messages,
)
from tfm_rag.application.integrations.endpoint_resolver import resolve_inference_target
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.ports.llm import LLMDispatcherPort
from tfm_rag.domain.ports.repositories import (
    ChatbotRepositoryPort,
    KnowledgeBaseRepositoryPort,
    ProviderCredentialRepositoryPort,
)
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor
from tfm_rag.domain.value_objects.llm_selection import LLMSelection


async def _default_resolve_endpoint(
    *,
    credentials_repo: ProviderCredentialRepositoryPort,
    encryptor: SecretEncryptor,
    ollama_base_url: str,
    llm_selection: LLMSelection,
) -> tuple[str, str, str | None]:
    return await resolve_inference_target(
        credential_id=llm_selection.credential_id,
        credentials_repo=credentials_repo,
        encryptor=encryptor,
        ollama_base_url=ollama_base_url,
    )


async def suggest_welcome_messages(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    kb_repo: KnowledgeBaseRepositoryPort,
    credentials_repo: ProviderCredentialRepositoryPort,
    llm_dispatcher: LLMDispatcherPort,
    encryptor: SecretEncryptor,
    ollama_base_url: str,
    chatbot_id: UUID,
    resolve_endpoint_fn: Callable[
        ..., Awaitable[tuple[str, str, str | None]]
    ] = _default_resolve_endpoint,
    generate_fn: Callable[..., Awaitable[WelcomeMessages]] = generate_welcome_messages,
) -> WelcomeMessages:
    try:
        chatbot = await chatbot_repo.get_chatbot(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc

    summaries: list[str] = []
    for kb_id in chatbot.kb_ids:
        try:
            kb = await kb_repo.get_knowledge_base(kb_id)
        except NotFoundError:
            continue
        desc = (kb.description or "").strip()
        summaries.append(f"{kb.name}: {desc}" if desc else kb.name)

    provider_id, base_url, api_key = await resolve_endpoint_fn(
        credentials_repo=credentials_repo,
        encryptor=encryptor,
        ollama_base_url=ollama_base_url,
        llm_selection=chatbot.llm_selection,
    )
    llm = llm_dispatcher.for_provider(provider_id)
    return await generate_fn(
        llm=llm,
        base_url=base_url,
        api_key=api_key,
        model_id=chatbot.llm_selection.model_id,
        system_prompt=chatbot.system_prompt or "",
        kb_summaries=summaries,
    )
