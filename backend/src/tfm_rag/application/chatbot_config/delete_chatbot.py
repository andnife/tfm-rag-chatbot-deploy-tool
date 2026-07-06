from uuid import UUID

from tfm_rag.domain.ports.repositories import ChatbotRepositoryPort


async def delete_chatbot(
    *,
    chatbot_repo: ChatbotRepositoryPort,
    chatbot_id: UUID,
) -> None:
    await chatbot_repo.delete_chatbot(chatbot_id)
