'use client'

import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'

export interface JudgeSelection {
  credential_id: string
  judge_model: string
}

interface JudgeModelSelectProps {
  value: JudgeSelection
  onChange: (v: JudgeSelection) => void
}

/**
 * Credential-first judge selector. A thin wrapper over CredentialModelPicker
 * (kind="llm") that maps {credentialId, model} to {credential_id, judge_model}.
 */
export function JudgeModelSelect({ value, onChange }: JudgeModelSelectProps) {
  function handleChange(v: { credentialId: string; model: string }) {
    onChange({ credential_id: v.credentialId, judge_model: v.model })
  }

  return (
    <CredentialModelPicker
      kind="llm"
      credentialId={value.credential_id || null}
      model={value.judge_model}
      onChange={handleChange}
    />
  )
}
