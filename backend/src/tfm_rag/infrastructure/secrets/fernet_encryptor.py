from cryptography.fernet import Fernet, InvalidToken

from tfm_rag.domain.errors.integrations import SecretDecryptError
from tfm_rag.domain.ports.secret_encryptor import SecretEncryptor


class FernetSecretEncryptor(SecretEncryptor):
    """AES-128-GCM + HMAC via cryptography.fernet.

    The key is a 32-byte url-safe base64 string (44 chars including `=` padding).
    Generate one with: `cryptography.fernet.Fernet.generate_key()`.
    """

    def __init__(self, key: str | bytes) -> None:
        if isinstance(key, str):
            key = key.encode("utf-8")
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise SecretDecryptError("invalid or corrupted ciphertext") from exc
