from tfm_rag.domain.errors.common import DomainError, NotFoundError


class ChatbotNotFoundError(NotFoundError):
    """Raised when a Chatbot does not exist in the tenant."""


class ChatbotAlreadyExistsError(DomainError):
    """Raised when a tenant already has a Chatbot with the requested name."""
