import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Vitest config for the Next 14 (App Router) frontend. Kept separate from
// next.config.js — Next's own bundler (SWC) never runs the test files;
// Vite/esbuild (via @vitejs/plugin-react) compiles them instead. The `@/*`
// alias mirrors tsconfig.json's `paths` so component imports resolve the
// same way in tests as they do in the app.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // Explicit imports (`import { describe, it, expect } from 'vitest'`) in
    // every test file instead of globals — keeps `next build`'s type-check
    // pass (which walks every .ts/.tsx under tsconfig's `include`) from
    // needing a "vitest/globals" ambient-types entry.
    globals: false,
    css: false,
  },
})
