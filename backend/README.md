# tfm-rag-backend — CAP-INFRA-PERSISTENCE

Backend de la plataforma RAG del TFM. Esta primera entrega cubre solo la capa de persistencia base (Postgres + Qdrant + Ollama orquestados con docker-compose) y un endpoint `/health` que verifica los tres componentes.

## Arranque

```bash
cd infra
cp .env.example .env
# Generar secretos reales
python -c "import secrets; print(secrets.token_urlsafe(32))"  # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # FERNET_KEY
docker compose up -d
```

Espera a que los tres servicios estén `healthy` (Ollama tarda más por el pull inicial):

```bash
docker compose ps
```

Aplica las migraciones:

```bash
cd ../backend
alembic upgrade head
```

Verifica:

```bash
curl http://localhost:8000/health
```

## Tests

```bash
cd backend
pip install -e ".[dev]"
pytest tests/unit -v
# Integration tests require the stack up:
pytest tests/integration -v -m integration
```

## Próximas CAPs

Esta es la 1ª de 17 plans. Ver `docs/superpowers/plans/` para la lista completa.
