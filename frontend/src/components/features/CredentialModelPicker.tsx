'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { useCredentials, useEmbeddingDimension, useEmbeddingProviders, useModelsForCredential } from '@/lib/queries'

// Sentinel value used inside the <Select> to represent the "free-text / custom"
// option. It must not collide with a real model id returned by the API.
const FREE_TEXT_SENTINEL = '__custom__'

type Kind = 'llm' | 'embedding'

export interface CredentialModelPickerProps {
  kind: Kind
  credentialId: string | null
  model: string
  dim?: number              // embedding only
  onChange: (v: { credentialId: string; model: string; dim?: number }) => void
  disabled?: boolean
}

/**
 * Credential-first model picker.
 *
 * 1. Shows a credential select populated from useCredentials().
 * 2. On credential change, fetches available models via useModelsForCredential().
 * 3. Filters the model list by `kind` (llm picker hides 'embedding'; embedding
 *    picker hides 'llm'; 'unknown' is always shown).
 * 4. Always offers a "custom / free-text" option so the user can type a model
 *    id not returned by the endpoint.
 * 5. When kind === 'embedding', auto-fills `dim` from the embedding provider
 *    catalog when the chosen model matches a known (model_id, dim) tuple.
 *    Otherwise shows an editable numeric input.
 * 6. Emits onChange({credentialId, model, dim?}) on every change.
 */
