from abc import ABC, abstractmethod


class SecretEncryptor(ABC):
    """Port for symmetric encryption of secrets at rest.

    Adapters MUST be deterministic enough to survive process restarts
    (the same plaintext + same key produces decryptable ciphertext).
    Adapters MAY use authenticated encryption (recommended).
    """

    @abstractmethod
    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt and return ciphertext bytes."""

    @abstractmethod
    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt and return plaintext bytes. Raises SecretDecryptError on failure."""
