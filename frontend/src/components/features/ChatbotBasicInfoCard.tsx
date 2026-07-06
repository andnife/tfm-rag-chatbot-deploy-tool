'use client'

import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export interface ChatbotBasicInfoCardProps {
  name: string
  onNameChange: (v: string) => void
  description: string
  onDescriptionChange: (v: string) => void
  systemPrompt: string
  onSystemPromptChange: (v: string) => void
}

/** Name / description / system prompt card of the chatbot edit page. */
export function ChatbotBasicInfoCard({
  name,
  onNameChange,
  description,
  onDescriptionChange,
  systemPrompt,
  onSystemPromptChange,
}: ChatbotBasicInfoCardProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t('chatbots.basicInfo')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="name">{t('chatbotNew.name')}</Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => onNameChange(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="description">{t('chatbotNew.description')}</Label>
          <Textarea
            id="description"
            value={description}
            onChange={(e) => onDescriptionChange(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="sp">{t('chatbotNew.systemPrompt')}</Label>
          <Textarea
            id="sp"
            rows={10}
            value={systemPrompt}
            onChange={(e) => onSystemPromptChange(e.target.value)}
            className="font-mono text-xs"
          />
          <p className="text-xs text-gray-500">
            {t('chatbots.systemPromptHint')}
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
