from tfm_rag.domain.errors.common import DomainError, NotFoundError


class KnowledgeBaseNotFoundError(NotFoundError):
    """Raised when a KB does not exist in the tenant."""


class KnowledgeBaseInUseError(DomainError):
    """Raised when a KB cannot be deleted because a chatbot references it.

    Defined in plan #7 so the error class is stable. The actual check fires
    in plan #10 once chatbots + chatbot_knowledge_base exist.
    """


class IncompatibleEmbeddingsError(DomainError):
    """Raised when KBs attached to the same chatbot disagree on embedding.

    Defined here so plan #10 can raise it. Plan #7 doesn't trigger it.
    """


class SourceNotFoundError(NotFoundError):
    """Raised when a Source does not exist in the KB."""


class UnsupportedSourceTypeError(DomainError):
    """Raised when a tester / handler is requested for an unknown SourceType."""


class IngestionFailedError(DomainError):
    """Raised when the ingestion pipeline fails for a single source."""


class IngestionJobNotFoundError(NotFoundError):
    """Raised when an IngestionJob row does not exist in the tenant."""


class DatabaseConnectionError(DomainError):
    """Raised when a connection to a DatabaseSource fails (bad host/port,
    auth failure, network timeout, SSL failure, etc.).

    The error message is safe to surface to the user (no secrets).
    """


class SchemaIntrospectionError(DomainError):
    """Raised when introspecting the schema of a DatabaseSource fails
    after a successful connection (e.g. missing permissions on
    information_schema, unexpected dialect quirk).
    """


class UnsupportedDatabaseDialectError(DomainError):
    """Raised when a DatabaseSourceSpec specifies a driver value we don't
    support (anything other than 'postgres' or 'mysql' in MVP).
    """
