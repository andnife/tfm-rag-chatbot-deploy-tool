from typing import Protocol


class PasswordHasher(Protocol):
    """Hashes/verifies user passwords for the auth flows.

    Keeps the concrete algorithm (bcrypt, in
    `infrastructure/auth/password.py`) out of `application/auth`.
    """

    def hash(self, password: str) -> str:
        """Return a one-way hash of `password` suitable for storage."""
        ...

    def verify(self, password: str, password_hash: str) -> bool:
        """Return True iff `password` matches `password_hash`.

        Must return False (not raise) on malformed hashes.
        """
        ...
