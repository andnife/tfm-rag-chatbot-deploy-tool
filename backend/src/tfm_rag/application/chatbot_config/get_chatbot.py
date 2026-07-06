from uuid import UUID

from tfm_rag.application.chatbot_config.create_chatbot import ChatbotView, _to_view
from tfm_rag.domain.errors.chatbot import ChatbotNotFoundError
from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.ports.repositories import ChatbotRepositoryPort


async def get_chatbot(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    chatbot_id: UUID,
) -> ChatbotView:
    try:
        chatbot = await chatbot_repo.get_chatbot(chatbot_id)
    except NotFoundError as exc:
        raise ChatbotNotFoundError(str(exc)) from exc
    return _to_view(chatbot)
