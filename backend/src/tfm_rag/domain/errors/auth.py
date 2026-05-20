from tfm_rag.domain.errors.common import DomainError


class InvalidCredentialsError(DomainError):
    """Raised when login credentials are wrong."""


class UserAlreadyExistsError(DomainError):
    """Raised when registering a user whose email or google_sub already exists."""
