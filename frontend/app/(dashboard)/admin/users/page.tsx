'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { SuperadminGuard } from '@/components/SuperadminGuard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import { useAdminTenants, useAdminTenantDetail } from '@/lib/queries'

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="text-gray-500 min-w-[120px]">{label}</span>
      <span className="font-mono break-all">{value}</span>
    </div>
  )
}

function UsersPageInner() {
  const { t } = useTranslation()
  const { data: tenants, isLoading } = useAdminTenants()
  const [selected, setSelected] = useState<string | null>(null)
  const { data: detail, isLoading: detailLoading } = useAdminTenantDetail(selected)

  return (
    <AppShell title={t('nav.users')}>
      <p className="text-sm text-gray-500 mb-4">
        {t('admin.users.intro')}
      </p>
      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        {/* Master: tenants + users */}
        <div className="space-y-3">
          {isLoading && <p className="text-sm text-gray-500">{t('common.loading')}</p>}
          {tenants?.map((tn) => (
            <Card
              key={tn.tenant_id}
              className={cn(
                'cursor-pointer transition-colors',
                selected === tn.tenant_id ? 'ring-2 ring-gray-900' : 'hover:bg-gray-50',
              )}
              onClick={() => setSelected(tn.tenant_id)}
            >
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center justify-between">
                  <span className="break-all">{tn.name}</span>
                  <Badge variant="info">{t('admin.users.userCount', { count: tn.users.length })}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {tn.users.map((u) => (
                  <div key={u.id} className="flex items-center gap-2 text-xs">
                    <span className="font-mono break-all">{u.email}</span>
                    {u.is_superadmin && <Badge>superadmin</Badge>}
                  </div>
                ))}
                <Row label="tenant_id" value={tn.tenant_id} />
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Detail: selected tenant's resources */}
        <div>
          {!selected && (
            <p className="text-sm text-gray-500">
              {t('admin.users.selectTenant')}
            </p>
          )}
          {selected && detailLoading && <p className="text-sm text-gray-500">{t('common.loading')}</p>}
          {detail && (
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t('admin.users.chatbotsCard', { count: detail.chatbots.length })}</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {detail.chatbots.length === 0 && <p className="text-xs text-gray-400">—</p>}
                  {detail.chatbots.map((c) => (
                    <div key={c.id} className="text-xs">
                      <span className="font-medium">{c.name}</span>
                      {c.description && <span className="text-gray-500"> — {c.description}</span>}
                    </div>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t('admin.users.kbsCard', { count: detail.knowledge_bases.length })}</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {detail.knowledge_bases.length === 0 && <p className="text-xs text-gray-400">—</p>}
                  {detail.knowledge_bases.map((k) => (
                    <div key={k.id} className="text-xs">
                      <span className="font-medium">{k.name}</span>
                      {k.description && <span className="text-gray-500"> — {k.description}</span>}
                    </div>
                  ))}
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-sm">{t('admin.users.credentialsCard', { count: detail.credentials.length })}</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  {detail.credentials.length === 0 && <p className="text-xs text-gray-400">—</p>}
                  {detail.credentials.map((cr) => (
                    <div key={cr.id} className="space-y-1 border-b last:border-0 pb-2 last:pb-0">
                      <Row label="proveedor" value={cr.provider_id} />
                      <Row label="label" value={cr.label} />
                      <Row label="base_url" value={cr.base_url ?? '—'} />
                      <Row label="origen" value={cr.config_source} />
                    </div>
                  ))}
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}

export default function UsersPage() {
  return (
    <SuperadminGuard>
      <UsersPageInner />
    </SuperadminGuard>
  )
}
