import { useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { useDatasetRows, useImportDatasetRows } from '@/lib/queries'
import { ApiError } from '@/lib/api'

interface Props {
  datasetId: string
}

export function DatasetRows({ datasetId }: Props) {
  const { t } = useTranslation()
  const [expandedRow, setExpandedRow] = useState<number | null>(null)
  const [jsonl, setJsonl] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data: rows = [], isLoading } = useDatasetRows(datasetId)
  const importRows = useImportDatasetRows(datasetId)

  const handleImport = () => {
    if (!jsonl.trim()) return
    importRows.mutate(jsonl, {
      onSuccess: (dataset) => {
        toast.success(t('eval.datasets.rows.importSuccess', { count: dataset.num_rows }))
        setJsonl('')
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.message : t('eval.datasets.rows.importError'))
      },
    })
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      setJsonl((ev.target?.result as string) ?? '')
    }
    reader.readAsText(file)
    // Reset input so the same file can be re-selected
    e.target.value = ''
  }

  return (
    <div className="space-y-4">
      {/* Row list */}
      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('eval.datasets.rows.loading')}
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('eval.datasets.rows.empty')}</p>
      ) : (
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">
            {t('eval.datasets.rows.count', { count: rows.length })}
          </div>
          {rows.map((row, idx) => (
            <div
              key={idx}
              className={cn(
                'rounded-md border transition-colors',
                expandedRow === idx && 'border-primary',
              )}
            >
              <button
                type="button"
                onClick={() => setExpandedRow(expandedRow === idx ? null : idx)}
                className="flex w-full items-center gap-2 p-3 text-left text-sm"
              >
                <span className="flex-1 truncate">{row.question}</span>
                <Badge variant="info" className="shrink-0 text-xs">
                  {row.scenario}
                </Badge>
                {row.complexity && (
                  <Badge variant="warning" className="shrink-0 text-xs">
                    {row.complexity}
                  </Badge>
                )}
                {expandedRow === idx ? (
                  <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                )}
              </button>
              {expandedRow === idx && (
                <div className="space-y-2 border-t p-3 text-sm">
                  <div>
                    <div className="text-xs font-medium text-muted-foreground">
                      {t('eval.datasets.rows.groundTruth')}
                    </div>
                    <p className="whitespace-pre-wrap">{row.ground_truth || '—'}</p>
                  </div>
                  {row.source_doc && (
                    <div className="text-xs text-muted-foreground">
                      {t('eval.datasets.rows.sourceDoc')}: {row.source_doc}
                    </div>
                  )}
                  {row.sql_reference && (
                    <div>
                      <div className="text-xs font-medium text-muted-foreground">
                        {t('eval.datasets.rows.sqlReference')}
                      </div>
                      <pre className="mt-0.5 overflow-x-auto rounded bg-muted px-2 py-1 text-xs">
                        {row.sql_reference}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* JSONL import */}
      <div className="space-y-2 rounded-md border p-4">
        <Label className="text-sm font-medium">{t('eval.datasets.rows.importLabel')}</Label>
        <Textarea
          placeholder={t('eval.datasets.rows.importPlaceholder')}
          value={jsonl}
          onChange={(e) => setJsonl(e.target.value)}
          rows={5}
          className="font-mono text-xs"
        />
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={handleImport}
            disabled={importRows.isPending || !jsonl.trim()}
          >
            {importRows.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {t('eval.datasets.rows.importButton')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
          >
            {t('eval.datasets.rows.loadFile')}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".jsonl,.json"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>
      </div>
    </div>
  )
}
