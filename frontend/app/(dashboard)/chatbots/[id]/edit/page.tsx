'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Save } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import {
  useChatbot,
  useKnowledgeBases,
  useUpdateChatbot,
} from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { AdvancedSection } from '@/components/features/AdvancedSection'
import { EMPTY_ROLE, isRoleValid, type RoleLlmValue } from '@/components/features/RoleLlmSelect'
import { ChatbotBasicInfoCard } from '@/components/features/ChatbotBasicInfoCard'
import { ChatbotLlmCard } from '@/components/features/ChatbotLlmCard'
import { ChatbotKnowledgeBasesCard } from '@/components/features/ChatbotKnowledgeBasesCard'
import { ChatbotGenerationSettingsCard } from '@/components/features/ChatbotGenerationSettingsCard'
import { ChatbotPipelineSettingsCard } from '@/components/features/ChatbotPipelineSettingsCard'
import { ChatbotRolesCard } from '@/components/features/ChatbotRolesCard'
import type { ChatbotIn, LlmRole, LlmSelection, RoleLlmSelections } from '@/types/api'

const ROLES: LlmRole[] = ['evaluator', 'sql_generator', 'answer_generator']

export default function ChatbotEditPage() {
  const { t } = useTranslation()
  const params = useParams<{ id: string }>()
  const id = params.id ?? ''
  const router = useRouter()
  const { data: bot, isLoading } = useChatbot(id)
  const kbsQ = useKnowledgeBases()
  const update = useUpdateChatbot(id)

  // Local state — initialized from `bot` once loaded.
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([])
  // Credential-first LLM selection — credentialId and model_id driven together.
  const [llmSel, setLlmSel] = useState<LlmSelection>({ credential_id: '', model_id: '' })
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(1024)
  const [topK, setTopK] = useState(5)
  const [scoreThreshold, setScoreThreshold] = useState(0.0)
  const [maxSelfCorrection, setMaxSelfCorrection] = useState(1)
  const [enableReranker, setEnableReranker] = useState(false)
  const [abstainWhenInsufficient, setAbstainWhenInsufficient] = useState(true)
  const [roleSel, setRoleSel] = useState<Record<LlmRole, RoleLlmValue>>({
    evaluator: EMPTY_ROLE,
    sql_generator: EMPTY_ROLE,
    answer_generator: EMPTY_ROLE,
  })

  useEffect(() => {
    if (!bot) return
    setName(bot.name)
    setDescription(bot.description ?? '')
    setSystemPrompt(bot.system_prompt)
    setSelectedKbIds(bot.kb_ids)
    // Initialize credentialId from the stored llm_selection.credential_id.
    setLlmSel({
      credential_id: bot.llm_selection.credential_id,
      model_id: bot.llm_selection.model_id,
    })
    const p = bot.pipeline_config
    setTopK(p.top_k)
    setScoreThreshold(p.score_threshold)
    setMaxSelfCorrection(p.max_self_correction_retries)
    setEnableReranker(p.enable_reranker)
    setAbstainWhenInsufficient(p.abstain_when_insufficient)
    setTemperature(p.generation?.temperature ?? 0.7)
    setMaxTokens(p.generation?.max_tokens ?? 1024)
    // Initialize each role's credentialId from the stored role_llm_selections.
    const r = bot.role_llm_selections ?? {}
    setRoleSel({
      evaluator: r.evaluator
        ? { credentialId: r.evaluator.credential_id, modelId: r.evaluator.model_id }
        : EMPTY_ROLE,
      sql_generator: r.sql_generator
        ? { credentialId: r.sql_generator.credential_id, modelId: r.sql_generator.model_id }
        : EMPTY_ROLE,
      answer_generator: r.answer_generator
        ? { credentialId: r.answer_generator.credential_id, modelId: r.answer_generator.model_id }
        : EMPTY_ROLE,
    })
  }, [bot])

  const firstKb = useMemo(
    () => kbsQ.data?.find((k) => k.id === selectedKbIds[0]),
    [kbsQ.data, selectedKbIds],
  )
  const embeddingFilter = firstKb?.embedding_selection
  const availableKbs =
    kbsQ.data?.filter(
      (k) =>
        !embeddingFilter ||
        k.id === selectedKbIds[0] ||
        (k.embedding_selection.credential_id === embeddingFilter.credential_id &&
          k.embedding_selection.model_id === embeddingFilter.model_id),
    ) ?? []

  const toggleKb = (kbId: string) => {
    setSelectedKbIds((curr) =>
      curr.includes(kbId) ? curr.filter((x) => x !== kbId) : [...curr, kbId],
    )
  }

  const rolesValid = ROLES.every((role) => isRoleValid(roleSel[role]))

  const canSave =
    !!name.trim() &&
    !!llmSel.credential_id &&
    !!llmSel.model_id &&
    selectedKbIds.length > 0 &&
    rolesValid

  const buildRoleSelections = (): RoleLlmSelections => {
    const out: RoleLlmSelections = {}
    for (const role of ROLES) {
      const v = roleSel[role]
      if (!v.credentialId || !v.modelId) continue
      out[role] = { credential_id: v.credentialId, model_id: v.modelId }
    }
    return out
  }

  const onSave = () => {
    const payload: Partial<ChatbotIn> = {
      name: name.trim(),
      description: description.trim() || null,
      system_prompt: systemPrompt,
      llm_selection: llmSel,
      role_llm_selections: buildRoleSelections(),
      kb_ids: selectedKbIds,
      pipeline_config: {
        top_k: topK,
        score_threshold: scoreThreshold,
        max_self_correction_retries: maxSelfCorrection,
        enable_reranker: enableReranker,
        reranker_initial_top_k: 30,
        abstain_when_insufficient: abstainWhenInsufficient,
        generation: { temperature, max_tokens: maxTokens },
      },
    }
    update.mutate(payload, {
      onSuccess: () => {
        toast.success(t('chatbots.updated'))
      },
      onError: (err) =>
        toast.error(
          err instanceof ApiError ? err.message : t('chatbots.errorUpdate'),
        ),
    })
  }

  if (isLoading || !bot) {
    return (
      <AppShell title={t('chatbots.loading')}>
        <p className="text-gray-500">…</p>
      </AppShell>
    )
  }

  return (
    <AppShell title={`${t('common.edit')} · ${bot.name}`}>
      <div className="mb-4 flex items-center justify-between">
        <Link
          href="/chatbots"
          className="text-sm text-primary-600 hover:underline inline-flex items-center"
        >
          <ArrowLeft className="h-4 w-4 mr-1" /> {t('common.back')}
        </Link>
        <div className="flex gap-2">
          <Link href={`/chatbots/${id}/playground`}>
            <Button variant="secondary">{t('chatbots.test')}</Button>
          </Link>
          <Link href={`/chatbots/${id}/widget`}>
            <Button variant="secondary">{t('chatbots.widget')}</Button>
          </Link>
          <Link href={`/chatbots/${id}/sessions`}>
            <Button variant="secondary">{t('chatbots.sessions')}</Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 max-w-6xl">
        <ChatbotBasicInfoCard
          name={name}
          onNameChange={setName}
          description={description}
          onDescriptionChange={setDescription}
          systemPrompt={systemPrompt}
          onSystemPromptChange={setSystemPrompt}
        />

        <ChatbotLlmCard
          credentialId={llmSel.credential_id || null}
          model={llmSel.model_id}
          onChange={setLlmSel}
        />

        <ChatbotKnowledgeBasesCard
          embeddingFilter={embeddingFilter}
          availableKbs={availableKbs}
          selectedKbIds={selectedKbIds}
          onToggleKb={toggleKb}
        />
      </div>

      <div className="mt-6 max-w-6xl">
        <AdvancedSection>
          <ChatbotGenerationSettingsCard
            temperature={temperature}
            onTemperatureChange={setTemperature}
            maxTokens={maxTokens}
            onMaxTokensChange={setMaxTokens}
          />

          <ChatbotPipelineSettingsCard
            topK={topK}
            onTopKChange={setTopK}
            scoreThreshold={scoreThreshold}
            onScoreThresholdChange={setScoreThreshold}
            maxSelfCorrection={maxSelfCorrection}
            onMaxSelfCorrectionChange={setMaxSelfCorrection}
            enableReranker={enableReranker}
            onEnableRerankerChange={setEnableReranker}
            abstainWhenInsufficient={abstainWhenInsufficient}
            onAbstainWhenInsufficientChange={setAbstainWhenInsufficient}
          />

          <ChatbotRolesCard
            evaluator={roleSel.evaluator}
            onEvaluatorChange={(v) => setRoleSel((s) => ({ ...s, evaluator: v }))}
            sqlGenerator={roleSel.sql_generator}
            onSqlGeneratorChange={(v) => setRoleSel((s) => ({ ...s, sql_generator: v }))}
            answerGenerator={roleSel.answer_generator}
            onAnswerGeneratorChange={(v) => setRoleSel((s) => ({ ...s, answer_generator: v }))}
          />
        </AdvancedSection>
      </div>

      <div className="mt-6 flex justify-end gap-2 max-w-6xl">
        <Button variant="secondary" onClick={() => router.push('/chatbots')}>
          {t('common.cancel')}
        </Button>
        <Button onClick={onSave} disabled={!canSave || update.isPending}>
          <Save className="h-4 w-4 mr-1" />
          {update.isPending ? t('common.saving') : t('chatbots.saveChanges')}
        </Button>
      </div>
    </AppShell>
  )
}
