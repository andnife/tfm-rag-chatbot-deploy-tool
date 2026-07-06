'use client'

import { useTranslation } from 'react-i18next'
import { Label } from '@/components/ui/label'
import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'
import { useCredentials } from '@/lib/queries'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/** Sentinel for the "inherit from the main LLM" choice (Radix needs a non-empty value). */
const INHERIT = '__inherit__'

export interface RoleLlmValue {
  /** Empty string means "inherit from the main LLM selection". */
  credentialId: string
  modelId: string
}

export const EMPTY_ROLE: RoleLlmValue = { credentialId: '', modelId: '' }

/** True when the value is either "inherit" or a fully-specified credential+model. */
export function isRoleValid(v: RoleLlmValue): boolean {
  if (!v.credentialId) return true
  return !!v.modelId
}

/**
 * Optional per-role LLM picker. Defaults to "inherit the main LLM"; once a
 * credential+model is chosen it emits {credentialId, modelId}.
 */
export function RoleLlmSelect({
  label,
  value,
  onChange,
}: {
  label: string
  value: RoleLlmValue
  onChange: (v: RoleLlmValue) => void
}) {
  const { t } = useTranslation()
  const credentialsQ = useCredentials()
  const credentials = credentialsQ.data ?? []

  const isInheriting = !value.credentialId

  function handleToggle(selectVal: string) {
    if (selectVal === INHERIT) {
      onChange(EMPTY_ROLE)
    } else {
      // selectVal is a credentialId — treat as first-time selection.
      onChange({ credentialId: selectVal, modelId: '' })
    }
  }

  function handlePickerChange(v: { credentialId: string; model: string }) {
    onChange({ credentialId: v.credentialId, modelId: v.model })
  }

  return (
    <div className="space-y-2">
      <Label>{label}</Label>

      {/* Inherit-or-override toggle */}
      <Select
        value={isInheriting ? INHERIT : value.credentialId}
        onValueChange={handleToggle}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={INHERIT}>{t('chatbots.roleInherit')}</SelectItem>
          {credentials.map((c) => (
            <SelectItem key={c.id} value={c.id}>
              {c.label}
              {c.provider_id ? ` · ${c.provider_id}` : ''}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {/* Full credential+model picker when not inheriting */}
      {!isInheriting && (
        <CredentialModelPicker
          kind="llm"
          credentialId={value.credentialId}
          model={value.modelId}
          onChange={handlePickerChange}
        />
      )}
    </div>
  )
}
