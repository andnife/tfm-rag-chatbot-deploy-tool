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
  {
    id: 'openai_compat',
    display_name: 'OpenAI-compatible endpoint',
    description: '',
    config_source: 'TENANT_CREDENTIAL',
    requires_base_url_input: true,
    supports_tool_calling: true,
    default_models: [],
  },
]

// Open the dialog and wait until the default provider (OpenAI) is applied — the
// managed-provider hint only renders once a fixed-endpoint provider is selected.
async function openDialog(): Promise<void> {
  fireEvent.click(screen.getByRole('button', { name: 'Añadir credencial' }))
  await screen.findByText(/endpoint fijo y límites de tasa recomendados/i)
}

async function selectProvider(label: string): Promise<void> {
  fireEvent.click(screen.getByRole('combobox'))
  const listbox = await screen.findByRole('listbox')
  fireEvent.click(within(listbox).getByText(label))
}

describe('AddCredentialDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.apiFetch).mockImplementation((path: string) => {
      if (path === '/providers/llm') return Promise.resolve(PROVIDERS)
      return Promise.reject(new Error(`unmocked path: ${path}`))
    })
  })

  it('defaults the provider to OpenAI when opened', async () => {
    renderWithQueryClient(<AddCredentialDialog />)
    await openDialog()
    // OpenAI is preselected → its managed-provider hint is shown and there is
    // no lingering "select a provider" placeholder state.
    expect(
      screen.getByText(/endpoint fijo y límites de tasa recomendados/i),
    ).toBeInTheDocument()
  })

  it('does not submit until required fields are filled', async () => {
    renderWithQueryClient(<AddCredentialDialog />)
    await openDialog()

    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))

    // Provider is prefilled (OpenAI); label + api_key are still required.
    expect(await screen.findByText('Etiqueta obligatoria')).toBeInTheDocument()
    expect(screen.getByText('API key obligatoria')).toBeInTheDocument()
    expect(api.apiJson).not.toHaveBeenCalled()
  })

  it('submits the create-credential request with the default OpenAI provider', async () => {
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
    await openDialog()

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
          base_url: null, // OpenAI: no endpoint URL sent
        }),
      )
    })
  })

  it('hides base_url + concurrency and shows the managed hint for OpenAI', async () => {
    renderWithQueryClient(<AddCredentialDialog />)
    await openDialog() // OpenAI is the default

    expect(screen.queryByLabelText('URL del endpoint')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Concurrencia máxima')).not.toBeInTheDocument()
    expect(
      screen.getByText(/endpoint fijo y límites de tasa recomendados/i),
    ).toBeInTheDocument()
  })

  it('requires an endpoint URL for OpenAI-compatible providers', async () => {
    renderWithQueryClient(<AddCredentialDialog />)
    await openDialog()
    await selectProvider('OpenAI-compatible endpoint')

    // base_url field appears for a compat provider.
    expect(screen.getByLabelText('URL del endpoint')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Etiqueta'), { target: { value: 'Groq' } })
    fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'sk-x' } })
    // Submit with an empty base_url → validation blocks it.
    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }))

    expect(
      await screen.findByText(/obligatoria para proveedores compatibles con OpenAI/i),
    ).toBeInTheDocument()
    expect(api.apiJson).not.toHaveBeenCalled()
  })
})
