import pytest
from cryptography.fernet import Fernet

from tfm_rag.domain.errors.integrations import SecretDecryptError
from tfm_rag.infrastructure.secrets.fernet_encryptor import FernetSecretEncryptor


def test_encrypt_decrypt_roundtrip() -> None:
    key = Fernet.generate_key()
    enc = FernetSecretEncryptor(key)
    ct = enc.encrypt(b"sk-test-12345")
    assert ct != b"sk-test-12345"
    pt = enc.decrypt(ct)
    assert pt == b"sk-test-12345"


def test_decrypt_with_different_key_raises() -> None:
    enc1 = FernetSecretEncryptor(Fernet.generate_key())
    enc2 = FernetSecretEncryptor(Fernet.generate_key())
    ct = enc1.encrypt(b"secret")
    with pytest.raises(SecretDecryptError):
        enc2.decrypt(ct)


def test_decrypt_garbage_raises() -> None:
    enc = FernetSecretEncryptor(Fernet.generate_key())
    with pytest.raises(SecretDecryptError):
        enc.decrypt(b"not-a-fernet-token")


def test_accepts_key_as_string_or_bytes() -> None:
    key_bytes = Fernet.generate_key()
    key_str = key_bytes.decode("utf-8")
    enc_bytes = FernetSecretEncryptor(key_bytes)
    enc_str = FernetSecretEncryptor(key_str)
    ct = enc_bytes.encrypt(b"hello")
    assert enc_str.decrypt(ct) == b"hello"
