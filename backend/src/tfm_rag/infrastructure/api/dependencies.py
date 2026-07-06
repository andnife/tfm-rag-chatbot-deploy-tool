import threading
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
_factory_lock = threading.Lock()


def get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Return the singleton session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        with _factory_lock:
            if _session_factory is None:
                engine = build_engine(
                    settings.postgres_url,
                    pool_size=settings.db_pool_size,
                    max_overflow=settings.db_max_overflow,
                )
                _session_factory = build_session_factory(engine)
    return _session_factory


async def get_session(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory(settings)
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


def require_superadmin(
    ctx: RequestContext = Depends(get_current_context),  # noqa: B008
) -> RequestContext:
    """Allow only application superadmins. Raises 403 otherwise.

    The security boundary for the cross-tenant admin surface (Inspect, Eval,
    /api/admin/overview): hiding nav items in the frontend is UX only.
    """
    if not ctx.is_superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superadmin only",
        )
    return ctx
