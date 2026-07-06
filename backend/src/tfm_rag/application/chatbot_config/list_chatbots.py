from tfm_rag.application.chatbot_config.create_chatbot import ChatbotView, _to_view
from tfm_rag.domain.ports.repositories import ChatbotRepositoryPort


async def list_chatbots(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    limit: int = 20,
    offset: int = 0,
) -> list[ChatbotView]:
    chatbots = await chatbot_repo.list_chatbots(limit=limit, offset=offset)
    return [_to_view(c) for c in chatbots]
