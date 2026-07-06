import { CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { useModelsForCredential } from '@/lib/queries'
import { ApiError } from '@/lib/api'

interface Props { credentialId: string | null; onClose: () => void }

/**
 * "Probar credencial" — instead of asking the user to type a model id, this
 * fetches the credential's live model catalog (GET /credentials/{id}/models).
 * A successful fetch IS the connectivity proof; the returned list is shown so
 * the user sees exactly which models the credential/endpoint offers.
 */
export function TestCredentialDialog({ credentialId, onClose }: Props) {
  const { t } = useTranslation()
  const q = useModelsForCredential(credentialId)
  const models = q.data?.models ?? []
  const providerError = q.data?.error ?? null
  // The endpoint returns 200 with {models:[], error} on upstream failure;
  // q.isError only fires for 404 (unknown credential) / network.
  const failed = q.isError || !!providerError
  const errorMsg =
    providerError ??
    (q.error instanceof ApiError ? q.error.message : null) ??
    t('credentials.testFailed')

  return (
    <Dialog open={credentialId !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('credentials.testTitle')}</DialogTitle></DialogHeader>
        <div className="space-y-4">
          {q.isLoading && (
            <div className="flex items-center gap-2 text-fg-muted text-sm">
              <Loader2 className="h-5 w-5 animate-spin" /> {t('common.testing')}
            </div>
          )}

          {!q.isLoading && !failed && (
            <>
              <div className="flex items-center gap-2 text-success text-sm">
                <CheckCircle2 className="h-5 w-5" />
                {models.length > 0
                  ? t('credentials.modelsAvailable', { count: models.length })
                  : t('credentials.noModelsFound')}
              </div>
              {models.length > 0 && (
                <ul className="max-h-60 overflow-y-auto rounded-md border border-line divide-y divide-line text-sm">
                  {models.map((m) => (
                    <li key={m.id} className="flex items-center justify-between px-3 py-1.5">
                      <span className="font-mono">{m.id}</span>
                      <span className="text-fg-muted text-xs">{m.kind}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {!q.isLoading && failed && (
            <div className="flex items-start gap-2 text-danger text-sm">
              <XCircle className="h-5 w-5 shrink-0" /> {errorMsg}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>{t('common.close')}</Button>
            <Button onClick={() => q.refetch()} disabled={q.isFetching}>
              {q.isFetching ? t('common.testing') : t('common.test')}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
