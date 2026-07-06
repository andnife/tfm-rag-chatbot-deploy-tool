'use client'

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { Plus, Search } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { ChatbotCard } from '@/components/features/ChatbotCard'
import { useChatbots } from '@/lib/queries'

export default function ChatbotsListPage() {
  const { t } = useTranslation()
  const { data: bots, isLoading } = useChatbots()
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    if (!bots) return []
    const q = query.trim().toLowerCase()
    if (!q) return bots
    return bots.filter(
      (b) =>
        b.name.toLowerCase().includes(q) ||
        (b.description ?? '').toLowerCase().includes(q) ||
        b.llm_selection.model_id.toLowerCase().includes(q),
    )
  }, [bots, query])

  return (
    <AppShell title={t('chatbots.title')}>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-6">
        <p className="text-gray-500">{t('chatbots.subtitle')}</p>
        <Link href="/chatbots/new">
          <Button>
            <Plus className="h-4 w-4" /> {t('chatbots.new')}
          </Button>
        </Link>
      </div>

      {bots && bots.length > 0 && (
        <div className="relative mb-4 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            placeholder={t('common.search')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
          />
        </div>
      )}

      {isLoading && <p className="text-gray-500">{t('common.loading')}</p>}
      {bots && bots.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            {t('chatbots.empty')}{' '}
            <Link href="/chatbots/new" className="text-primary-600 hover:underline">
              {t('chatbots.new')}
            </Link>
            .
          </CardContent>
        </Card>
      )}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((b) => (
            <ChatbotCard key={b.id} bot={b} />
          ))}
        </div>
      )}
      {bots && bots.length > 0 && filtered.length === 0 && (
        <p className="text-gray-500 text-sm">{t('common.empty')}</p>
      )}
    </AppShell>
  )
}
