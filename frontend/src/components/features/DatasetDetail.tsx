import { useState } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { useDataset, useSetDatasetSeed, useProcessDataset } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { DatasetStatusBadge } from './DatasetStatusBadge'
import { DatasetRows } from './DatasetRows'
import { UploadDocumentDialog } from './UploadDocumentDialog'

interface Props {
  datasetId: string
  onBack: () => void
}

export function DatasetDetail({ datasetId, onBack }: Props) {
  const { t } = useTranslation()
  const [sqlSeed, setSqlSeed] = useState('')
  const { data: dataset, isLoading } = useDataset(datasetId)
  const setSeed = useSetDatasetSeed(datasetId)
  const process = useProcessDataset(datasetId)

  const handleSaveSeed = () => {
    setSeed.mutate(sqlSeed, {
      onSuccess: () => toast.success(t('eval.datasets.detail.seedSaved')),
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('eval.datasets.detail.seedError')),
    })
  }

  const handleProcess = () => {
    process.mutate(undefined, {
      onSuccess: () => toast.success(t('eval.datasets.detail.processingStarted')),
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('eval.datasets.detail.processError')),
    })
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('eval.datasets.detail.loading')}
      </div>
    )
  }

  if (!dataset) {
    return <p className="text-sm text-muted-foreground">{t('eval.datasets.detail.notFound')}</p>
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Button variant="outline" size="sm" onClick={onBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          {t('eval.datasets.detail.back')}
        </Button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">{dataset.name}</h2>
            <DatasetStatusBadge status={dataset.status} />
          </div>
          {dataset.status === 'failed' && dataset.status_error && (
            <p className="mt-1 text-sm text-danger">{dataset.status_error}</p>
          )}
          {dataset.db_schema_name && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {t('eval.datasets.detail.schema')}: <span className="font-mono">{dataset.db_schema_name}</span>
            </p>
          )}
        </div>
      </div>

      {/* Documents */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('eval.datasets.detail.documentsTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t('eval.datasets.detail.documentsHint')}</p>
          {dataset.knowledge_base_id ? (
            <UploadDocumentDialog kbId={dataset.knowledge_base_id} />
          ) : (
            <p className="text-xs text-muted-foreground">{t('eval.datasets.detail.noKb')}</p>
          )}
        </CardContent>
      </Card>

      {/* SQL seed */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('eval.datasets.detail.sqlSeedTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Label>{t('eval.datasets.detail.sqlSeedLabel')}</Label>
          <Textarea
            placeholder={t('eval.datasets.detail.sqlSeedPlaceholder')}
            value={sqlSeed}
            onChange={(e) => setSqlSeed(e.target.value)}
            rows={6}
            className="font-mono text-xs"
          />
          <Button
            size="sm"
            onClick={handleSaveSeed}
            disabled={setSeed.isPending || !sqlSeed.trim()}
          >
            {setSeed.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('eval.datasets.detail.saveSeed')}
          </Button>
        </CardContent>
      </Card>

      {/* Process */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('eval.datasets.detail.processTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t('eval.datasets.detail.processHint')}</p>
          <Button
            onClick={handleProcess}
            disabled={process.isPending || dataset.status === 'processing'}
          >
            {(process.isPending || dataset.status === 'processing') && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            {t('eval.datasets.detail.process')}
          </Button>
        </CardContent>
      </Card>

      {/* Rows */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('eval.datasets.detail.rowsTitle')}</CardTitle>
        </CardHeader>
        <CardContent>
          <DatasetRows datasetId={datasetId} />
        </CardContent>
      </Card>
    </div>
  )
}
