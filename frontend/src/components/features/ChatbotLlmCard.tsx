'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { LlmModelSelect } from '@/components/features/LlmModelSelect'
import type { LlmSelection } from '@/types/api'

export interface ChatbotLlmCardProps {
  credentialId: string | null
  model: string
  onChange: (v: LlmSelection) => void
}

/** Main LLM credential+model card of the chatbot edit page. */
export function ChatbotLlmCard({ credentialId, model, onChange }: ChatbotLlmCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">LLM</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <LlmModelSelect credentialId={credentialId} model={model} onChange={onChange} />
      </CardContent>
    </Card>
  )
}
