from tfm_rag.domain.errors.common import DomainError, NotFoundError


class UnsupportedProviderError(DomainError):
    """Raised when retrieve_docs is asked to embed with a provider whose
    Embedder adapter hasn't been wired yet. Plan #12 only supports Ollama.
    """


class RetrievalError(DomainError):
    """Raised when the retrieval pipeline (embed + vector search) fails for
    a reason that isn't tenant-scope, not-found, or validation.
    """


class SessionNotFoundError(NotFoundError):
    """Raised when a ChatSession is not found in the tenant."""
