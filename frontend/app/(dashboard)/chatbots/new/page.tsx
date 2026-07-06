'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { WizardSteps } from '@/components/features/WizardSteps'
import { useCreateChatbot, useKnowledgeBases } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { AdvancedSection } from '@/components/features/AdvancedSection'
import {
  EMPTY_ROLE,
  isRoleValid,
  RoleLlmSelect,
  type RoleLlmValue,
} from '@/components/features/RoleLlmSelect'
import { LlmModelSelect } from '@/components/features/LlmModelSelect'
import type { LlmRole, LlmSelection, RoleLlmSelections } from '@/types/api'

const ROLES: LlmRole[] = ['evaluator', 'sql_generator', 'answer_generator']

const DEFAULT_PROMPT = 'Eres un asistente útil, claro y conciso. Responde en el idioma del usuario con un tono profesional y cercano.'

export default function ChatbotCreatePage() {
  const { t } = useTranslation()
  const router = useRouter()
  const kbsQ = useKnowledgeBases()
  const create = useCreateChatbot()

  const STEPS = [t('chatbotNew.steps.info'), t('chatbotNew.steps.kbs'), t('chatbotNew.steps.llm')]

  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [systemPrompt, setSystemPrompt] = useState(DEFAULT_PROMPT)
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([])
  // Credential-first LLM selection — drives both credentialId and model_id together.
  const [llmSel, setLlmSel] = useState<LlmSelection>({ credential_id: '', model_id: '' })
  const [temperature, setTemperature] = useState(0.7)
  const [maxTokens, setMaxTokens] = useState(1024)
  const [topK, setTopK] = useState(5)
  const [scoreThreshold, setScoreThreshold] = useState(0.3)
  const [maxSelfCorrection, setMaxSelfCorrection] = useState(1)
  const [roleSel, setRoleSel] = useState<Record<LlmRole, RoleLlmValue>>({
    evaluator: EMPTY_ROLE,
    sql_generator: EMPTY_ROLE,
    answer_generator: EMPTY_ROLE,
  })

  const firstKb = useMemo(
    () => kbsQ.data?.find(k => k.id === selectedKbIds[0]),
    [kbsQ.data, selectedKbIds],
  )
  const embeddingFilter = firstKb?.embedding_selection
  const availableKbs = kbsQ.data?.filter(k =>
    !embeddingFilter ||
    k.id === selectedKbIds[0] ||
    (k.embedding_selection.credential_id === embeddingFilter.credential_id &&
     k.embedding_selection.model_id === embeddingFilter.model_id),
  ) ?? []

  const toggleKb = (id: string) => {
    setSelectedKbIds(curr => curr.includes(id) ? curr.filter(x => x !== id) : [...curr, id])
  }

  const rolesValid = ROLES.every(role => isRoleValid(roleSel[role]))
  const canNext0 = name.trim().length > 0
  const canNext1 = selectedKbIds.length > 0
  const canCreate = canNext0 && canNext1 && !!llmSel.credential_id && !!llmSel.model_id && rolesValid

  const buildRoleSelections = (): RoleLlmSelections => {
    const out: RoleLlmSelections = {}
    for (const role of ROLES) {
      const v = roleSel[role]
      if (!v.credentialId || !v.modelId) continue
      out[role] = { credential_id: v.credentialId, model_id: v.modelId }
    }
    return out
  }

  const onCreate = () => {
    create.mutate({
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
        enable_reranker: false,
        reranker_initial_top_k: 30,
        abstain_when_insufficient: true,
        generation: { temperature, max_tokens: maxTokens },
      },
    }, {
      onSuccess: (bot) => {
        toast.success(t('chatbotNew.created'))
        router.push(`/chatbots/${bot.id}/playground`)
      },
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('chatbotNew.errorCreate')),
    })
  }

  return (
    <AppShell title={t('chatbotNew.title')}>
      <Card className="max-w-3xl">
        <CardContent className="pt-6">
          <WizardSteps steps={STEPS} current={step} />

          {step === 0 && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">{t('chatbotNew.name')}</Label>
                <Input id="name" value={name} onChange={e => setName(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">{t('chatbotNew.description')}</Label>
                <Textarea id="description" value={description} onChange={e => setDescription(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="sp">{t('chatbotNew.systemPrompt')}</Label>
                <Textarea id="sp" rows={6} value={systemPrompt} onChange={e => setSystemPrompt(e.target.value)} />
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-3">
              {embeddingFilter && (
                <p className="text-xs text-gray-500">
                  {t('chatbots.onlyEmbedding', { model: embeddingFilter.model_id })}
                </p>
              )}
              {availableKbs.length === 0 && <p className="text-gray-500">{t('chatbots.noKbs')}</p>}
              {availableKbs.map(kb => (
                <label key={kb.id} className="flex items-start gap-3 p-3 border rounded-md hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox" className="mt-0.5"
                    checked={selectedKbIds.includes(kb.id)}
                    onChange={() => toggleKb(kb.id)}
                  />
                  <div className="flex-1">
                    <div className="font-medium text-sm">{kb.name}</div>
                    <div className="text-xs text-gray-500">{kb.embedding_selection.model_id} · {kb.embedding_selection.dim}d</div>
                  </div>
                </label>
              ))}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-4">
              <LlmModelSelect
                credentialId={llmSel.credential_id || null}
                model={llmSel.model_id}
                onChange={setLlmSel}
              />
              <AdvancedSection>
              <div className="grid grid-cols-2 gap-4 pt-2">
                <div className="space-y-2">
                  <Label>{t('chatbotNew.temperature')}: {temperature.toFixed(2)}</Label>
                  <input type="range" min={0} max={2} step={0.1} value={temperature} onChange={e => setTemperature(Number(e.target.value))} className="w-full" />
                </div>
                <div className="space-y-2">
                  <Label>{t('chatbotNew.maxTokens')}: {maxTokens}</Label>
                  <input type="range" min={128} max={4096} step={128} value={maxTokens} onChange={e => setMaxTokens(Number(e.target.value))} className="w-full" />
                </div>
                <div className="space-y-2">
                  <Label>{t('chatbotNew.topK')}: {topK}</Label>
                  <input type="range" min={1} max={20} step={1} value={topK} onChange={e => setTopK(Number(e.target.value))} className="w-full" />
                </div>
                <div className="space-y-2">
                  <Label>{t('chatbotNew.scoreThreshold')}: {scoreThreshold.toFixed(2)}</Label>
                  <input type="range" min={0} max={1} step={0.05} value={scoreThreshold} onChange={e => setScoreThreshold(Number(e.target.value))} className="w-full" />
                </div>
                <div className="space-y-2 col-span-2">
                  <Label>{t('chatbots.maxSelfCorrection')}: {maxSelfCorrection}</Label>
                  <input type="range" min={0} max={3} step={1} value={maxSelfCorrection} onChange={e => setMaxSelfCorrection(Number(e.target.value))} className="w-full" />
                  <p className="text-xs text-gray-500">{t('chatbots.maxSelfCorrectionHint')}</p>
                </div>
              </div>
              <div className="space-y-3 pt-4 border-t">
                <div>
                  <Label className="text-sm font-medium">{t('chatbots.rolesTitle')}</Label>
                  <p className="text-xs text-gray-500">{t('chatbots.rolesHint')}</p>
                </div>
                <RoleLlmSelect
                  label={t('chatbots.roleEvaluator')}
                  value={roleSel.evaluator}
                  onChange={(v) => setRoleSel((s) => ({ ...s, evaluator: v }))}
                />
                <RoleLlmSelect
                  label={t('chatbots.roleSqlGenerator')}
                  value={roleSel.sql_generator}
                  onChange={(v) => setRoleSel((s) => ({ ...s, sql_generator: v }))}
                />
                <RoleLlmSelect
                  label={t('chatbots.roleAnswerGenerator')}
                  value={roleSel.answer_generator}
                  onChange={(v) => setRoleSel((s) => ({ ...s, answer_generator: v }))}
                />
              </div>
              </AdvancedSection>
            </div>
          )}

          <div className="flex justify-between mt-6">
            <Button variant="secondary" onClick={() => step === 0 ? router.push('/chatbots') : setStep(step - 1)}>
              {step === 0 ? t('common.cancel') : t('common.prev')}
            </Button>
            {step < 2 ? (
              <Button
                disabled={(step === 0 && !canNext0) || (step === 1 && !canNext1)}
                onClick={() => setStep(step + 1)}
              >{t('common.next')}</Button>
            ) : (
              <Button disabled={!canCreate || create.isPending} onClick={onCreate}>
                {create.isPending ? t('chatbotNew.creating') : t('chatbots.new')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </AppShell>
  )
}
