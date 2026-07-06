import { useState } from 'react'
import { Loader2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useDatasetList, useDeleteDataset } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { DatasetStatusBadge } from './DatasetStatusBadge'
import { DatasetDetail } from './DatasetDetail'
import { CreateDatasetDialog } from './CreateDatasetDialog'

export function EvalDatasetsTab() {
  const { t } = useTranslation()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const { data: datasets, isLoading, isError } = useDatasetList()
  const deleteDataset = useDeleteDataset()

  // Drill-down: render detail view when a dataset is selected
  if (selectedId) {
    return (
      <DatasetDetail
        datasetId={selectedId}
        onBack={() => setSelectedId(null)}
      />
    )
  }

  const handleDelete = (id: string) => {
    deleteDataset.mutate(id, {
      onSuccess: () => {
        toast.success(t('eval.datasets.deleted'))
        setConfirmDeleteId(null)
      },
      onError: (err) =>
        toast.error(
          err instanceof ApiError ? err.message : t('eval.datasets.errorDelete'),
        ),
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{t('eval.datasets.title')}</h2>
          <p className="text-sm text-muted-foreground">{t('eval.datasets.subtitle')}</p>
        </div>
        <CreateDatasetDialog />
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center gap-2 text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('common.loading')}
        </div>
      )}

      {/* Error */}
      {isError && (
        <p className="text-sm text-danger">{t('eval.datasets.errorLoad')}</p>
      )}

      {/* Empty state */}
      {!isLoading && !isError && datasets?.length === 0 && (
        <div className="rounded-md border border-dashed p-8 text-center">
          <p className="text-sm text-muted-foreground">{t('eval.datasets.empty')}</p>
        </div>
      )}

      {/* Dataset list */}
      {!isLoading && !isError && (datasets ?? []).length > 0 && (
        <div className="space-y-3">
          {datasets!.map((ds) => (
            <Card key={ds.id}>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CardTitle className="text-base">{ds.name}</CardTitle>
                    <DatasetStatusBadge status={ds.status} />
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      onClick={() => setSelectedId(ds.id)}
                    >
                      {t('eval.datasets.manage')}
                    </Button>
                    {confirmDeleteId === ds.id ? (
                      <>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={deleteDataset.isPending}
                          onClick={() => handleDelete(ds.id)}
                        >
                          {deleteDataset.isPending ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            t('common.delete')
                          )}
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setConfirmDeleteId(null)}
                        >
                          {t('common.cancel')}
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setConfirmDeleteId(ds.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4 text-sm text-muted-foreground">
                  {ds.description && <span>{ds.description}</span>}
                  <span>
                    {t('eval.datasets.numRows', { count: ds.num_rows })}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
