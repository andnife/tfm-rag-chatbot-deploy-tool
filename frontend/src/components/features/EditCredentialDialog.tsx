import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateCredential } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import type { CredentialOut } from '@/types/api'

interface Props {
  credential: CredentialOut | null
  onClose: () => void
}

// We reuse POST /credentials — the backend upserts by (provider_id, label),
// so saving with the same provider+label rotates the api_key and updates base_url.
export function EditCredentialDialog({ credential, onClose }: Props) {
  const { t } = useTranslation()
  const open = !!credential
  const upsert = useCreateCredential()
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [maxConc, setMaxConc] = useState('')
  const [minInterval, setMinInterval] = useState('')

  useEffect(() => {
    if (credential) {
      setApiKey('')
      setBaseUrl(credential.base_url ?? '')
      setMaxConc(credential.max_concurrency != null ? String(credential.max_concurrency) : '')
      setMinInterval(credential.min_request_interval_seconds != null ? String(credential.min_request_interval_seconds) : '')
    }
  }, [credential])

  const onSave = () => {
    if (!credential) return
    if (!apiKey.trim()) {
      toast.error(t('credentials.newApiKeyRequired'))
      return
    }
    upsert.mutate(
      {
        provider_id: credential.provider_id,
        label: credential.label,
        api_key: apiKey,
        base_url: baseUrl.trim() || null,
        max_concurrency: maxConc.trim() ? parseInt(maxConc, 10) : null,
        min_request_interval_seconds: minInterval.trim() ? parseFloat(minInterval) : null,
      },
      {
        onSuccess: () => {
          toast.success(t('credentials.updated'))
          onClose()
        },
        onError: (err) =>
          toast.error(err instanceof ApiError ? err.message : t('credentials.errorSave')),
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose() }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('credentials.editTitle')}</DialogTitle>
        </DialogHeader>
        {credential && (
          <div className="space-y-4">
            <div className="rounded-md bg-gray-50 p-3 text-xs space-y-1">
              <div>
                <span className="text-gray-500">{t('credentials.provider')}:</span>{' '}
                <span className="font-mono">{credential.provider_id}</span>
              </div>
              <div>
                <span className="text-gray-500">{t('credentials.label')}:</span>{' '}
                <span className="font-mono">{credential.label}</span>
              </div>
              <p className="text-gray-400 text-[10px] pt-1">
                {t('credentials.editNote')}
              </p>
            </div>
            <div className="space-y-2">
              <Label>{t('credentials.newApiKey')}</Label>
              <Input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
              />
            </div>
            <div className="space-y-2">
              <Label>{t('credentials.baseUrl')}</Label>
              <Input
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.openai.com/v1"
              />
            </div>
            <div className="space-y-2">
              <Label>{t('credentials.maxConcurrency')}</Label>
              <Input
                type="number"
                min={1}
                value={maxConc}
                onChange={(e) => setMaxConc(e.target.value)}
                placeholder={t('credentials.maxConcurrencyPlaceholder')}
              />
              <p className="text-xs text-fg-muted">{t('credentials.maxConcurrencyHint')}</p>
            </div>
            <div className="space-y-2">
              <Label>{t('credentials.minInterval')}</Label>
              <Input
                type="number"
                min={0}
                step="0.1"
                value={minInterval}
                onChange={(e) => setMinInterval(e.target.value)}
                placeholder={t('credentials.minIntervalPlaceholder')}
              />
              <p className="text-xs text-fg-muted">{t('credentials.minIntervalHint')}</p>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button onClick={onSave} disabled={upsert.isPending}>
                {upsert.isPending ? t('common.saving') : t('common.save')}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
