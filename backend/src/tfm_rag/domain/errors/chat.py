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


class LLMError(DomainError):
    """Raised when an LLM provider fails (HTTP error, malformed response,
    parsing error). The agent loop translates this into a 502 at the API
    layer.
    """


class LLMTimeoutError(LLMError):
    """Specialisation of LLMError for explicit timeouts (httpx.TimeoutException).
    Worth a dedicated type so observability dashboards can split them.
    """


class MaxIterationsExceededError(DomainError):
    """Raised when the agent loop hits `max_retrieval_iterations` without
    a terminal decision. The use case actually CATCHES this and synthesises
    an abstain — but it's defined here so tests can pin the behaviour.
    """


class UnsafeSQLError(DomainError):
    """Raised when the LLM emits SQL that the safety checker rejects
    (non-SELECT statement, multi-statement, banned keyword)."""


class QueryExecutionError(DomainError):
    """Raised when the database returns an error executing the SELECT
    (syntax, missing table, permission denied, server crash).

    Connection-level failures (auth, network) keep raising
    DatabaseConnectionError from domain.errors.knowledge instead.
    """


class DatabaseSourceMismatchError(DomainError):
    """Raised when the agent emits a query_database call with a
    source_id that does not exist in the chatbot's attached KBs, or
    points to a non-database Source."""
