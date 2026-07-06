import { useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import {
  useOllamaModels,
  useReindexAll,
  useUpdateKnowledgeBase,
} from '@/lib/queries'
import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'
import { ApiError } from '@/lib/api'
import type { KnowledgeBaseOut, ModelRef, OllamaModel, ReindexAllOut, UpdateKbOut } from '@/types/api'
import { AlertTriangle, RefreshCw, Settings, Zap } from 'lucide-react'

interface Props {
  kb: KnowledgeBaseOut
  onSuccess?: () => void
}

export function KBConfigPanel({ kb, onSuccess }: Props) {
  const { t } = useTranslation()
  const ollamaModels = useOllamaModels()
  const updateKb = useUpdateKnowledgeBase(kb.id)
  const reindexAll = useReindexAll(kb.id)

  const [editOpen, setEditOpen] = useState(false)
  const [reindexConfirmOpen, setReindexConfirmOpen] = useState(false)
  const [reindexConfirmText, setReindexConfirmText] = useState('')

  // Edit embedding state — credential-first
  const [credentialId, setCredentialId] = useState<string | null>(kb.embedding_selection?.credential_id ?? null)
  const [modelId, setModelId] = useState(kb.embedding_selection?.model_id ?? '')
  const [dim, setDim] = useState<number | undefined>(kb.embedding_selection?.dim ?? undefined)

  // Edit description-model state — optional, credential-first
  const [descCredentialId, setDescCredentialId] = useState<string | null>(kb.description_llm?.credential_id ?? null)
  const [descModelId, setDescModelId] = useState(kb.description_llm?.model_id ?? '')

  // Check if a model is actually available in Ollama
  const isModelAvailable = (modelId: string): boolean => {
    if (!ollamaModels.data) return true // Unknown, assume available
    return ollamaModels.data.models.some((m: OllamaModel) => m.name.startsWith(modelId))
  }

  const currentEmb = kb.embedding_selection
  const currentModelAvailable = currentEmb ? isModelAvailable(currentEmb.model_id) : false

  const handleSaveEmbedding = () => {
    if (!credentialId || !modelId || !dim) {
      toast.error(t('embeddings.configIncomplete'))
      return
    }
    const description_llm: ModelRef | null =
      descCredentialId && descModelId
        ? { credential_id: descCredentialId, model_id: descModelId }
        : null
    updateKb.mutate(
      {
        embedding_selection: { credential_id: credentialId, model_id: modelId, dim },
        description_llm,
      },
      {
        onSuccess: (res: UpdateKbOut) => {
          toast.success(t('embeddings.configUpdated'))
          setEditOpen(false)
          if (res.reindex_required) {
            // Cambiar el modelo invalida los vectores existentes: en vez de
            // pedir al usuario que reindexe a mano, lo relanzamos automáticamente
            // avisándole. (Cambiar size/overlap no marca reindex_required.)
            toast.info(t('embeddings.reindexAuto'))
            reindexAll.mutate(undefined, {
              onSuccess: (r: ReindexAllOut) => {
                toast.success(t('reindex.started', { count: r.source_count }))
                onSuccess?.()
              },
              onError: (err: unknown) =>
                toast.error(err instanceof ApiError ? err.message : t('reindex.errorReindex')),
            })
          } else {
            onSuccess?.()
          }
        },
        onError: (err: unknown) => toast.error(err instanceof ApiError ? err.message : t('embeddings.errorUpdate')),
      },
    )
  }

  const handleReindexAll = () => {
    reindexAll.mutate(undefined, {
      onSuccess: (res: ReindexAllOut) => {
        toast.success(t('reindex.started', { count: res.source_count }))
        setReindexConfirmOpen(false)
        setReindexConfirmText('')
        onSuccess?.()
      },
      onError: (err: unknown) => toast.error(err instanceof ApiError ? err.message : t('reindex.errorReindex')),
    })
  }

  return (
    <div className="space-y-6">
      {/* Current Embedding Config */}
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
              <Zap className="h-4 w-4" /> {t('embeddings.title')}
            </h3>
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              <Settings className="h-3 w-3 mr-1" /> {t('common.edit')}
            </Button>
          </div>

          {currentEmb ? (
            <div className="space-y-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="text-gray-500">{t('embeddings.model')}:</span>
                <code className="bg-gray-100 px-2 py-0.5 rounded text-xs font-mono">
                  {currentEmb.model_id}
                </code>
                {!currentModelAvailable && ollamaModels.data && (
                  <Badge variant="destructive" className="text-xs">{t('embeddings.notAvailable')}</Badge>
                )}
                {currentModelAvailable && ollamaModels.data && (
                  <Badge variant="default" className="text-xs border border-success/30 bg-success-subtle text-success">{t('embeddings.available')}</Badge>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-gray-500">{t('embeddings.dimensions')}:</span>
                <span>{currentEmb.dim}d</span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-500">{t('embeddings.unconfigured')}</p>
          )}

          {!currentModelAvailable && ollamaModels.data && currentEmb && (
            <div className="mt-4 border border-warning/30 bg-warning-subtle rounded-md p-3 text-sm text-warning">
              <AlertTriangle className="h-4 w-4 inline mr-1" />
              {t('embeddings.modelUnavailable', { model: currentEmb.model_id })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Reindex All */}
      {currentEmb && (
        <Card>
          <CardContent className="p-6">
            <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2 mb-4">
              <RefreshCw className="h-4 w-4" /> {t('reindex.title')}
            </h3>
            <p className="text-sm text-gray-600 mb-4">
              {t('reindex.description')}
            </p>
            <Button
              variant="outline"
              onClick={() => setReindexConfirmOpen(true)}
              disabled={!currentModelAvailable}
            >
              <RefreshCw className="h-4 w-4 mr-1" /> {t('reindex.button')}
            </Button>
            {!currentModelAvailable && ollamaModels.data && (
              <p className="text-xs text-amber-600 mt-2">
                {t('reindex.cannotReindex')}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Edit Embedding Dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('embeddings.configure')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-gray-600">
              {t('embeddings.changeNote')}
            </p>
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
              disabled={updateKb.isPending}
            />
            <div className="space-y-1 pt-2 border-t">
              <div className="flex items-center justify-between">
                <Label>{t('knowledge.descriptionModel.label')}</Label>
                {(descCredentialId || descModelId) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => { setDescCredentialId(null); setDescModelId('') }}
                    disabled={updateKb.isPending}
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
                disabled={updateKb.isPending}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditOpen(false)}>{t('common.cancel')}</Button>
              <Button onClick={handleSaveEmbedding} disabled={updateKb.isPending}>
                {updateKb.isPending ? t('common.saving') : t('common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Reindex Confirmation Dialog */}
      <Dialog open={reindexConfirmOpen} onOpenChange={setReindexConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-600">
              <AlertTriangle className="h-5 w-5" /> {t('reindex.confirmTitle')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="border border-warning/30 bg-warning-subtle rounded-md p-4 text-sm text-warning">
              <p className="font-semibold mb-2">{t('reindex.confirmQuestion')}</p>
              <ul className="list-disc list-inside space-y-1 text-xs">
                <li>{t('reindex.confirmBullet1')}</li>
                <li>{t('reindex.confirmBullet2', { count: reindexAll.data?.source_count ?? '...' })}</li>
                <li>{t('reindex.confirmBullet3')}</li>
                <li>{t('reindex.confirmBullet4')}</li>
              </ul>
            </div>
            <div className="space-y-2">
              <Label>{t('reindex.confirmLabel')}</Label>
              <input
                type="text"
                className="w-full border rounded-md px-3 py-2 text-sm"
                placeholder={t('reindex.confirmPlaceholder')}
                value={reindexConfirmText}
                onChange={(e) => setReindexConfirmText(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => { setReindexConfirmOpen(false); setReindexConfirmText('') }}>
                {t('common.cancel')}
              </Button>
              <Button
                variant="destructive"
                disabled={reindexConfirmText !== t('reindex.confirmWord') || reindexAll.isPending}
                onClick={handleReindexAll}
              >
                {reindexAll.isPending ? t('reindex.reindexing') : t('reindex.button')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
