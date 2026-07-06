import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import type { RetrievalIteration } from '@/types/api'

export function IterationPanel({ iterations }: { iterations: RetrievalIteration[] }) {
  const { t } = useTranslation()
  if (iterations.length === 0) return null
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm">{t('iterationPanel.title')}</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {iterations.map((it) => (
          <div key={it.index} className="text-xs">
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="info">#{it.index}</Badge>
              <span className="font-mono font-medium">{it.tool}</span>
              <span className="text-gray-500">{it.latency_ms}ms</span>
              {it.num_chunks !== null && it.num_chunks !== undefined && (
                <span className="text-gray-500">{it.num_chunks} chunks</span>
              )}
            </div>
            {it.query && (
              <pre className="bg-gray-50 rounded p-2 overflow-x-auto text-[10px] leading-tight">
                {it.query}
              </pre>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
