'use client'

import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { RoleLlmSelect, type RoleLlmValue } from '@/components/features/RoleLlmSelect'

export interface ChatbotRolesCardProps {
  evaluator: RoleLlmValue
  onEvaluatorChange: (v: RoleLlmValue) => void
  sqlGenerator: RoleLlmValue
  onSqlGeneratorChange: (v: RoleLlmValue) => void
  answerGenerator: RoleLlmValue
  onAnswerGeneratorChange: (v: RoleLlmValue) => void
}

/** Per-role LLM override card (evaluator / sql_generator / answer_generator). */
export function ChatbotRolesCard({
  evaluator,
  onEvaluatorChange,
  sqlGenerator,
  onSqlGeneratorChange,
  answerGenerator,
  onAnswerGeneratorChange,
}: ChatbotRolesCardProps) {
  const { t } = useTranslation()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t('chatbots.rolesTitle')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-gray-500">{t('chatbots.rolesHint')}</p>
        <RoleLlmSelect
          label={t('chatbots.roleEvaluator')}
          value={evaluator}
          onChange={onEvaluatorChange}
        />
        <RoleLlmSelect
          label={t('chatbots.roleSqlGenerator')}
          value={sqlGenerator}
          onChange={onSqlGeneratorChange}
        />
        <RoleLlmSelect
          label={t('chatbots.roleAnswerGenerator')}
          value={answerGenerator}
          onChange={onAnswerGeneratorChange}
        />
      </CardContent>
    </Card>
  )
}
