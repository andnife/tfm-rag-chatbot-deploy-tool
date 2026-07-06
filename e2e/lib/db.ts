// Direct Postgres access for the handful of fixture-setup steps the HTTP API
// cannot do: granting the app-level `is_superadmin` flag (eval routes gate on
// it — see dependencies.py `require_superadmin`) and seeding a separate
// "source" database for the sql-route spec (an attachable DatabaseSource).
//
// Mirrors what backend/tests/integration/* already do for the same needs:
//   - `UPDATE users SET is_superadmin = true WHERE email = ...`
//     (test_eval_dataset_runs.py and siblings)
//   - `_prepare_source_db()` creating `tfm_rag_source_test` + tables
//     (test_chat_sql_flow.py, test_db_source_flow.py)
//
// Connects to the same Postgres the backend uses (infra/docker-compose.yml
// `postgres` service, exposed at localhost:5432 — see lib/env.ts).
import { Client } from 'pg'
import { PG_APP_DATABASE, PG_HOST, PG_PASSWORD, PG_PORT, PG_SOURCE_DATABASE, PG_USER } from './env'

const APP_CONN = { host: PG_HOST, port: PG_PORT, user: PG_USER, password: PG_PASSWORD, database: PG_APP_DATABASE }
const SOURCE_CONN = { ...APP_CONN, database: PG_SOURCE_DATABASE }

/** Grants `is_superadmin` to the given user (idempotent). The caller must
 * re-login afterwards — the JWT carries the `sa` claim from login time, so an
 * already-issued token won't reflect the change. */
export async function grantSuperadmin(email: string): Promise<void> {
  const client = new Client(APP_CONN)
  await client.connect()
  try {
    await client.query('UPDATE users SET is_superadmin = true WHERE email = $1', [email])
  } finally {
    await client.end()
  }
}

async function ensureSourceDatabaseExists(): Promise<void> {
  const admin = new Client(APP_CONN)
  await admin.connect()
  try {
    const { rowCount } = await admin.query('SELECT 1 FROM pg_database WHERE datname = $1', [PG_SOURCE_DATABASE])
    if (rowCount === 0) {
      // Database names can't be parameterised — PG_SOURCE_DATABASE is a
      // fixed, non-user-controlled constant (env.ts), not request input.
      await admin.query(`CREATE DATABASE "${PG_SOURCE_DATABASE}"`)
    }
  } finally {
    await admin.end()
  }
}

const TABLE = 'e2e_products'

export interface SqlSourceFixture {
  /** Body for ApiClient.testDbConnection's `spec` / attachDatabase. */
  spec: {
    driver: 'postgres'
    host: string
    port: number
    db_name: string
    username: string
    password: string
    ssl_mode: 'disable'
  }
  rowCount: number
  dispose: () => Promise<void>
}

/** Seeds a small, distinctive table in the shared source DB and returns the
 * connection spec to attach via `api.attachDatabase`/`api.testDbConnection`. */
export async function seedSqlSource(): Promise<SqlSourceFixture> {
  await ensureSourceDatabaseExists()
  const client = new Client(SOURCE_CONN)
  await client.connect()
  try {
    await client.query(`DROP TABLE IF EXISTS ${TABLE}`)
    await client.query(
      `CREATE TABLE ${TABLE} (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL)`,
    )
    await client.query(
      `INSERT INTO ${TABLE} (id, name, price) VALUES ` +
        "(1, 'Quantum Widget', 4173), (2, 'Flux Capacitor', 8821), (3, 'Warp Coil', 1590)",
    )
  } finally {
    await client.end()
  }
  return {
    spec: {
      driver: 'postgres',
      host: PG_HOST,
      port: PG_PORT,
      db_name: PG_SOURCE_DATABASE,
      username: PG_USER,
      password: PG_PASSWORD,
      ssl_mode: 'disable',
    },
    rowCount: 3,
    dispose: async () => {
      const c = new Client(SOURCE_CONN)
      await c.connect()
      try {
        await c.query(`DROP TABLE IF EXISTS ${TABLE}`)
      } finally {
        await c.end()
      }
    },
  }
}

/** Current row count of the seeded table — `-1` if the table is gone
 * entirely (e.g. a destructive statement actually ran). Used by the
 * SQL-safety negative test to prove the database was not mutated. */
export async function countSqlSourceRows(): Promise<number> {
  const client = new Client(SOURCE_CONN)
  await client.connect()
  try {
    const { rows } = await client.query(`SELECT COUNT(*)::int AS n FROM ${TABLE}`)
    return rows[0].n as number
  } catch {
    return -1
  } finally {
    await client.end()
  }
}