export function CredentialModelPicker({
  kind,
  credentialId,
  model,
  dim,
  onChange,
  disabled = false,
}: CredentialModelPickerProps) {
  const { t } = useTranslation()

  const credentialsQ = useCredentials()
  const modelsQ = useModelsForCredential(credentialId)
  const embeddingProvidersQ = useEmbeddingProviders()

  // Track whether the user has chosen to enter a free-text model id.
  // We start in free-text mode if the current model value is set but not in
  // the list (handled below after the list is computed).
  const [customModelText, setCustomModelText] = useState<string>('')

  // Free-text filter for the (potentially long) model dropdown.
  const [modelQuery, setModelQuery] = useState<string>('')

  // ---------- Credential options ----------
  const credentials = credentialsQ.data ?? []

  // ---------- Model list from the live endpoint ----------
  const fetchError = modelsQ.data?.error ?? null
  const rawModels = modelsQ.data?.models ?? []

  // Filter by kind: prefer models the endpoint classified as this exact kind
  // (so the embedding picker doesn't show text-generation models and vice
  // versa). Fall back to 'unknown' models only when the endpoint classified
  // none of this kind (e.g. an endpoint that exposes no tags) — otherwise the
  // user would be stuck with an empty list.
  const exactKind = rawModels.filter((m) => m.kind === kind)
  const filteredModels = exactKind.length > 0
    ? exactKind
    : rawModels.filter((m) => m.kind === 'unknown')

  // Apply the free-text search box on top of the kind filter.
  const q = modelQuery.trim().toLowerCase()
  const visibleModels = q
    ? filteredModels.filter((m) => m.id.toLowerCase().includes(q))
    : filteredModels

  // Determine whether the current model value is in the fetched list.
  const modelInList = model ? filteredModels.some((m) => m.id === model) : false
  // If the model is set but not in the list, that counts as free-text mode.
  const isInFreeTextMode =
    !modelInList && (!!model || !!customModelText)

  // The value to bind to the <Select> — sentinel when in free-text mode.
  const selectValue = isInFreeTextMode ? FREE_TEXT_SENTINEL : (model || '')

  // ---------- Dim auto-fill from embedding catalog ----------
  function lookupDim(modelId: string): number | undefined {
    if (kind !== 'embedding') return undefined
    const providers = embeddingProvidersQ.data ?? []
    for (const p of providers) {
      const tuple = p.default_models.find(([mid]) => mid === modelId)
      if (tuple) return tuple[1]
    }
    return undefined
  }

  // ---------- Event handlers ----------
  function handleCredentialChange(newCredId: string) {
    // Reset model on credential change — including the free-text buffer, so a
    // model typed under the previous credential can't be silently re-emitted
    // under the new one.
    setCustomModelText('')
    onChange({ credentialId: newCredId, model: '', dim: undefined })
  }

  function handleModelSelect(value: string) {
    if (value === FREE_TEXT_SENTINEL) {
      // Switch to free-text mode; preserve the last custom text if any.
      const text = customModelText || ''
      // Emit with the current text (may be empty); parent will wait for input.
      if (credentialId) {
        const autoDim = lookupDim(text)
        onChange({
          credentialId,
          model: text,
          ...(kind === 'embedding' ? { dim: autoDim ?? dim } : {}),
        })
      }
      return
    }
    // Known model selected.
    setCustomModelText('')
    if (credentialId) {
      const autoDim = lookupDim(value)
      onChange({
        credentialId,
        model: value,
        ...(kind === 'embedding' ? { dim: autoDim } : {}),
      })
    }
  }

  function handleCustomModelInput(text: string) {
    setCustomModelText(text)
    if (credentialId) {
      const autoDim = lookupDim(text)
      onChange({
        credentialId,
        model: text,
        ...(kind === 'embedding' ? { dim: autoDim ?? dim } : {}),
      })
    }
  }

  function handleDimChange(raw: string) {
    const parsed = parseInt(raw, 10)
    if (credentialId) {
      onChange({
        credentialId,
        model,
        dim: isNaN(parsed) ? undefined : parsed,
      })
    }
  }

  // ---------- Dim display logic ----------
  // 1) Catalog match (instant). 2) Otherwise auto-detect by probing the
  //    endpoint (embeds a short text, measures the vector length) — only for a
  //    listed model outside the catalog. 3) Manual entry only as last resort
  //    (probe failed, or a free-text/custom model the endpoint can't probe).
  const catalogDim = model ? lookupDim(model) : undefined
  const needsProbe =
    kind === 'embedding' && !!credentialId && !!model && !isInFreeTextMode &&
    catalogDim === undefined
  const dimProbe = useEmbeddingDimension(credentialId, model, needsProbe)
  const probedDim = needsProbe ? (dimProbe.data?.dim ?? undefined) : undefined
  const probing = needsProbe && dimProbe.isFetching
  const probeFailed =
    needsProbe && !dimProbe.isFetching &&
    (dimProbe.isError || (dimProbe.data != null && dimProbe.data.dim == null))

  const autoDim = catalogDim ?? probedDim
  const dimIsAutoFilled = autoDim !== undefined
  const dimValue = dim ?? autoDim ?? ''

  // The catalog path emits the dim at selection time; the probe is async, so
  // push the detected dimension up to the parent once it resolves.
  useEffect(() => {
    if (needsProbe && probedDim !== undefined && dim !== probedDim && credentialId) {
      onChange({ credentialId, model, dim: probedDim })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [probedDim, needsProbe, credentialId, model])

  // ---------- Render ----------
  return (
    <div className="space-y-3">
      {/* Credential selector */}
      <div className="space-y-1">
        <Label>{t('selectors.credential')}</Label>
        {credentials.length === 0 && !credentialsQ.isLoading ? (
          <p className="text-xs text-muted-foreground">{t('selectors.noCredentials')}</p>
        ) : (
          <Select
            value={credentialId ?? ''}
            onValueChange={handleCredentialChange}
            disabled={disabled || credentialsQ.isLoading}
          >
            <SelectTrigger>
              <SelectValue placeholder={t('selectors.selectCredential')} />
            </SelectTrigger>
            <SelectContent>
              {credentials.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.label}
                  {c.provider_id ? ` · ${c.provider_id}` : ''}
                  {c.base_url ? ` (${c.base_url})` : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Model selector — shown once a credential is chosen */}
      {credentialId && (
        <div className="space-y-1">
          <Label>{t('selectors.model')}</Label>

          {/* Fetch-failed / empty-list hint */}
          {(fetchError || (modelsQ.isFetched && filteredModels.length === 0)) && (
            <p className="text-xs text-muted-foreground">{t('selectors.fetchFailed')}</p>
          )}

          {/* Select with fetched models + custom option */}
          <Select
            value={selectValue}
            onValueChange={handleModelSelect}
            onOpenChange={(open) => { if (!open) setModelQuery('') }}
            disabled={disabled || modelsQ.isLoading}
          >
            <SelectTrigger>
              <SelectValue
                placeholder={
                  modelsQ.isLoading
                    ? '…'
                    : t('selectors.selectModel')
                }
              />
            </SelectTrigger>
            <SelectContent>
              {/* Type-to-filter box for long model lists (e.g. DeepInfra).
                  stopPropagation keeps Radix Select's typeahead from hijacking
                  the keystrokes so the input stays editable. */}
              <div className="sticky top-0 z-10 bg-canvas p-1">
                <Input
                  autoFocus
                  placeholder={t('selectors.filterModels')}
                  value={modelQuery}
                  onChange={(e) => setModelQuery(e.target.value)}
                  onKeyDown={(e) => e.stopPropagation()}
                  className="h-8"
                />
              </div>
              {visibleModels.map((m) => (
                <SelectItem key={m.id} value={m.id}>
                  {m.id}
                </SelectItem>
              ))}
              {q && visibleModels.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-muted-foreground">
                  {t('selectors.noModelMatches')}
                </p>
              )}
              <SelectItem value={FREE_TEXT_SENTINEL}>
                {t('selectors.freeTextModel')}
              </SelectItem>
            </SelectContent>
          </Select>

          {/* Free-text input when in custom mode */}
          {isInFreeTextMode && (
            <Input
              placeholder={t('selectors.freeTextModel')}
              value={customModelText || model}
              onChange={(e) => handleCustomModelInput(e.target.value)}
              disabled={disabled}
              className="mt-1"
            />
          )}
        </div>
      )}

      {/* Dim field — embedding only */}
      {kind === 'embedding' && credentialId && model && (
        <div className="space-y-1">
          <Label>{t('selectors.dim')}</Label>
          {probing ? (
            <Input value={t('selectors.detectingDim')} readOnly disabled
                   className="bg-muted cursor-progress text-muted-foreground" />
          ) : (
            <Input
              type="number"
              min={1}
              value={dimValue}
              readOnly={dimIsAutoFilled}
              disabled={disabled || dimIsAutoFilled}
              onChange={(e) => handleDimChange(e.target.value)}
              className={dimIsAutoFilled ? 'bg-muted cursor-not-allowed' : ''}
            />
          )}
          {dimIsAutoFilled && !probing && (
            <p className="text-xs text-muted-foreground">{t('selectors.dimAutoDetected')}</p>
          )}
          {probeFailed && (
            <p className="text-xs text-muted-foreground">{t('selectors.dimProbeFailed')}</p>
          )}
        </div>
      )}
    </div>
  )
}
