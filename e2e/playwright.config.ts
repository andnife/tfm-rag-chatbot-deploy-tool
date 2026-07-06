import { defineConfig } from '@playwright/test'
import { BASE_URL, STORAGE_STATE } from './lib/env'

// Two projects:
//  - fast: specs that don't touch the model (CRUD/validation/errors/nav) — parallel.
//  - llm:  specs that touch generation/embeddings (ingestion, chat, eval, journeys)
//          — serial (one CPU Ollama), via the nginx mirror, 600s timeout.
const LLM_GLOBS = [
  '**/areas/ingestion.spec.ts',
  '**/areas/chat.spec.ts',
  '**/areas/eval.spec.ts',
  '**/areas/sql-route.spec.ts',
  '**/areas/public-widget.spec.ts',
  '**/journeys/**.spec.ts',
]

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  globalTeardown: './global-teardown.ts',
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    storageState: STORAGE_STATE, // logged-in by default; auth specs override to anonymous
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      // Serial: the backend is not concurrency-safe under parallel KB/chatbot
      // creation (Qdrant collection races + tenant-visibility races under load),
      // so we run one worker. Still "fast" because it never waits on the LLM.
      name: 'fast',
      testMatch: ['**/areas/**.spec.ts'],
      testIgnore: LLM_GLOBS,
      timeout: 60_000,
      fullyParallel: false,
      workers: 1,
    },
    {
      name: 'llm',
      testMatch: LLM_GLOBS,
      timeout: 600_000,
      fullyParallel: false,
      workers: 1,
    },
  ],
})
