import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import type { Citation } from '@/types/api'

interface Props {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

export function ChatMessage({ role, content, citations }: Props) {
  const { t } = useTranslation()
  const isUser = role === 'user'
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const toggle = (key: string) => {
    setExpanded((s) => ({ ...s, [key]: !s[key] }))
  }

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[80%] rounded-lg px-4 py-3 text-sm',
          isUser
            ? 'bg-primary-600 text-white'
            : 'bg-canvas border border-line shadow-xs',
        )}
      >
        <div className="whitespace-pre-wrap">{content}</div>
        {!isUser && citations && citations.length > 0 && (
          <div className="mt-3 pt-3 border-t border-line space-y-1">
            <div className="text-xs font-semibold text-fg-muted mb-1">{t('chatMessage.sources')}</div>
            {citations.map((c, i) => {
              const key = c.chunk_id ?? String(i)
              const isOpen = !!expanded[key]
              const hasPreview = !!c.preview && c.preview.length > 0
              return (
                <div key={key} className="text-xs">
                  <button
                    type="button"
                    onClick={() => hasPreview && toggle(key)}
                    className={cn(
                      'w-full text-left flex items-start gap-2 py-1 rounded -mx-1 px-1',
                      hasPreview && 'hover:bg-surface cursor-pointer',
                    )}
                    disabled={!hasPreview}
                  >
                    {hasPreview ? (
                      isOpen ? (
                        <ChevronDown className="h-3 w-3 mt-0.5 text-fg-faint shrink-0" />
                      ) : (
                        <ChevronRight className="h-3 w-3 mt-0.5 text-fg-faint shrink-0" />
                      )
                    ) : (
                      <span className="w-3 shrink-0" />
                    )}
                    <Badge className="shrink-0">[{i + 1}]</Badge>
                    <span className="flex-1 min-w-0 text-fg-muted">
                      <span className="font-medium">{c.source_name}</span>
                      {c.location && <span className="text-fg-faint"> · {c.location}</span>}
                      <span className="ml-2 text-fg-faint">
                        ({(c.score * 100).toFixed(0)}%)
                      </span>
                    </span>
                  </button>
                  {hasPreview && isOpen && (
                    <pre className="mt-1 ml-6 bg-surface-2 rounded p-2 text-[11px] leading-relaxed whitespace-pre-wrap font-sans text-fg-muted max-h-48 overflow-y-auto">
                      {c.preview}
                    </pre>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
