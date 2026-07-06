import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { renderWithQueryClient } from '@/test/renderWithQueryClient'
import { AddCredentialDialog } from '@/components/features/AddCredentialDialog'
import * as api from '@/lib/api'
import type { LlmProvider } from '@/types/api'

// The app defaults to Spanish (src/lib/i18n.ts falls back to "es" when no
// tfm_rag_lang is in localStorage, which is the case in a fresh jsdom env),
// so assertions below use the ES catalog strings.

vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...actual,
    apiFetch: vi.fn(),
    apiJson: vi.fn(),
  }
})

const PROVIDERS: LlmProvider[] = [
  {
    id: 'openai',
    display_name: 'OpenAI',
    description: '',
    config_source: 'TENANT_CREDENTIAL',
    requires_base_url_input: false,
    supports_tool_calling: true,
    default_models: ['gpt-4o-mini'],
  },
]

describe('AddCredentialDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.apiFetch).mockImplementation((path: string) => {
      if (path === '/providers/llm') return Promise.resolve(PROVIDERS)
      return Promise.reject(new Error(`unmocked path: ${path}`))
    })
  })

  it('shows validation errors and never submits until required fields are filled', async () => {
    renderWithQueryClient(<AddCredentialDialog />)

    fireEvent.click(screen.getByRole('button', { name: 'Añadir credencial' }))

    const submit = await screen.findByRole('button', { name: 'Guardar' })
    fireEvent.click(submit)

    expect(await screen.findByText('Selecciona un proveedor')).toBeInTheDocument()
    expect(screen.getByText('Etiqueta obligatoria')).toBeInTheDocument()
    expect(screen.getByText('API key obligatoria')).toBeInTheDocument()

    // The actual create request must never fire while the form is invalid.
    expect(api.apiJson).not.toHaveBeenCalled()
  })

  it('submits the create-credential request once required fields are valid', async () => {
    vi.mocked(api.apiJson).mockResolvedValue({
      id: 'cred-1',
      provider_id: 'openai',
      label: 'Mi clave',
      base_url: null,
      config_source: 'TENANT_CREDENTIAL',
      max_concurrency: null,
      min_request_interval_seconds: null,
    })

    renderWithQueryClient(<AddCredentialDialog />)
    fireEvent.click(screen.getByRole('button', { name: 'Añadir credencial' }))

    const providerTrigger = await screen.findByText('Selecciona...')
    fireEvent.click(providerTrigger)
    // Radix Select renders a visually-hidden native <select> in addition to
    // the popper listbox — both contain an "OpenAI" text node, so scope the
    // query to the open listbox.
    const listbox = await screen.findByRole('listbox')
    fireEvent.click(within(listbox).getByText('OpenAI'))

    fireEvent.change(screen.getByLabelText('Etiqueta'), { target: { value: 'Mi clave' } })
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'sk-secret' } })

    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))

    await waitFor(() => {
      expect(api.apiJson).toHaveBeenCalledWith(
        '/credentials',
        'POST',
        expect.objectContaining({
          provider_id: 'openai',
          label: 'Mi clave',
          api_key: 'sk-secret',
        }),
      )
    })
  })
})
