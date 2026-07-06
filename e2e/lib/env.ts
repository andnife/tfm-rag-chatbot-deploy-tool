// Centralised env + constants for the e2e suite.

// The nginx mirror (routes /api+/widget straight to the backend with 600s
// timeouts). Chat only works through here, not bare next-dev (30s cap).
export const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:8080'

// The backend, hit directly by the api-client for fixture setup/teardown and
// for error paths the UI can't easily provoke.
export const BACKEND_URL = process.env.E2E_BACKEND_URL ?? 'http://localhost:8000'

// Dedicated e2e identity, created in global-setup. Kept separate from the
// debug@/admin@ seeds so the suite never depends on or corrupts them.
export const E2E_EMAIL = process.env.E2E_EMAIL ?? 'e2e@test.com'
export const E2E_PASSWORD = process.env.E2E_PASSWORD ?? 'E2eTest1234!'

// Saved logged-in cookie state, reused by authed specs (see playwright.config).
export const STORAGE_STATE = 'e2e/.auth/e2e.json'

// nginx mirror container.
export const MIRROR_CONTAINER = 'e2e-nginx'
export const MIRROR_PORT = 8080

// The app's own Postgres (infra/docker-compose.yml `postgres` service),
// reachable from the host at localhost:5432. Used by lib/db.ts for the rare
// setup step the HTTP API can't do: granting `is_superadmin` (eval routes)
// and seeding a separate "source" database for the sql-route spec — mirrors
// backend/tests/integration/*'s own `UPDATE users SET is_superadmin ...` /
// `_prepare_source_db()` helpers.
export const PG_HOST = process.env.E2E_PG_HOST ?? 'localhost'
export const PG_PORT = Number(process.env.E2E_PG_PORT ?? 5432)
export const PG_USER = process.env.E2E_PG_USER ?? 'tfm'
export const PG_PASSWORD = process.env.E2E_PG_PASSWORD ?? 'tfm'
export const PG_APP_DATABASE = process.env.E2E_PG_DATABASE ?? 'tfm_rag'
// A second database on the same Postgres instance, dedicated to DatabaseSource
// fixtures (kept separate from the app's own `tfm_rag`) — same one the
// backend's db-source integration tests use.
export const PG_SOURCE_DATABASE = process.env.E2E_PG_SOURCE_DB ?? 'tfm_rag_source_test'
