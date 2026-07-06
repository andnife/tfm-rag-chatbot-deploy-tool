import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash (cost 12) of `plain`."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff `plain` matches the bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


class BcryptPasswordHasher:
    """Implements the domain `PasswordHasher` port over the bcrypt helpers."""

    def hash(self, password: str) -> str:
        return hash_password(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return verify_password(password, password_hash)
