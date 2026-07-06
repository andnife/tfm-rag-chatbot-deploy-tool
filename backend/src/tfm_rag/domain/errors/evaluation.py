from tfm_rag.domain.errors.common import DomainError


class EvaluationDatasetError(DomainError):
    """Raised when an evaluation dataset cannot be loaded (file missing,
    malformed JSONL, missing required fields, etc.). The CLI surfaces this
    as a non-zero exit + stderr message.
    """


class EvaluationError(DomainError):
    """Raised when the evaluation pipeline fails for a non-dataset reason
    (RAGAS crash, no scored cases, judge LLM unreachable, etc.).
    """


class EvalDatasetError(DomainError):
    """Raised when an eval dataset or one of its rows is invalid (bad field,
    unknown scenario/complexity, missing sql_reference for sql_only, etc.)."""
