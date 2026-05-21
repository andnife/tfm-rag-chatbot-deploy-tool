from typing import Protocol

from tfm_rag.domain.value_objects.retrieved_chunk import RetrievedChunk


class Reranker(Protocol):
    """Reorders / trims a list of candidates by relevance to `query`.

    Plan #12 ships the port only. Adapters (`BGECrossEncoderReranker`,
    `CohereRerankerAdapter`) land in a later plan. If `enable_reranker=true`
    is requested but no Reranker is wired, `retrieve_docs` degrades to
    a no-op rerank and emits a warning.
    """

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]: ...
