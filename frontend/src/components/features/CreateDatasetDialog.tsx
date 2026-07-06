import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useCreateDataset } from '@/lib/queries'
import { CredentialModelPicker } from '@/components/features/CredentialModelPicker'
import { ApiError } from '@/lib/api'

const schema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
})

type FormData = z.infer<typeof schema>

interface Props {
  trigger?: React.ReactNode
  onSuccess?: () => void
}

export function CreateDatasetDialog({ trigger, onSuccess }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)

  // Embedding picker state — credential-first
  const [credentialId, setCredentialId] = useState<string | null>(null)
  const [modelId, setModelId] = useState('')
  const [dim, setDim] = useState<number | undefined>(undefined)

  const create = useCreateDataset()

  const form = useForm<FormData>({ resolver: zodResolver(schema) })

  const onSubmit = (data: FormData) => {
    if (!credentialId || !modelId || !dim) {
      toast.error(t('embeddings.configIncomplete'))
      return
    }

    create.mutate(
      {
        name: data.name,
        description: data.description?.trim() || null,
        embedding_selection: {
          credential_id: credentialId,
          model_id: modelId,
          dim,
        },
      },
      {
        onSuccess: () => {
          toast.success(t('eval.datasets.create.created'))
          form.reset()
          setCredentialId(null)
          setModelId('')
          setDim(undefined)
          setOpen(false)
          onSuccess?.()
        },
        onError: (err) =>
          toast.error(
            err instanceof ApiError ? err.message : t('eval.datasets.create.errorCreate'),
          ),
      },
    )
  }

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      form.reset()
      setCredentialId(null)
      setModelId('')
      setDim(undefined)
    }
    setOpen(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? <Button>{t('eval.datasets.new')}</Button>}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('eval.datasets.create.title')}</DialogTitle>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="ds-name">{t('eval.datasets.create.name')}</Label>
            <Input
              id="ds-name"
              placeholder={t('eval.datasets.create.namePlaceholder')}
              {...form.register('name')}
            />
            {form.formState.errors.name && (
              <p className="text-xs text-danger">{t('eval.datasets.create.nameRequired')}</p>
            )}
          </div>

          {/* Description */}
          <div className="space-y-2">
            <Label htmlFor="ds-desc">{t('eval.datasets.create.description')}</Label>
            <Input
              id="ds-desc"
              placeholder={t('eval.datasets.create.descriptionPlaceholder')}
              {...form.register('description')}
            />
          </div>

          {/* Embedding — credential-first picker */}
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

          {/* Actions */}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => handleOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? t('common.creating') : t('eval.datasets.create.submit')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
