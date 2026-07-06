#!/usr/bin/env bash
# Container entrypoint: apply pending alembic migrations, then start the app.
#
# Runs `alembic upgrade head` before uvicorn so a from-scratch deploy (empty
# Postgres database) boots against a fully migrated schema. Controlled by
# RUN_MIGRATIONS (default "1"); set RUN_MIGRATIONS=0 to skip (e.g. if
# migrations are applied out-of-band, or to run a one-off command instead).
#
# Any arguments passed to the container override the default uvicorn command,
# e.g.:
#   docker run ... tfm-backend alembic upgrade head
#   docker run ... tfm-backend bash

set -euo pipefail

if [[ "${RUN_MIGRATIONS:-1}" == "1" ]]; then
  echo "[entrypoint] RUN_MIGRATIONS=1 — applying alembic migrations..."
  alembic upgrade head
else
  echo "[entrypoint] RUN_MIGRATIONS=0 — skipping alembic migrations."
fi

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

exec uvicorn tfm_rag.infrastructure.api.app:app --host 0.0.0.0 --port 8000
