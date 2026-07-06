'use client'

import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { EmbeddingSelection, KnowledgeBaseOut } from '@/types/api'

export interface ChatbotKnowledgeBasesCardProps {
  embeddingFilter: EmbeddingSelection | undefined
  availableKbs: KnowledgeBaseOut[]
  selectedKbIds: string[]
  onToggleKb: (kbId: string) => void
}

/** Knowledge-base selection card of the chatbot edit page. */
export function ChatbotKnowledgeBasesCard({
  embeddingFilter,
  availableKbs,
  selectedKbIds,
  onToggleKb,
}: ChatbotKnowledgeBasesCardProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">Knowledge Bases</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {embeddingFilter && (
          <p className="text-xs text-gray-500">
            {t('chatbots.onlyEmbeddingShort', { model: embeddingFilter.model_id })}
          </p>
        )}
        {availableKbs.length === 0 && (
          <p className="text-gray-500 text-sm">{t('chatbots.noKbs')}</p>
        )}
        <div className="max-h-60 overflow-y-auto space-y-2">
          {availableKbs.map((kb) => (
            <label
              key={kb.id}
              className="flex items-start gap-3 p-3 border rounded-md hover:bg-gray-50 cursor-pointer"
            >
              <input
                type="checkbox"
                className="mt-0.5"
                checked={selectedKbIds.includes(kb.id)}
                onChange={() => onToggleKb(kb.id)}
              />
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">
                  {kb.name}
                </div>
                <div className="text-xs text-gray-500">
                  {kb.embedding_selection.model_id} ·{' '}
                  {kb.embedding_selection.dim}d
                </div>
              </div>
            </label>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
