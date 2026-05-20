class DomainError(Exception):
    """Base class for all domain-level errors."""


class NotFoundError(DomainError):
    """Raised when a resource is not found."""


class ValidationError(DomainError):
    """Raised when input validation fails at the domain level."""


class TenantScopeViolation(DomainError):
    """Raised when a use case tries to access data from a different tenant.

    This should NEVER happen in correctly-written code; if it triggers,
    something at the application layer is bypassing the repository pattern.
    """
