from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def build_engine(
    postgres_url: str,
    *,
    echo: bool = False,
    pool_size: int = 10,
    max_overflow: int = 20,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine. Use one per process.

    ``pool_size`` + ``max_overflow`` bound the total concurrent connections.
    The eval runner sizes its generation concurrency off this total, so keep
    them aligned with the Postgres server's ``max_connections``.
    """
    return create_async_engine(
        postgres_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


def build_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Context manager that commits on success, rolls back on exception."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
            raise
