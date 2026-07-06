from typing import Protocol


class DocumentLoader(Protocol):
    """Extracts plain text from a single document of one mime type."""

    mime_type: str

    async def load(self, content: bytes) -> str: ...


class LoaderDispatcherPort(Protocol):
    """Picks the right `DocumentLoader` for an incoming mime type.

    The concrete `infrastructure.document_loaders.dispatcher.LoaderDispatcher`
    satisfies this structurally; application code depends on the port so it
    never imports the infrastructure dispatcher.
    """

    def for_mime(self, mime_type: str) -> DocumentLoader: ...
