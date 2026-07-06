'use client'

import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'
import type { LlmSelection } from '@/types/api'

export interface LlmModelSelectProps {
  /** Currently selected credential id (null = none). */
  credentialId: string | null
  /** Currently selected model id. */
  model: string
  /** Called on every change with the full LlmSelection payload. */
  onChange: (v: LlmSelection) => void
  disabled?: boolean
}

/**
 * Credential-first LLM selector. Wraps CredentialModelPicker (kind="llm") and
 * maps {credentialId, model} to the {credential_id, model_id} LlmSelection shape.
 */
export function LlmModelSelect({
  credentialId,
  model,
  onChange,
  disabled = false,
}: LlmModelSelectProps) {
  function handleChange(v: { credentialId: string; model: string }) {
    onChange({ credential_id: v.credentialId, model_id: v.model })
  }

  return (
    <CredentialModelPicker
      kind="llm"
      credentialId={credentialId}
      model={model}
      onChange={handleChange}
      disabled={disabled}
    />
  )
}
