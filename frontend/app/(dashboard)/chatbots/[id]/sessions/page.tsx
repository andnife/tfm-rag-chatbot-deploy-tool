'use client'

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowLeft, MessageSquare, Globe, Bot } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useChatbotSessions, useSessionDetail, useChatbot } from '@/lib/queries'
import type { SessionMessage } from '@/types/api'

type OriginFilter = 'all' | 'playground' | 'widget'

function truncateId(id: string) {
  return id.length > 8 ? id.slice(0, 8) + '…' : id
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('es-ES', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function SessionsPage() {
  const { t } = useTranslation()
  const params = useParams<{ id: string }>()
  const chatbotId = params.id ?? ''
  const { data: bot } = useChatbot(chatbotId)
  const { data: sessions, isLoading } = useChatbotSessions(chatbotId)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [originFilter, setOriginFilter] = useState<OriginFilter>('all')
  const { data: detail, isLoading: loadingDetail } = useSessionDetail(selectedSessionId)

  const filteredSessions = useMemo(() => {
    if (!sessions) return []
    if (originFilter === 'all') return sessions
    return sessions.filter((s) => s.origin === originFilter)
  }, [sessions, originFilter])

  return (
    <AppShell title={bot?.name ? `${t('sessions.title')} · ${bot.name}` : t('sessions.title')}>
      <div className="mb-4 flex items-center justify-between">
        <Link href="/chatbots" className="text-sm text-primary-600 hover:underline inline-flex items-center">
          <ArrowLeft className="h-4 w-4 mr-1" /> {t('common.back')}
        </Link>
        {sessions && sessions.length > 0 && (
          <div className="w-48">
            <Select value={originFilter} onValueChange={(v) => setOriginFilter(v as OriginFilter)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('sessions.all')}</SelectItem>
                <SelectItem value="playground">{t('sessions.playground')}</SelectItem>
                <SelectItem value="widget">{t('sessions.widget')}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      {isLoading && <p className="text-fg-muted">{t('common.loading')}</p>}

      {sessions && sessions.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            {t('sessions.empty')}
          </CardContent>
        </Card>
      )}

      {sessions && sessions.length > 0 && filteredSessions.length === 0 && (
        <p className="text-gray-500 text-sm">{t('common.empty')}</p>
      )}

      {filteredSessions.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-gray-500">
                <th className="pb-2 font-medium">{t('sessions.colId')}</th>
                <th className="pb-2 font-medium">{t('sessions.colOrigin')}</th>
                <th className="pb-2 font-medium">{t('sessions.colCreated')}</th>
                <th className="pb-2 font-medium">{t('sessions.colLastActivity')}</th>
              </tr>
            </thead>
            <tbody>
              {filteredSessions.map((s) => (
                <tr
                  key={s.id}
                  className="border-b last:border-0 hover:bg-surface cursor-pointer transition-colors"
                  onClick={() => setSelectedSessionId(s.id)}
                >
                  <td className="py-3 font-mono text-xs">{truncateId(s.id)}</td>
                  <td className="py-3">
                    <Badge variant={s.origin === 'playground' ? 'info' : 'default'}>
                      {s.origin === 'playground' ? (
                        <MessageSquare className="h-3 w-3 mr-1 inline" />
                      ) : (
                        <Globe className="h-3 w-3 mr-1 inline" />
                      )}
                      {s.origin}
                    </Badge>
                  </td>
                  <td className="py-3 text-gray-500">{formatDate(s.created_at)}</td>
                  <td className="py-3 text-gray-500">{formatDate(s.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Dialog open={!!selectedSessionId} onOpenChange={(open) => { if (!open) setSelectedSessionId(null) }}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>{t('sessions.detailTitle')}</DialogTitle>
          </DialogHeader>
          {loadingDetail && <p className="text-gray-500 text-sm">{t('sessions.loadingMessages')}</p>}
          {detail && (
            <div className="overflow-y-auto flex-1 space-y-3 py-2">
              {detail.messages.length === 0 && (
                <p className="text-fg-faint text-sm text-center py-6">{t('sessions.noMessages')}</p>
              )}
              {detail.messages.map((msg: SessionMessage) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
                      msg.role === 'user'
                        ? 'bg-primary-600 text-white'
                        : 'bg-surface text-fg'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 mb-1 opacity-70 text-xs">
                      {msg.role === 'user' ? t('sessions.roleUser') : <><Bot className="h-3 w-3" /> {t('sessions.roleAssistant')}</>}
                    </div>
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </AppShell>
  )
}
