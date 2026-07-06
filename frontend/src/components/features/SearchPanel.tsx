import { useState } from 'react'
import { Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useKbSearch } from '@/lib/queries'

export function SearchPanel({ kbId }: { kbId: string }) {
  const { t } = useTranslation()
  const [q, setQ] = useState('')
  const search = useKbSearch(kbId)

  const onRun = () => {
    if (!q.trim()) return
    search.mutate(q.trim())
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input value={q} onChange={e => setQ(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && onRun()}
          placeholder={t('search.placeholder')} />
        <Button onClick={onRun} disabled={search.isPending || !q.trim()}>
          <Search className="h-4 w-4" /> {t('search.button')}
        </Button>
      </div>
      {search.data && (
        <div className="space-y-3">
          {search.data.length === 0 && <p className="text-gray-500 text-sm">{t('search.noResults')}</p>}
          {search.data.map((hit, i) => (
            <Card key={i}>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-gray-500">{hit.source_filename ?? hit.source_id} · chunk {hit.chunk_index}</span>
                  <Badge>{hit.score.toFixed(3)}</Badge>
                </div>
                <p className="text-sm whitespace-pre-wrap">{hit.content}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
