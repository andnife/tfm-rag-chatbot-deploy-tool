'use client'

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { Plus, Search } from 'lucide-react'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { KBCard } from '@/components/features/KBCard'
import { useKnowledgeBases } from '@/lib/queries'

export default function KnowledgeListPage() {
  const { t } = useTranslation()
  const { data: kbs, isLoading } = useKnowledgeBases()
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    if (!kbs) return []
    const q = query.trim().toLowerCase()
    if (!q) return kbs
    return kbs.filter(
      (kb) =>
        kb.name.toLowerCase().includes(q) ||
        (kb.description ?? '').toLowerCase().includes(q) ||
        kb.embedding_selection.model_id.toLowerCase().includes(q),
    )
  }, [kbs, query])

  return (
    <AppShell title={t('kb.title')}>
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3 mb-6">
        <p className="text-gray-500">{t('kb.subtitle')}</p>
        <Link href="/knowledge/new">
          <Button>
            <Plus className="h-4 w-4" /> {t('kb.new')}
          </Button>
        </Link>
      </div>

      {kbs && kbs.length > 0 && (
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
      {kbs && kbs.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-gray-500">
            {t('kb.empty')}{' '}
            <Link href="/knowledge/new" className="text-primary-600 hover:underline">
              {t('kb.new')}
            </Link>
            .
          </CardContent>
        </Card>
      )}
      {filtered.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((kb) => (
            <KBCard key={kb.id} kb={kb} />
          ))}
        </div>
      )}
      {kbs && kbs.length > 0 && filtered.length === 0 && (
        <p className="text-gray-500 text-sm">{t('common.empty')}</p>
      )}
    </AppShell>
  )
}
