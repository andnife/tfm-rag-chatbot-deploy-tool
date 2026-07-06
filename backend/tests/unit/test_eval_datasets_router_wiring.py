"""Wiring test for /api/admin/eval/datasets — Task 9 review follow-up.

`test_eval_datasets_new_routes.py` calls `upload_sql_seed` / `process`
directly as plain async functions — that exercises none of FastAPI's
`Depends` resolution, so a composition-wiring bug (wrong provider, wrong
repo type, session not threaded through) would slip past it silently.

This test hits `GET /api/admin/eval/datasets/{dataset_id}` through a real
`TestClient` request. Only the leaf `get_session` / `get_settings`
dependencies are overridden (fakes, no database); `get_eval_dataset_repo`
and `get_eval_dataset_item_repo` run for real and must compose the actual
`EvalDatasetRepository` / `EvalDatasetItemRepository` classes wrapping the
fake session — exactly mirroring the technique in
`test_auth_router_wiring.py` and `test_knowledge_bases_search_router.py`.
"""
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.domain.value_objects.eval_dataset import EvalDatasetView
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.dependencies import get_session, get_settings
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.persistence.repositories.eval_datasets_repo import (
    EvalDatasetItemRepository,
    EvalDatasetRepository,
)
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32
FERNET_KEY = "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="
_SENTINEL_SESSION = object()


def _make_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        postgres_url="postgresql+asyncpg://u:p@h:5432/d",
        qdrant_url="http://qdrant:6333",
        ollama_base_url="http://ollama:11434",
        jwt_secret=SECRET,
        fernet_key=FERNET_KEY,
        cookie_secure=False,
    )


def _token(*, is_superadmin: bool) -> str:
    return encode_jwt(
        user_id=uuid4(), tenant_id=uuid4(), secret=SECRET,
        expires_hours=1, is_superadmin=is_superadmin,
    )


def _client() -> TestClient:
    app = create_app()
    settings = _make_settings()

    async def _fake_session():
        yield _SENTINEL_SESSION

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=True)


def test_get_one_requires_superadmin() -> None:
    client = _client()
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=False))

    resp = client.get(f"/api/admin/eval/datasets/{uuid4()}")

    assert resp.status_code == 403


def test_get_one_composes_repos_via_depends_and_shapes_json() -> None:
    dataset_id = uuid4()
    fake_view = EvalDatasetView(
        id=dataset_id,
        tenant_id=uuid4(),
        name="World Countries",
        description="geo facts",
        knowledge_base_id=uuid4(),
        db_schema_name=None,
        sql_seed_artifact=None,
        status="ready",
        status_error=None,
        num_rows=180,
    )
    captured: dict[str, object] = {}

    # Mirrors the REAL keyword-only signature of `get_eval_dataset`: an
    # old-style positional/legacy-kw caller would TypeError against this fake.
    async def _fake_get_eval_dataset(
        *, ds_repo, item_repo, dataset_id
    ) -> EvalDatasetView:
        captured.update(ds_repo=ds_repo, item_repo=item_repo, dataset_id=dataset_id)
        return fake_view

    client = _client()
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.get_eval_dataset",
        new=_fake_get_eval_dataset,
    ):
        resp = client.get(f"/api/admin/eval/datasets/{dataset_id}")

    assert resp.status_code == 200, resp.text
    # Composition: real adapters, built from the request session — proves
    # `Depends(get_eval_dataset_repo)` / `Depends(get_eval_dataset_item_repo)`
    # actually ran, not just a direct function call.
    assert isinstance(captured["ds_repo"], EvalDatasetRepository)
    assert captured["ds_repo"]._session is _SENTINEL_SESSION
    assert isinstance(captured["item_repo"], EvalDatasetItemRepository)
    assert captured["item_repo"]._session is _SENTINEL_SESSION
    assert captured["dataset_id"] == dataset_id
    assert resp.json() == {
        "id": str(dataset_id),
        "name": "World Countries",
        "description": "geo facts",
        "knowledge_base_id": str(fake_view.knowledge_base_id),
        "db_schema_name": None,
        "status": "ready",
        "status_error": None,
        "num_rows": 180,
    }


def test_get_one_returns_404_when_dataset_missing() -> None:
    dataset_id = uuid4()
    client = _client()
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    async def _raise_not_found(*, ds_repo, item_repo, dataset_id):
        raise NotFoundError(f"eval dataset {dataset_id} not found")

    with patch(
        "tfm_rag.infrastructure.api.routers.eval_datasets.get_eval_dataset",
        new=_raise_not_found,
    ):
        resp = client.get(f"/api/admin/eval/datasets/{dataset_id}")

    assert resp.status_code == 404
