from tfm_rag.domain.errors.common import DomainError


class CredentialNotFoundError(DomainError):
    """Raised when a ProviderCredential is not found in the tenant."""


class CredentialTestFailedError(DomainError):
    """Raised when TestCredential fails to reach the provider."""


class SecretDecryptError(DomainError):
    """Raised when the encryptor cannot decrypt a stored secret.

    Common causes: corrupted ciphertext, the Fernet master key was rotated
    without re-encrypting existing secrets.
    """
