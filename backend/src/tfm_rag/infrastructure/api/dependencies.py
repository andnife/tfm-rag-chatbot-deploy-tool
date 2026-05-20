from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tfm_rag.infrastructure.persistence.engine import (
    build_engine,
    build_session_factory,
)
from tfm_rag.infrastructure.persistence.repository import RequestContext
from tfm_rag.infrastructure.settings import Settings, get_settings


_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = build_engine(settings.postgres_url)
        _session_factory = build_session_factory(engine)
    return _session_factory


async def get_session(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[AsyncSession]:
    factory = _get_factory(settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_current_context(request: Request) -> RequestContext:
    ctx: RequestContext | None = getattr(request.state, "ctx", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return ctx
