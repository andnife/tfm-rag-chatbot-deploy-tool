'use client'

import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'

export interface ChatbotGenerationSettingsCardProps {
  temperature: number
  onTemperatureChange: (v: number) => void
  maxTokens: number
  onMaxTokensChange: (v: number) => void
}

/** Temperature / max-tokens card, inside the "advanced" disclosure. */
export function ChatbotGenerationSettingsCard({
  temperature,
  onTemperatureChange,
  maxTokens,
  onMaxTokensChange,
}: ChatbotGenerationSettingsCardProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t('chatbotNew.temperature')}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>{t('chatbotNew.temperature')}: {temperature.toFixed(2)}</Label>
            <input type="range" min={0} max={2} step={0.1} value={temperature}
              onChange={(e) => onTemperatureChange(Number(e.target.value))} className="w-full" />
          </div>
          <div className="space-y-2">
            <Label>{t('chatbotNew.maxTokens')}: {maxTokens}</Label>
            <input type="range" min={128} max={4096} step={128} value={maxTokens}
              onChange={(e) => onMaxTokensChange(Number(e.target.value))} className="w-full" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
