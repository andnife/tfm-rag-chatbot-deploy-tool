"""Wiring tests for /api/admin/eval/runs — Task 9 review follow-up.

Task 9 moved the eval-run repositories behind the composition root
(`get_eval_run_repo` / `get_chatbot_repo` / `get_eval_dataset_repo` in
`infrastructure/api/composition.py`), but the only existing coverage for
`eval_runs.py` (`test_eval_datasets_new_routes.py`, for the sibling router)
calls handlers directly as plain functions — that bypasses FastAPI's
`Depends` resolution entirely, so it can't catch a composition wiring bug.

These tests hit the real router through `TestClient` (httpx-based) with
`app.dependency_overrides` on the composition providers, faking the repos —
no database. They cover all five `eval_runs.py` endpoints, including the
path through the resignatured `_resolve_run_views` helper.
"""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from tfm_rag.domain.errors.common import NotFoundError
from tfm_rag.infrastructure.api.app import create_app
from tfm_rag.infrastructure.api.auth_cookie import COOKIE_NAME
from tfm_rag.infrastructure.api.composition import (
    get_chatbot_repo,
    get_eval_dataset_repo,
    get_eval_run_repo,
)
from tfm_rag.infrastructure.api.dependencies import get_session, get_settings
from tfm_rag.infrastructure.api.routers import eval_runs
from tfm_rag.infrastructure.auth.jwt import encode_jwt
from tfm_rag.infrastructure.persistence.models.eval_runs import EvalRunRow
from tfm_rag.infrastructure.settings import Settings

SECRET = "x" * 32
FERNET_KEY = "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM="


@pytest.fixture(autouse=True)
def _reset_cancel_registry() -> None:
    eval_runs._CANCEL_REQUESTED.clear()
    yield
    eval_runs._CANCEL_REQUESTED.clear()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEvalRunRepo:
    def __init__(
        self,
        *,
        rows: list[EvalRunRow] | None = None,
        row: EvalRunRow | None = None,
        get_error: Exception | None = None,
    ) -> None:
        self._rows = rows or []
        self._row = row
        self._get_error = get_error
        self.list_recent_calls: list[int] = []
        self.get_calls: list[object] = []

    async def list_recent(self, *, limit: int) -> list[EvalRunRow]:
        self.list_recent_calls.append(limit)
        return self._rows

    async def get(self, run_id: object) -> EvalRunRow:
        self.get_calls.append(run_id)
        if self._get_error is not None:
            raise self._get_error
        assert self._row is not None
        return self._row


class _FakeNameRepo:
    """Fake for the `ChatbotRepository` / `EvalDatasetRepository` seams that
    `_resolve_run_views` uses to resolve display names."""

    def __init__(self, names: dict, missing: frozenset = frozenset()) -> None:
        self._names = names
        self._missing = missing
        self.get_calls: list[object] = []

    async def get(self, entity_id: object) -> SimpleNamespace:
        self.get_calls.append(entity_id)
        if entity_id in self._missing:
            raise NotFoundError(f"{entity_id} not found")
        # `llm_selection` is a raw JSONB dict on the real row, mirrored here so
        # cb-repo callers that read `generator_model` don't blow up (ds-repo
        # never reads it).
        return SimpleNamespace(
            name=self._names[entity_id],
            llm_selection={"model_id": None},
        )


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


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


def _client(
    *,
    fake_session: object | None = None,
    run_repo: object | None = None,
    cb_repo: object | None = None,
    ds_repo: object | None = None,
) -> TestClient:
    app = create_app()
    settings = _make_settings()

    async def _fake_session_dep():
        yield fake_session if fake_session is not None else object()

    app.dependency_overrides[get_session] = _fake_session_dep
    app.dependency_overrides[get_settings] = lambda: settings
    if run_repo is not None:
        app.dependency_overrides[get_eval_run_repo] = lambda: run_repo
    if cb_repo is not None:
        app.dependency_overrides[get_chatbot_repo] = lambda: cb_repo
    if ds_repo is not None:
        app.dependency_overrides[get_eval_dataset_repo] = lambda: ds_repo
    return TestClient(app, raise_server_exceptions=True)


