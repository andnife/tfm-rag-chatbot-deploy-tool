import asyncio
from pathlib import Path
from uuid import UUID

_MAX_FILENAME_LEN = 255


class LocalStorage:
    """Filesystem-backed Storage adapter.

    URI scheme: `file://<absolute-path>`. Files live under
    `<root>/tenant_<tenant_id>/<source_id>/<filename>`.
    Filenames are not sanitised beyond rejecting path separators — the
    upstream HTTP layer already validates them.
    """

    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(
        self, *, tenant_id: UUID, source_id: UUID, filename: str
    ) -> Path:
        if "/" in filename or "\\" in filename or filename in {".", ".."}:
            raise ValueError(f"Invalid filename: {filename!r}")
        if "\x00" in filename:
            raise ValueError("Filename contains null byte")
        if len(filename) > _MAX_FILENAME_LEN:
            raise ValueError(f"Filename too long: {len(filename)} > {_MAX_FILENAME_LEN}")
        return (
            self._root
            / f"tenant_{tenant_id}"
            / str(source_id)
            / filename
        )

    def _assert_within_root(self, path: Path) -> None:
        """Raise if path escapes the storage root (path traversal guard)."""
        resolved = path.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(
                f"Storage path escapes root: {resolved} is outside {self._root}"
            ) from None

    async def save(
        self,
        *,
        tenant_id: UUID,
        source_id: UUID,
        filename: str,
        content: bytes,
    ) -> str:
        path = self._path_for(
            tenant_id=tenant_id, source_id=source_id, filename=filename
        )

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

        await asyncio.to_thread(_write)
        return f"file://{path}"

    async def load(self, storage_uri: str) -> bytes:
        path = Path(storage_uri.removeprefix("file://"))
        self._assert_within_root(path)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, storage_uri: str) -> None:
        path = Path(storage_uri.removeprefix("file://"))
        self._assert_within_root(path)

        def _delete() -> None:
            if not path.exists():
                return
            path.unlink()
            # Best-effort prune empty parents:
            for parent in (path.parent, path.parent.parent):
                try:
                    parent.rmdir()
                except OSError:
                    break

        await asyncio.to_thread(_delete)
