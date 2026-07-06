import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { renderWithQueryClient } from '@/test/renderWithQueryClient'
import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'
import * as api from '@/lib/api'
import type { CredentialModelsResponse, CredentialOut } from '@/types/api'

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

const CREDENTIALS: CredentialOut[] = [
  {
    id: 'cred-1',
    provider_id: 'openai',
    label: 'My OpenAI key',
    base_url: null,
    config_source: 'TENANT_CREDENTIAL',
    max_concurrency: null,
    min_request_interval_seconds: null,
  },
]

const MODELS_RESPONSE: CredentialModelsResponse = {
  models: [
    { id: 'gpt-4o-mini', kind: 'llm' },
    { id: 'text-embedding-3-small', kind: 'embedding' },
  ],
  error: null,
}

function mockApiFetch() {
  vi.mocked(api.apiFetch).mockImplementation((path: string) => {
    if (path === '/credentials') return Promise.resolve(CREDENTIALS)
    if (path === '/providers/embedding') return Promise.resolve([])
    if (/^\/credentials\/.+\/models$/.test(path)) return Promise.resolve(MODELS_RESPONSE)
    return Promise.reject(new Error(`unmocked path: ${path}`))
  })
}

describe('CredentialModelPicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockApiFetch()
  })

  it('loads models for the selected credential and filters them by kind', async () => {
    renderWithQueryClient(
      <CredentialModelPicker kind="llm" credentialId="cred-1" model="" onChange={vi.fn()} />,
    )

    const modelTrigger = await screen.findByText('Selecciona modelo…')
    fireEvent.click(modelTrigger)

    // llm-kind model is offered...
    expect(await screen.findByText('gpt-4o-mini')).toBeInTheDocument()
    // ...but the embedding-kind model is filtered out for kind="llm".
    expect(screen.queryByText('text-embedding-3-small')).not.toBeInTheDocument()
  })

  it('selecting a fetched model emits onChange with the credential and model id', async () => {
    const onChange = vi.fn()
    renderWithQueryClient(
      <CredentialModelPicker kind="llm" credentialId="cred-1" model="" onChange={onChange} />,
    )

    const modelTrigger = await screen.findByText('Selecciona modelo…')
    fireEvent.click(modelTrigger)
    const option = await screen.findByText('gpt-4o-mini')
    fireEvent.click(option)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ credentialId: 'cred-1', model: 'gpt-4o-mini' }),
      )
    })
  })

  it('selecting the custom-model option notifies the parent for the active credential', async () => {
    const onChange = vi.fn()
    renderWithQueryClient(
      <CredentialModelPicker kind="llm" credentialId="cred-1" model="" onChange={onChange} />,
    )

    const modelTrigger = await screen.findByText('Selecciona modelo…')
    fireEvent.click(modelTrigger)
    const customOption = await screen.findByText('Modelo personalizado…')
    fireEvent.click(customOption)

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ credentialId: 'cred-1', model: '' }),
      )
    })
  })

  it('shows a pre-filled, editable free-text input when the current model is not in the fetched list', async () => {
    const onChange = vi.fn()
    renderWithQueryClient(
      <CredentialModelPicker
        kind="llm"
        credentialId="cred-1"
        model="my-legacy-model"
        onChange={onChange}
      />,
    )

    // A model value that doesn't match the fetched list is treated as a
    // pre-existing custom entry: the free-text input renders pre-filled...
    const input = await screen.findByPlaceholderText('Modelo personalizado…')
    expect(input).toHaveValue('my-legacy-model')

    // ...and remains editable, emitting the new value on every change.
    fireEvent.change(input, { target: { value: 'my-fine-tuned-model' } })
    await waitFor(() => {
      expect(onChange).toHaveBeenLastCalledWith(
        expect.objectContaining({ credentialId: 'cred-1', model: 'my-fine-tuned-model' }),
      )
    })
  })

  it('shows a "no credentials" hint when the credential list is empty', async () => {
    vi.mocked(api.apiFetch).mockImplementation((path: string) => {
      if (path === '/credentials') return Promise.resolve([])
      if (path === '/providers/embedding') return Promise.resolve([])
      return Promise.reject(new Error(`unmocked path: ${path}`))
    })

    renderWithQueryClient(
      <CredentialModelPicker kind="llm" credentialId={null} model="" onChange={vi.fn()} />,
    )

    expect(
      await screen.findByText('No hay credenciales. Crea una en Credenciales.'),
    ).toBeInTheDocument()
  })
})
