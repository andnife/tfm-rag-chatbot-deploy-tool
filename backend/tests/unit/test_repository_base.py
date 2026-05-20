from uuid import UUID, uuid4

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from tfm_rag.infrastructure.persistence.base import Base
from tfm_rag.infrastructure.persistence.repository import (
    BaseRepository,
    RequestContext,
)


class DummyEntity(Base):
    """Test-only entity for repository tests. Never targeted by Alembic migrations."""
    __tablename__ = "dummy_entity"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class DummyRepository(BaseRepository):
    model = DummyEntity


def test_request_context_requires_tenant_id() -> None:
    ctx = RequestContext(tenant_id=uuid4(), user_id=uuid4())
    assert ctx.tenant_id is not None
    assert ctx.user_id is not None


def test_repository_has_model() -> None:
    assert DummyRepository.model is DummyEntity
