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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { useCreateCredential, useLlmProviders } from '@/lib/queries'
import { ApiError } from '@/lib/api'

const schema = z.object({
  provider_id: z.string().min(1),
  label: z.string().min(1),
  api_key: z.string().min(1),
  base_url: z.string().optional(),
  max_concurrency: z.string().optional(),
  min_request_interval_seconds: z.string().optional(),
})

type FormData = z.infer<typeof schema>

export function AddCredentialDialog() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const providers = useLlmProviders()
  const create = useCreateCredential()
  const form = useForm<FormData>({ resolver: zodResolver(schema) })

  const onSubmit = (data: FormData) => {
    create.mutate({
      provider_id: data.provider_id,
      label: data.label,
      api_key: data.api_key,
      base_url: data.base_url?.trim() || null,
      max_concurrency: data.max_concurrency?.trim() ? parseInt(data.max_concurrency, 10) : null,
      min_request_interval_seconds: data.min_request_interval_seconds?.trim() ? parseFloat(data.min_request_interval_seconds) : null,
    }, {
      onSuccess: () => {
        toast.success(t('credentials.saved'))
        form.reset()
        setOpen(false)
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.message : t('credentials.errorSave'))
      },
    })
  }

  const tenantProviders = providers.data?.filter(p => p.config_source === 'TENANT_CREDENTIAL') ?? []

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>{t('credentials.addButton')}</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('credentials.addTitle')}</DialogTitle></DialogHeader>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label>{t('credentials.provider')}</Label>
            <Select onValueChange={(v) => form.setValue('provider_id', v, { shouldValidate: true })}>
              <SelectTrigger><SelectValue placeholder={t('credentials.selectProvider')} /></SelectTrigger>
              <SelectContent>
                {tenantProviders.map(p => (
                  <SelectItem key={p.id} value={p.id}>{p.display_name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {form.formState.errors.provider_id && (
              <p className="text-xs text-danger">{t('credentials.validatorProvider')}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="label">{t('credentials.label')}</Label>
            <Input id="label" {...form.register('label')} placeholder={t('credentials.labelPlaceholder')} />
            {form.formState.errors.label && (
              <p className="text-xs text-danger">{t('credentials.validatorLabel')}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="api_key">{t('credentials.apiKey')}</Label>
            <Input id="api_key" type="password" {...form.register('api_key')} />
            {form.formState.errors.api_key && (
              <p className="text-xs text-danger">{t('credentials.validatorApiKey')}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="base_url">{t('credentials.baseUrl')}</Label>
            <Input id="base_url" {...form.register('base_url')} placeholder="https://api.openai.com/v1" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="max_concurrency">{t('credentials.maxConcurrency')}</Label>
            <Input id="max_concurrency" type="number" min={1} {...form.register('max_concurrency')} placeholder={t('credentials.maxConcurrencyPlaceholder')} />
            <p className="text-xs text-fg-muted">{t('credentials.maxConcurrencyHint')}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="min_request_interval_seconds">{t('credentials.minInterval')}</Label>
            <Input id="min_request_interval_seconds" type="number" min={0} step="0.1" {...form.register('min_request_interval_seconds')} placeholder={t('credentials.minIntervalPlaceholder')} />
            <p className="text-xs text-fg-muted">{t('credentials.minIntervalHint')}</p>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? t('common.saving') : t('common.save')}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