def _run_row(**overrides: object) -> EvalRunRow:
    defaults: dict[str, object] = dict(
        id=uuid4(), tenant_id=uuid4(), chatbot_id=uuid4(),
        judge_model="gemma3:1b", status="queued", progress=0,
    )
    defaults.update(overrides)
    return EvalRunRow(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------


def test_list_runs_requires_superadmin() -> None:
    client = _client(run_repo=_FakeEvalRunRepo())
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=False))

    resp = client.get("/api/admin/eval/runs")

    assert resp.status_code == 403


def test_list_runs_without_auth_returns_401() -> None:
    client = _client(run_repo=_FakeEvalRunRepo())
    resp = client.get("/api/admin/eval/runs")
    assert resp.status_code == 401


def test_list_runs_resolves_chatbot_and_dataset_names_via_composed_repos() -> None:
    """Proves the composed repos (from `Depends`) flow into `_resolve_run_views`
    and its cb/ds name resolution + caching."""
    cb_id, ds_id = uuid4(), uuid4()
    missing_cb_id = uuid4()
    row_with_dataset = _run_row(chatbot_id=cb_id, dataset_id=ds_id)
    row_without_dataset = _run_row(chatbot_id=cb_id, dataset_id=None)
    row_missing_chatbot = _run_row(chatbot_id=missing_cb_id, dataset_id=None)

    cb_repo = _FakeNameRepo({cb_id: "Acme Bot"}, missing={missing_cb_id})
    ds_repo = _FakeNameRepo({ds_id: "World Countries"})
    run_repo = _FakeEvalRunRepo(
        rows=[row_with_dataset, row_without_dataset, row_missing_chatbot]
    )

    client = _client(run_repo=run_repo, cb_repo=cb_repo, ds_repo=ds_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get("/api/admin/eval/runs")

    assert resp.status_code == 200, resp.text
    assert run_repo.list_recent_calls == [50]
    body = resp.json()
    assert body[0]["chatbot_name"] == "Acme Bot"
    assert body[0]["dataset_name"] == "World Countries"
    assert body[1]["chatbot_name"] == "Acme Bot"
    assert body[1]["dataset_name"] is None
    assert body[2]["chatbot_name"] is None
    # cb_repo.get was cached: called once per distinct id, not once per row.
    assert cb_repo.get_calls == [cb_id, missing_cb_id]
    assert ds_repo.get_calls == [ds_id]


class _FakeChatbotRepo:
    """Fake `ChatbotRepository` that returns a chatbot exposing both `name`
    and `llm_selection.model_id` from a single `get`, mirroring the real
    entity `_resolve_run_views` reads for `generator_model`."""

    def __init__(self, chatbots: dict) -> None:
        self._chatbots = chatbots
        self.get_calls: list[object] = []

    async def get(self, entity_id: object) -> SimpleNamespace:
        self.get_calls.append(entity_id)
        if entity_id not in self._chatbots:
            raise NotFoundError(f"{entity_id} not found")
        name, model_id = self._chatbots[entity_id]
        return SimpleNamespace(
            name=name,
            llm_selection={"model_id": model_id},
        )


def test_list_runs_resolves_generator_model_from_same_chatbot_fetch() -> None:
    cb_id = uuid4()
    row = _run_row(chatbot_id=cb_id, dataset_id=None)
    cb_repo = _FakeChatbotRepo({cb_id: ("Acme Bot", "llama-3.3-70b")})
    ds_repo = _FakeNameRepo({})
    run_repo = _FakeEvalRunRepo(rows=[row])

    client = _client(run_repo=run_repo, cb_repo=cb_repo, ds_repo=ds_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get("/api/admin/eval/runs")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["chatbot_name"] == "Acme Bot"
    assert body[0]["generator_model"] == "llama-3.3-70b"
    # No second repo call: name + generator_model come from one fetch.
    assert cb_repo.get_calls == [cb_id]


def test_list_runs_generator_model_none_when_chatbot_missing() -> None:
    cb_id = uuid4()
    row = _run_row(chatbot_id=cb_id, dataset_id=None)
    cb_repo = _FakeChatbotRepo({})  # cb_id not present → NotFoundError
    ds_repo = _FakeNameRepo({})
    run_repo = _FakeEvalRunRepo(rows=[row])

    client = _client(run_repo=run_repo, cb_repo=cb_repo, ds_repo=ds_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get("/api/admin/eval/runs")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body[0]["chatbot_name"] is None
    assert body[0]["generator_model"] is None


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------


def test_get_run_returns_200_with_resolved_names() -> None:
    cb_id = uuid4()
    row = _run_row(chatbot_id=cb_id)
    run_repo = _FakeEvalRunRepo(row=row)
    cb_repo = _FakeNameRepo({cb_id: "Acme Bot"})
    ds_repo = _FakeNameRepo({})

    client = _client(run_repo=run_repo, cb_repo=cb_repo, ds_repo=ds_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get(f"/api/admin/eval/runs/{row.id}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["chatbot_name"] == "Acme Bot"
    assert run_repo.get_calls == [row.id]


def test_get_run_returns_404_when_missing() -> None:
    run_id = uuid4()
    run_repo = _FakeEvalRunRepo(get_error=NotFoundError("no such run"))
    client = _client(run_repo=run_repo, cb_repo=_FakeNameRepo({}), ds_repo=_FakeNameRepo({}))
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get(f"/api/admin/eval/runs/{run_id}")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/trace
# ---------------------------------------------------------------------------


def test_get_run_trace_returns_404_when_run_missing() -> None:
    run_id = uuid4()
    run_repo = _FakeEvalRunRepo(get_error=NotFoundError("no such run"))
    client = _client(run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get(f"/api/admin/eval/runs/{run_id}/trace")

    assert resp.status_code == 404


def test_get_run_trace_returns_empty_list_when_no_trace_file_yet() -> None:
    row = _run_row()
    run_repo = _FakeEvalRunRepo(row=row)
    client = _client(run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get(f"/api/admin/eval/runs/{row.id}/trace")

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /runs/{run_id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_run_returns_404_when_missing() -> None:
    run_id = uuid4()
    run_repo = _FakeEvalRunRepo(get_error=NotFoundError("no such run"))
    client = _client(run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.post(f"/api/admin/eval/runs/{run_id}/cancel")

    assert resp.status_code == 404


def test_cancel_run_returns_409_when_not_cancellable() -> None:
    row = _run_row(status="done")
    run_repo = _FakeEvalRunRepo(row=row)
    client = _client(run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.post(f"/api/admin/eval/runs/{row.id}/cancel")

    assert resp.status_code == 409


def test_cancel_run_success_registers_cancel_and_commits() -> None:
    row = _run_row(status="running")
    run_repo = _FakeEvalRunRepo(row=row)
    session = _FakeSession()
    client = _client(fake_session=session, run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.post(f"/api/admin/eval/runs/{row.id}/cancel")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "cancelled"}
    assert row.status == "cancelled"
    assert row.finished_at is not None
    assert session.committed is True
    assert eval_runs.consume_cancel(str(row.id)) is True


# ---------------------------------------------------------------------------
# GET /runs/{run_id}/live
# ---------------------------------------------------------------------------


def test_get_run_live_returns_404_when_missing() -> None:
    run_id = uuid4()
    run_repo = _FakeEvalRunRepo(get_error=NotFoundError("no such run"))
    client = _client(run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get(f"/api/admin/eval/runs/{run_id}/live")

    assert resp.status_code == 404


def test_get_run_live_returns_empty_dict_when_no_live_file_yet() -> None:
    row = _run_row()
    run_repo = _FakeEvalRunRepo(row=row)
    client = _client(run_repo=run_repo)
    client.cookies.set(COOKIE_NAME, _token(is_superadmin=True))

    resp = client.get(f"/api/admin/eval/runs/{row.id}/live")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {}
