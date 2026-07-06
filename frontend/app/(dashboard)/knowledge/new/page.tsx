'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select' // used in AdvancedSection chunking strategy
import { WizardSteps } from '@/components/features/WizardSteps'
import { AdvancedSection } from '@/components/features/AdvancedSection'
import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'
import { useCreateKnowledgeBase } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import type { ChunkingConfig, EmbeddingSelection, ModelRef } from '@/types/api'

export default function KnowledgeCreatePage() {
  const { t } = useTranslation()
  const router = useRouter()
  const create = useCreateKnowledgeBase()
  const [step, setStep] = useState(0)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  // Embedding picker state — credential-first
  const [credentialId, setCredentialId] = useState<string | null>(null)
  const [modelId, setModelId] = useState('')
  const [dim, setDim] = useState<number | undefined>(undefined)
  // Description-model picker state — optional, credential-first
  const [descCredentialId, setDescCredentialId] = useState<string | null>(null)
  const [descModelId, setDescModelId] = useState('')
  const [strategy, setStrategy] = useState<ChunkingConfig['strategy']>('fixed')
  const [chunkSize, setChunkSize] = useState(800)
  const [chunkOverlap, setChunkOverlap] = useState(100)

  const STEPS = [t('knowledge.steps.info'), t('knowledge.steps.embeddings')]

  const canNext0 = name.trim().length > 0
  const canNext1 = !!credentialId && !!modelId && !!dim
  const canCreate = canNext0 && canNext1

  const onCreate = () => {
    if (!credentialId || !modelId || !dim) {
      toast.error(t('embeddings.configIncomplete'))
      return
    }
    const embedding_selection: EmbeddingSelection = {
      credential_id: credentialId,
      model_id: modelId,
      dim,
    }
    const chunking_config: ChunkingConfig = {
      strategy,
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
    }
    const description_llm: ModelRef | null =
      descCredentialId && descModelId
        ? { credential_id: descCredentialId, model_id: descModelId }
        : null
    create.mutate({ name: name.trim(), description: description.trim() || null, embedding_selection, chunking_config, description_llm }, {
      onSuccess: (kb) => {
        toast.success(t('knowledge.created'))
        router.push(`/knowledge/${kb.id}`)
      },
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('knowledge.errorCreate')),
    })
  }

  return (
    <AppShell title={t('knowledge.newTitle')}>
      <Card className="max-w-3xl">
        <CardContent className="pt-6">
          <WizardSteps steps={STEPS} current={step} />

          {step === 0 && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">{t('knowledge.name')}</Label>
                <Input id="name" value={name} onChange={e => setName(e.target.value)} placeholder={t('knowledge.namePlaceholder')} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">{t('knowledge.description')}</Label>
                <Textarea id="description" value={description} onChange={e => setDescription(e.target.value)} />
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-4">
              <CredentialModelPicker
                kind="embedding"
                credentialId={credentialId}
                model={modelId}
                dim={dim}
                onChange={(v) => {
                  setCredentialId(v.credentialId)
                  setModelId(v.model)
                  setDim(v.dim)
                }}
                disabled={create.isPending}
              />
              <AdvancedSection>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>{t('knowledge.descriptionModel.label')}</Label>
                    {(descCredentialId || descModelId) && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => { setDescCredentialId(null); setDescModelId('') }}
                        disabled={create.isPending}
                      >
                        {t('knowledge.descriptionModel.clear')}
                      </Button>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">{t('knowledge.descriptionModel.hint')}</p>
                  <CredentialModelPicker
                    kind="llm"
                    credentialId={descCredentialId}
                    model={descModelId}
                    onChange={(v) => {
                      setDescCredentialId(v.credentialId)
                      setDescModelId(v.model)
                    }}
                    disabled={create.isPending}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{t('kb.settings.strategy')}</Label>
                  <Select value={strategy} onValueChange={(v) => setStrategy(v as ChunkingConfig['strategy'])}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="fixed">fixed — tamaño fijo</SelectItem>
                      <SelectItem value="recursive">recursive — splitter recursivo</SelectItem>
                      <SelectItem value="by_paragraph">by_paragraph — por párrafos</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="chunk_size">{t('knowledge.chunkSize')}: {chunkSize}</Label>
                    <input id="chunk_size" type="range" min={200} max={2000} step={100}
                      value={chunkSize} onChange={e => setChunkSize(Number(e.target.value))} className="w-full" />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="chunk_overlap">{t('knowledge.overlap')}: {chunkOverlap}</Label>
                    <input id="chunk_overlap" type="range" min={0} max={500} step={50}
                      value={chunkOverlap} onChange={e => setChunkOverlap(Number(e.target.value))} className="w-full" />
                  </div>
                </div>
              </AdvancedSection>
            </div>
          )}

          <div className="flex justify-between mt-6">
            <Button variant="secondary" onClick={() => step === 0 ? router.push('/knowledge') : setStep(step - 1)}>
              {step === 0 ? t('common.cancel') : t('common.prev')}
            </Button>
            {step < 1 ? (
              <Button
                disabled={!canNext0}
                onClick={() => setStep(step + 1)}
              >{t('common.next')}</Button>
            ) : (
              <Button disabled={!canCreate || create.isPending} onClick={onCreate}>
                {create.isPending ? t('common.creating') : t('kb.new')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </AppShell>
  )
}
