from uuid import UUID

from tfm_rag.domain.ports.repositories import ChatSessionRepositoryPort


async def touch_session(
    *,
    session_repo: ChatSessionRepositoryPort,
    session_id: UUID,
) -> None:
    """Internal helper. Bumps `last_activity_at`. No-op if the session
    doesn't belong to the tenant (defense in depth — the agent loop should
    never call touch on a foreign session, but if it did we silently
    drop the update at the SQL layer via the tenant_id filter).
    """
    await session_repo.touch(session_id)
