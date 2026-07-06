# ---- builder: compiles wheels for deps that need a C toolchain (e.g. asyncpg) ----
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ---- runtime: slim image, no compiler toolchain, non-root user ----
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /data/storage \
    && chown -R appuser:appuser /app /data

ENV PATH="/opt/venv/bin:$PATH"

USER appuser

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
