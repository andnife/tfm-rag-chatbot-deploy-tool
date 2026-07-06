# backend/tests/integration/test_sql_provisioner.py
from uuid import uuid4

import asyncmy
import pytest

from tfm_rag.infrastructure.evaluation.sql_provisioner import (
    provision_seed,
    schema_name_for,
)

pytestmark = pytest.mark.integration

_ADMIN = dict(host="127.0.0.1", port=3306, admin_user="root", admin_password="rootpw")


@pytest.mark.asyncio
async def test_provision_seed_creates_isolated_db_with_data() -> None:
    dsid = uuid4()
    schema = schema_name_for(dsid)
    seed = (
        "CREATE TABLE widgets (id INT PRIMARY KEY, name VARCHAR(50));\n"
        "INSERT INTO widgets VALUES (1, 'alpha'), (2, 'beta');\n"
    )
    try:
        returned = await provision_seed(
            dataset_id=dsid, seed_sql=seed,
            host=_ADMIN["host"], port=_ADMIN["port"],
            admin_user=_ADMIN["admin_user"], admin_password=_ADMIN["admin_password"],
        )
        assert returned == schema
        # Verify the DB + data exist, queried by table's natural name.
        conn = await asyncmy.connect(
            host=_ADMIN["host"], port=_ADMIN["port"],
            user=_ADMIN["admin_user"], password=_ADMIN["admin_password"], db=schema,
        )
        try:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM widgets")
                (count,) = await cur.fetchone()
            assert count == 2
        finally:
            conn.close()
        # Idempotent: re-provision drops + recreates cleanly.
        await provision_seed(
            dataset_id=dsid, seed_sql=seed,
            host=_ADMIN["host"], port=_ADMIN["port"],
            admin_user=_ADMIN["admin_user"], admin_password=_ADMIN["admin_password"],
        )
    finally:
        conn = await asyncmy.connect(
            host=_ADMIN["host"], port=_ADMIN["port"],
            user=_ADMIN["admin_user"], password=_ADMIN["admin_password"],
        )
        try:
            async with conn.cursor() as cur:
                await cur.execute(f"DROP DATABASE IF EXISTS {schema}")
        finally:
            conn.close()
