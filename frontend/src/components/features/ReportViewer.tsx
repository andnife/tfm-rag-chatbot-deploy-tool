'use client'

import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { useEvalReportJson, useEvalReportMarkdown } from '@/lib/queries'
import { RunReportDetail } from './RunReportDetail'
import type { EvalRun, EvalReportJson } from '@/types/api'

interface ReportViewerProps {
  /** null = hidden; non-null string = report name to load and display */
  reportName: string | null
  run?: EvalRun
  mode: 'report' | 'json'
  onClose: () => void
}

export function ReportViewer({ reportName, run, mode, onClose }: ReportViewerProps) {
  const { t } = useTranslation()

  const { data: reportJson } = useEvalReportJson(reportName)
  const { data: reportMd } = useEvalReportMarkdown(reportName)

  if (!reportName) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-lg border border-line bg-canvas p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold">
            {t(mode === 'json' ? 'eval.reports.modalTitleJson' : 'eval.reports.modalTitleReport')}
          </h3>
          <Button variant="ghost" size="sm" onClick={onClose}>
            ✕
          </Button>
        </div>

        {mode === 'json' ? (
          reportJson ? (
            <pre className="overflow-auto whitespace-pre-wrap rounded-md border border-line bg-surface p-4 text-xs text-fg">
              {JSON.stringify(reportJson, null, 2)}
            </pre>
          ) : (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> {t('eval.reports.loading')}
            </div>
          )
        ) : reportJson ? (
          <RunReportDetail
            scenario="__entity__"
            report={reportJson as EvalReportJson}
            run={run}
          />
        ) : reportMd ? (
          <pre className="overflow-auto whitespace-pre-wrap text-sm text-fg">
            {(reportMd as { content: string }).content}
          </pre>
        ) : (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('eval.reports.loading')}
          </div>
        )}
      </div>
    </div>
  )
}
