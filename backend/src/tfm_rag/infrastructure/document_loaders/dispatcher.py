from collections.abc import Sequence

from tfm_rag.domain.errors.knowledge import UnsupportedSourceTypeError
from tfm_rag.domain.ports.document_loader import DocumentLoader


class LoaderDispatcher:
    """Picks the right loader for an incoming mime_type."""

    def __init__(self, loaders: Sequence[DocumentLoader]) -> None:
        self._by_mime: dict[str, DocumentLoader] = {
            loader.mime_type: loader for loader in loaders
        }

    def for_mime(self, mime_type: str) -> DocumentLoader:
        loader = self._by_mime.get(mime_type)
        if loader is None:
            raise UnsupportedSourceTypeError(
                f"No loader registered for mime_type {mime_type!r}. "
                f"Supported: {sorted(self._by_mime)}"
            )
        return loader
