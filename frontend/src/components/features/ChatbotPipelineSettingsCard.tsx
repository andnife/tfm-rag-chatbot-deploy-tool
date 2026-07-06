'use client'

import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'

export interface ChatbotPipelineSettingsCardProps {
  topK: number
  onTopKChange: (v: number) => void
  scoreThreshold: number
  onScoreThresholdChange: (v: number) => void
  maxSelfCorrection: number
  onMaxSelfCorrectionChange: (v: number) => void
  enableReranker: boolean
  onEnableRerankerChange: (v: boolean) => void
  abstainWhenInsufficient: boolean
  onAbstainWhenInsufficientChange: (v: boolean) => void
}

/** Retrieval pipeline settings card (top-K, threshold, self-correction, reranker, abstain). */
export function ChatbotPipelineSettingsCard({
  topK,
  onTopKChange,
  scoreThreshold,
  onScoreThresholdChange,
  maxSelfCorrection,
  onMaxSelfCorrectionChange,
  enableReranker,
  onEnableRerankerChange,
  abstainWhenInsufficient,
  onAbstainWhenInsufficientChange,
}: ChatbotPipelineSettingsCardProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t('chatbots.pipeline')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label>Top K: {topK}</Label>
            <input
              type="range"
              min={1}
              max={50}
              step={1}
              value={topK}
              onChange={(e) => onTopKChange(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="space-y-2">
            <Label>
              {t('chatbotNew.scoreThreshold')}: {scoreThreshold.toFixed(2)}
            </Label>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={scoreThreshold}
              onChange={(e) =>
                onScoreThresholdChange(Number(e.target.value))
              }
              className="w-full"
            />
          </div>
          <div className="space-y-2">
            <Label>
              {t('chatbots.maxSelfCorrection')}: {maxSelfCorrection}
            </Label>
            <input
              type="range"
              min={0}
              max={3}
              step={1}
              value={maxSelfCorrection}
              onChange={(e) => onMaxSelfCorrectionChange(Number(e.target.value))}
              className="w-full"
            />
            <p className="text-xs text-gray-500">
              {t('chatbots.maxSelfCorrectionHint')}
            </p>
          </div>
          <div className="space-y-2">
            <Label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={enableReranker}
                onChange={(e) => onEnableRerankerChange(e.target.checked)}
              />
              {t('chatbots.reranker')}
            </Label>
            <p className="text-xs text-gray-500">
              {t('chatbots.rerankerHint')}
            </p>
          </div>
          <div className="space-y-2">
            <Label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={abstainWhenInsufficient}
                onChange={(e) =>
                  onAbstainWhenInsufficientChange(e.target.checked)
                }
              />
              {t('chatbots.abstain')}
            </Label>
            <p className="text-xs text-gray-500">
              {t('chatbots.abstainHint')}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
