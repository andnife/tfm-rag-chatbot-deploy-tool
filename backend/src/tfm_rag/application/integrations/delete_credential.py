from uuid import UUID

from tfm_rag.domain.ports.repositories import ProviderCredentialRepositoryPort


async def delete_credential(
    *,
    credentials_repo: ProviderCredentialRepositoryPort,
    credential_id: UUID,
) -> None:
    await credentials_repo.delete_credential(credential_id)
