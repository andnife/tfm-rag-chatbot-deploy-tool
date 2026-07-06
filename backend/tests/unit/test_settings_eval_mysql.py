import os
from unittest import mock

from tfm_rag.infrastructure.settings import Settings


def _min_env(**extra: str) -> dict[str, str]:
    base = {
        "POSTGRES_URL": "postgresql+asyncpg://u:p@localhost/db",
        "QDRANT_URL": "http://localhost:6333",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "JWT_SECRET": "x" * 32,
        "FERNET_KEY": "qjd374RRcCpzdVhmmLHCnjxvBfrFwbwErhxIj4nq_XM=",
    }
    base.update(extra)
    return base


def test_eval_mysql_defaults_point_at_local_container() -> None:
    with mock.patch.dict(os.environ, _min_env(), clear=True):
        s = Settings()
    assert s.eval_mysql_host == "localhost"
    assert s.eval_mysql_port == 3306
    assert s.eval_mysql_admin_user == "root"
    assert s.eval_mysql_admin_password == "rootpw"


def test_eval_mysql_overridable_by_env() -> None:
    with mock.patch.dict(
        os.environ,
        _min_env(EVAL_MYSQL_HOST="db.internal", EVAL_MYSQL_PORT="3307"),
        clear=True,
    ):
        s = Settings()
    assert s.eval_mysql_host == "db.internal"
    assert s.eval_mysql_port == 3307
