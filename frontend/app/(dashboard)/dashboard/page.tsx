'use client'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { useQueries } from '@tanstack/react-query'
import { Database, Bot, FileText, MessageSquare, Plus } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useKnowledgeBases, useChatbots, qk } from '@/lib/queries'
import { apiFetch } from '@/lib/api'
import type { SessionSummary, SourceOut } from '@/types/api'

interface StatCardProps {
  title: string
  value: number | string
  icon: React.ReactNode
  loading?: boolean
}

function StatCard({ title, value, icon, loading }: StatCardProps) {
  return (
    <Card className="p-5">
      <CardContent className="p-0 flex items-center gap-4">
        <div className="w-12 h-12 rounded-lg bg-primary-50 text-primary-600 flex items-center justify-center shrink-0">
          {icon}
        </div>
        <div>
          <p className="text-sm text-gray-500">{title}</p>
          {loading ? (
            <div className="h-7 w-12 bg-gray-200 rounded animate-pulse mt-1" />
          ) : (
            <p className="text-2xl font-bold">{value}</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const { t } = useTranslation()
  const { data: kbs, isLoading: loadingKbs } = useKnowledgeBases()
  const { data: bots, isLoading: loadingBots } = useChatbots()

  // Compute aggregate "Fuentes" by fanning out to /sources for each KB.
  const sourcesQueries = useQueries({
    queries: (kbs ?? []).map((kb) => ({
      queryKey: qk.kbs.sources(kb.id),
      queryFn: () => apiFetch<SourceOut[]>(`/knowledge-bases/${kb.id}/sources`),
      staleTime: 60_000,
    })),
  })
  const totalSources = sourcesQueries.reduce(
    (acc, q) => acc + (q.data?.length ?? 0),
    0,
  )
  const loadingSources = sourcesQueries.some((q) => q.isLoading)

  // Same for sessions per chatbot.
  const sessionQueries = useQueries({
    queries: (bots ?? []).map((b) => ({
      queryKey: qk.chatbots.sessions(b.id),
      queryFn: () =>
        apiFetch<SessionSummary[]>(`/chatbots/${b.id}/sessions`),
      staleTime: 60_000,
    })),
  })
  const totalSessions = sessionQueries.reduce(
    (acc, q) => acc + (q.data?.length ?? 0),
    0,
  )
  const loadingSessions = sessionQueries.some((q) => q.isLoading)

  // Flatten sessions into "recent activity"
  const recentSessions = sessionQueries
    .flatMap((q, i) =>
      (q.data ?? []).map((s) => ({ ...s, botName: bots?.[i]?.name ?? '?' })),
    )
    .sort(
      (a, b) =>
        new Date(b.last_activity_at).getTime() -
        new Date(a.last_activity_at).getTime(),
    )
    .slice(0, 5)

  return (
    <AppShell title={t('dashboard.title')}>
      <p className="text-gray-500 mb-6">{t('dashboard.subtitle')}</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          title={t('dashboard.kbs')}
          value={kbs?.length ?? 0}
          icon={<Database className="h-6 w-6" />}
          loading={loadingKbs}
        />
        <StatCard
          title={t('dashboard.bots')}
          value={bots?.length ?? 0}
          icon={<Bot className="h-6 w-6" />}
          loading={loadingBots}
        />
        <StatCard
          title={t('dashboard.sources')}
          value={totalSources}
          icon={<FileText className="h-6 w-6" />}
          loading={loadingSources}
        />
        <StatCard
          title={t('dashboard.sessions')}
          value={totalSessions}
          icon={<MessageSquare className="h-6 w-6" />}
          loading={loadingSessions}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>{t('dashboard.recent')}</CardTitle>
            </CardHeader>
            <CardContent>
              {recentSessions.length === 0 && (
                <p className="text-gray-500 py-4 text-sm">
                  {t('common.empty')}
                </p>
              )}
              {recentSessions.length > 0 && (
                <div className="space-y-2">
                  {recentSessions.map((s) => (
                    <Link
                      key={s.id}
                      href={`/chatbots/${s.chatbot_id}/sessions`}
                      className="flex items-center gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors"
                    >
                      <div className="w-8 h-8 rounded-md bg-primary-50 text-primary-600 flex items-center justify-center">
                        <MessageSquare className="h-4 w-4" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate text-sm">{s.botName}</p>
                        <p className="text-xs text-gray-500 font-mono">
                          {s.id.slice(0, 8)} · {s.origin}
                        </p>
                      </div>
                      <p className="text-xs text-gray-400">
                        {new Date(s.last_activity_at).toLocaleString()}
                      </p>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div>
          <Card>
            <CardHeader>
              <CardTitle>{t('dashboard.quickActions')}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Link href="/knowledge/new">
                <Button className="w-full justify-start">
                  <Plus className="h-4 w-4" /> {t('dashboard.newKb')}
                </Button>
              </Link>
              <Link href="/chatbots/new">
                <Button variant="secondary" className="w-full justify-start">
                  <Plus className="h-4 w-4" /> {t('dashboard.newBot')}
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
