from uuid import UUID

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base


class ChatbotKnowledgeBaseRow(Base):
    """N:M link between chatbots and knowledge_bases.

    FK on kb_id is `ON DELETE RESTRICT` — this is what makes plan #7's
    `DeleteKnowledgeBase` raise `KnowledgeBaseInUseError` once chatbots
    reference a KB. FK on chatbot_id is `ON DELETE CASCADE`.
    """

    __tablename__ = "chatbot_knowledge_base"

    chatbot_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    kb_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
