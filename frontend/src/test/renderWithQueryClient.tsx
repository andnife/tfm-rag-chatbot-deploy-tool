import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, type RenderResult } from '@testing-library/react'

/**
 * Render helper for components that call `useQuery`/`useMutation` (via
 * src/lib/queries.ts). Each call gets a fresh QueryClient with retries
 * disabled — otherwise a failing mocked fetch retries and tests time out.
 */
export function renderWithQueryClient(ui: ReactElement): RenderResult {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}
