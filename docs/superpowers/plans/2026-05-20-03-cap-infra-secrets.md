# CAP-INFRA-SECRETS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a `SecretEncryptor` port (domain) + a `FernetSecretEncryptor` adapter (infrastructure) so that all secrets (provider API keys, SQL connection strings) can be persisted encrypted in Postgres and decrypted only at the point of use.

**Architecture:** Hexagonal. Domain defines the abstract port; infrastructure provides the Fernet (AES-128-GCM + HMAC) adapter. The Fernet key is read once from `Settings.fernet_key` at startup. A `SecretDecryptError` domain error is raised if decryption fails (corrupted ciphertext or rotated key).

**Tech Stack:** `cryptography` (Fernet). Already in `pyproject.toml` via transitive dependency of `python-jose[cryptography]`.

**Depends on:** Plan #1 (Settings).

---

## File structure for this plan

**Created:**

```
backend/src/tfm_rag/
├── domain/
│   ├── ports/
│   │   ├── __init__.py
│   │   └── secret_encryptor.py    # abstract base class
│   └── errors/
│       └── integrations.py        # add SecretDecryptError
├── infrastructure/
│   └── secrets/
│       ├── __init__.py
│       └── fernet_encryptor.py    # concrete adapter

backend/tests/unit/
└── test_fernet_encryptor.py
```

---

## Task 1 — Port + error

### Step 1.1: Create `backend/src/tfm_rag/domain/ports/__init__.py` (empty)

### Step 1.2: Create `backend/src/tfm_rag/domain/ports/secret_encryptor.py`

```python
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
```

### Step 1.3: Create `backend/src/tfm_rag/domain/errors/integrations.py`

```python
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
```

### Step 1.4: Commit

```bash
git add backend/src/tfm_rag/domain/ports/ \
        backend/src/tfm_rag/domain/errors/integrations.py
git commit -m "feat(domain): SecretEncryptor port + integrations errors"
```

---

## Task 2 — Fernet adapter + tests

### Step 2.1: Create `backend/src/tfm_rag/infrastructure/secrets/__init__.py` (empty)

### Step 2.2: Create `backend/src/tfm_rag/infrastructure/secrets/fernet_encryptor.py`

```python
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
```

### Step 2.3: Create `backend/tests/unit/test_fernet_encryptor.py`

```python
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
```

### Step 2.4: Commit

```bash
git add backend/src/tfm_rag/infrastructure/secrets/ \
        backend/tests/unit/test_fernet_encryptor.py
git commit -m "feat(infra): FernetSecretEncryptor + tests"
```

---

## Task 3 — Tag

```bash
git tag cap-03-infra-secrets
```

---

## Done criteria

- `SecretEncryptor` abstract port exists in `domain/ports/`.
- `FernetSecretEncryptor` adapter encrypts/decrypts bytes round-trip with the configured key.
- Decryption with a wrong/rotated key raises `SecretDecryptError`.
- Tests pass (4 unit tests).

## What plan #4 will build on top

Plan #4 (`CAP-INFRA-ASYNC-JOBS`) adds the `ingestion_jobs` table + a generic `JobsRunner` based on `FastAPI BackgroundTasks`. Both later plans (`CAP-INTEG-CREDENTIALS` plan #6 and `CAP-KB-DB-SOURCES` plan #9) consume `FernetSecretEncryptor` for cifrar api_keys y connection_strings.
