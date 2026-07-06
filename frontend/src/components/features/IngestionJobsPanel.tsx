import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, X, Check, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useIngestionStore, type TrackedJob } from '@/lib/ingestionStore'
import { apiFetch } from '@/lib/api'
import { barPosition, stageLabelKey } from '@/lib/ingestionProgress'
import type { IngestionJobOut } from '@/types/api'

const TERMINAL: TrackedJob['status'][] = ['done', 'failed']

function statusIcon(s: TrackedJob['status']) {
  switch (s) {
    case 'done':
      return <Check className="h-4 w-4 text-success" />
    case 'failed':
      return <AlertCircle className="h-4 w-4 text-danger" />
    case 'running':
    case 'queued':
    case 'pending':
    case 'not_started':
      return <Loader2 className="h-4 w-4 animate-spin text-primary-600" />
  }
}

export function IngestionJobsPanel() {
  const { t } = useTranslation()
  const { jobs, open, update, remove, setOpen } = useIngestionStore()
  const activeJobs = Object.values(jobs).sort((a, b) => b.startedAt - a.startedAt)

  // Poll every 2s for any non-terminal job
  useEffect(() => {
    const nonTerminal = activeJobs.filter((j) => !TERMINAL.includes(j.status))
    if (nonTerminal.length === 0) return
    const interval = setInterval(async () => {
      for (const j of nonTerminal) {
        try {
          const fresh = await apiFetch<IngestionJobOut>(`/ingestion-jobs/${j.jobId}`)
          update(j.jobId, {
            status: fresh.status as TrackedJob['status'],
            progress: fresh.progress,
            stage: fresh.stage,
            itemsDone: fresh.items_done,
            itemsTotal: fresh.items_total,
            error: fresh.error,
          })
        } catch {
          // swallow — leave job as-is
        }
      }
    }, 2000)
    return () => clearInterval(interval)
  }, [activeJobs, update])

  // Auto-remove terminal jobs 8s after they finish
  useEffect(() => {
    const terminal = activeJobs.filter((j) => TERMINAL.includes(j.status))
    if (terminal.length === 0) return
    const timers = terminal.map((j) =>
      setTimeout(() => remove(j.jobId), 8000),
    )
    return () => timers.forEach((tm) => clearTimeout(tm))
  }, [activeJobs, remove])

  if (activeJobs.length === 0) return null

  const runningCount = activeJobs.filter((j) => !TERMINAL.includes(j.status)).length

  return (
    <div className="fixed bottom-4 right-4 z-50 w-80 rounded-lg border border-line bg-canvas shadow-lg">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 border-b border-line hover:bg-surface rounded-t-lg"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-fg">
            {t('ingestion.title')}
          </span>
          {runningCount > 0 && (
            <span className="text-xs text-fg-muted">({runningCount} en curso)</span>
          )}
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-fg-muted" />
        ) : (
          <ChevronUp className="h-4 w-4 text-fg-muted" />
        )}
      </button>
      {open && (
        <div className="max-h-72 overflow-y-auto divide-y divide-line">
          {activeJobs.map((j) => (
            <div key={j.jobId} className="p-3">
              <div className="flex items-start gap-2">
                <div className="mt-0.5">{statusIcon(j.status)}</div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate" title={j.filename}>
                    {j.filename}
                  </p>
                  <p className="text-[10px] text-fg-muted tracking-wide">
                    {t(stageLabelKey(j.stage ?? null))}
                    {j.stage === 'embedding' && j.itemsTotal
                      ? ` · ${t('ingestion.chunks', { done: j.itemsDone ?? 0, total: j.itemsTotal })}`
                      : ''}
                  </p>
                  {!TERMINAL.includes(j.status) && (
                    <div className="w-full bg-surface rounded-full h-1.5 mt-1.5 overflow-hidden">
                      <div
                        className="bg-primary-600 h-1.5 rounded-full transition-all"
                        style={{
                          width: `${barPosition(
                            (j.stage ?? null) as Parameters<typeof barPosition>[0],
                            j.itemsTotal ? (j.itemsDone ?? 0) / j.itemsTotal : 0,
                          )}%`,
                        }}
                      />
                    </div>
                  )}
                  {j.status === 'failed' && j.error && (
                    <p className="text-[10px] text-danger mt-1">{j.error}</p>
                  )}
                </div>
                {TERMINAL.includes(j.status) && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={() => remove(j.jobId)}
                    title={t('ingestion.remove')}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
