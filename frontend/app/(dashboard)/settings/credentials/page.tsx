'use client'

import { useState } from 'react'
import { Pencil, Trash2, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { AddCredentialDialog } from '@/components/features/AddCredentialDialog'
import { EditCredentialDialog } from '@/components/features/EditCredentialDialog'
import { TestCredentialDialog } from '@/components/features/TestCredentialDialog'
import { useCredentials, useDeleteCredential } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import type { CredentialOut } from '@/types/api'

export default function CredentialsPage() {
  const { t } = useTranslation()
  const { data: creds, isLoading } = useCredentials()
  const del = useDeleteCredential()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [editing, setEditing] = useState<CredentialOut | null>(null)

  const onDelete = (id: string) => {
    if (!confirm(t('credentials.confirmDelete'))) return
    del.mutate(id, {
      onSuccess: () => toast.success(t('credentials.deleted')),
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('credentials.errorDelete')),
    })
  }

  return (
    <AppShell title={t('credentials.title')}>
      <div className="flex justify-between items-center mb-6">
        <p className="text-gray-500">{t('credentials.subtitle')}</p>
        <AddCredentialDialog />
      </div>
      {isLoading && <p className="text-gray-500">{t('common.loading')}</p>}
      {creds && creds.length === 0 && (
        <Card><CardContent className="py-12 text-center text-gray-500">
          {t('credentials.empty')}
        </CardContent></Card>
      )}
      {creds && creds.length > 0 && (
        <Card>
          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full min-w-[700px]">
              <thead>
                <tr className="text-left text-xs uppercase text-gray-500 border-b border-gray-200">
                  <th className="px-4 py-3">{t('credentials.colProvider')}</th>
                  <th className="px-4 py-3">{t('credentials.colLabel')}</th>
                  <th className="px-4 py-3">{t('credentials.colBaseUrl')}</th>
                  <th className="px-4 py-3">{t('credentials.colOrigin')}</th>
                  <th className="px-4 py-3 text-right">{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {creds.map(c => (
                  <tr key={c.id} className="border-b border-gray-100 last:border-0 text-sm">
                    <td className="px-4 py-3">{c.provider_id}</td>
                    <td className="px-4 py-3">{c.label}</td>
                    <td className="px-4 py-3 text-gray-500">{c.base_url ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">{c.config_source}</td>
                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => setTestingId(c.id)}>
                          <Zap className="h-3 w-3 mr-1" /> {t('credentials.testButton')}
                        </Button>
                        {c.config_source === 'TENANT_CREDENTIAL' && (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => setEditing(c)}
                            title={t('credentials.rotateTitle')}
                          >
                            <Pencil className="h-3 w-3" />
                          </Button>
                        )}
                        {c.config_source === 'TENANT_CREDENTIAL' && (
                          <Button size="sm" variant="danger" onClick={() => onDelete(c.id)} disabled={del.isPending}>
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
      <TestCredentialDialog credentialId={testingId} onClose={() => setTestingId(null)} />
      <EditCredentialDialog credential={editing} onClose={() => setEditing(null)} />
    </AppShell>
  )
}
