from pathlib import Path
from uuid import uuid4

import pytest

from tfm_rag.infrastructure.storage.local import LocalStorage


@pytest.mark.asyncio
async def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    tenant_id = uuid4()
    source_id = uuid4()
    uri = await storage.save(
        tenant_id=tenant_id,
        source_id=source_id,
        filename="hello.txt",
        content=b"hello world",
    )
    assert uri.startswith("file://")
    loaded = await storage.load(uri)
    assert loaded == b"hello world"


@pytest.mark.asyncio
async def test_save_isolates_by_tenant_and_source(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    u1 = await storage.save(
        tenant_id=t1, source_id=s1, filename="a.txt", content=b"one"
    )
    u2 = await storage.save(
        tenant_id=t2, source_id=s1, filename="a.txt", content=b"two"
    )
    assert u1 != u2
    assert await storage.load(u1) == b"one"
    assert await storage.load(u2) == b"two"


@pytest.mark.asyncio
async def test_delete_removes_file(tmp_path: Path) -> None:
    storage = LocalStorage(root=str(tmp_path))
    uri = await storage.save(
        tenant_id=uuid4(),
        source_id=uuid4(),
        filename="x.txt",
        content=b"x",
    )
    await storage.delete(uri)
    with pytest.raises(FileNotFoundError):
        await storage.load(uri)
