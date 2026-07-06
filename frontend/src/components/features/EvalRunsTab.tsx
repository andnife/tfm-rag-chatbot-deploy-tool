'use client'

import { useState } from 'react'
import { Loader2, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  useEvalRuns,
  useEvalRunLive,
  useCancelRun,
} from '@/lib/queries'
import { RunLiveProgress } from './RunLiveProgress'
import { LaunchEvalForm } from './LaunchEvalForm'
import { ReportViewer } from './ReportViewer'
import type { EvalRun } from '@/types/api'

// ─── Step strip (live question steps) ────────────────────────────────────────

const STEP_KEYS = ['route', 'retrieve', 'sql', 'grade', 'synthesize'] as const

function StepStrip({ runId }: { runId: string }) {
  const { t } = useTranslation()
  const { data: live } = useEvalRunLive(runId, true)

  if (!live?.steps?.length) return null

  const steps = live.steps

  return (
    <div className="mt-3 space-y-1.5">
      {/* Question progress */}
      {live.index != null && live.total != null && (
        <p className="text-xs font-medium text-fg-muted">
          {t('eval.evaluations.questionProgress', {
            index: live.index,
            total: live.total,
          })}
        </p>
      )}

      {/* Current step label */}
      {live.current_step && (
        <p className="text-xs text-fg-muted">
          <span className="font-medium">{t('eval.evaluations.currentStep')}:</span>{' '}
          {t(`eval.evaluations.step.${live.current_step}` as const, {
            defaultValue: live.current_step,
          })}
        </p>
      )}

      {/* Steps timeline */}
      <div className="flex flex-wrap gap-1.5">
        {steps.map((s, idx) => {
          const isCurrent = s.step === live.current_step
          const elapsedSec = (s.elapsed_ms / 1000).toFixed(1)
          const label = t(`eval.evaluations.step.${s.step}` as const, {
            defaultValue: s.step,
          })
          return (
            <span
              key={idx}
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                isCurrent
                  ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
                  : 'bg-muted text-fg-muted'
              }`}
            >
              {label}
              {isCurrent ? (
                <Loader2 className="h-2.5 w-2.5 animate-spin" />
              ) : (
                <span className="opacity-70">✓ {elapsedSec}s</span>
              )}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// ─── RunCard ──────────────────────────────────────────────────────────────────

interface RunCardProps {
  run: EvalRun
  onViewReport: (run: EvalRun, mode: 'report' | 'json') => void
}

function RunCard({ run, onViewReport }: RunCardProps) {
  const { t } = useTranslation()
  const cancelRun = useCancelRun()
  const [armed, setArmed] = useState(false)

  function handleCancelClick() {
    if (!armed) {
      setArmed(true)
      return
    }
    cancelRun.mutate(run.id)
    setArmed(false)
  }

  // ── queued / running ──────────────────────────────────────────────────────
  if (run.status === 'queued' || run.status === 'running') {
    return (
      <div className="rounded-lg border border-line bg-canvas p-4 space-y-3">
        {/* RunLiveProgress handles its own polling & progress bar */}
        <RunLiveProgress runId={run.id} />

        {/* Live step strip — only for running */}
        {run.status === 'running' && <StepStrip runId={run.id} />}

        {/* Two-click cancel */}
        <div className="flex items-center gap-2 pt-1">
          <Button
            variant={armed ? 'destructive' : 'outline'}
            size="sm"
            onClick={handleCancelClick}
            disabled={cancelRun.isPending}
          >
            {cancelRun.isPending && (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            )}
            {armed
              ? t('eval.evaluations.confirmCancel')
              : t('eval.evaluations.cancel')}
          </Button>
          {armed && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setArmed(false)}
            >
              {t('common.cancel')}
            </Button>
          )}
        </div>
      </div>
    )
  }

  // ── done ──────────────────────────────────────────────────────────────────
  if (run.status === 'done') {
    return (
      <div className="rounded-lg border border-line bg-canvas p-4 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Badge variant="success">{t('eval.statusDone')}</Badge>
            <span className="truncate text-xs text-fg-muted font-mono">
              {run.id.slice(0, 8)}
            </span>
            {run.finished_at && (
              <span className="text-xs text-fg-muted hidden sm:inline">
                · {new Date(run.finished_at).toLocaleString()}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onViewReport(run, 'report')}
            >
              {t('eval.evaluations.viewReport')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onViewReport(run, 'json')}
            >
              {t('eval.evaluations.viewJson')}
            </Button>
          </div>
        </div>
        <p className="text-xs text-fg-muted">
          {t('eval.launch.ranAgainst', {
            chatbot: run.chatbot_name ?? run.chatbot_id.slice(0, 8),
            dataset: run.dataset_name ?? '—',
          })}
        </p>
        <p className="text-xs text-fg-muted">
          {t('eval.generatorModel')}: {run.generator_model ?? '—'} · {t('eval.judgeModel')}: {run.judge_model ?? '—'}
        </p>
      </div>
    )
  }

  // Shared metadata lines (chatbot/dataset + models) so cancelled/failed runs
  // carry the same context as done runs, not just an id.
  const when = run.finished_at ?? run.created_at
  const metaLines = (
    <>
      <p className="text-xs text-fg-muted">
        {t('eval.launch.ranAgainst', {
          chatbot: run.chatbot_name ?? run.chatbot_id.slice(0, 8),
          dataset: run.dataset_name ?? '—',
        })}
      </p>
      <p className="text-xs text-fg-muted">
        {t('eval.generatorModel')}: {run.generator_model ?? '—'} · {t('eval.judgeModel')}: {run.judge_model ?? '—'}
      </p>
    </>
  )

  // ── failed ────────────────────────────────────────────────────────────────
  if (run.status === 'failed') {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Badge variant="danger">{t('eval.statusFailed')}</Badge>
            <span className="truncate text-xs text-fg-muted font-mono">{run.id.slice(0, 8)}</span>
            {when && (
              <span className="text-xs text-fg-muted hidden sm:inline">
                · {new Date(when).toLocaleString()}
              </span>
            )}
          </div>
          {run.report_dir && (
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="outline" size="sm" onClick={() => onViewReport(run, 'report')}>
                {t('eval.evaluations.viewReport')}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => onViewReport(run, 'json')}>
                {t('eval.evaluations.viewJson')}
              </Button>
            </div>
          )}
        </div>
        {metaLines}
        {run.error && (
          <p className="text-xs text-destructive break-all">{run.error}</p>
        )}
      </div>
    )
  }

  // ── cancelled ─────────────────────────────────────────────────────────────
  return (
    <div className="rounded-lg border border-line bg-canvas/60 p-4 space-y-2">
      <div className="flex items-center gap-2 min-w-0">
        <Badge variant="default">{t('eval.evaluations.statusCancelled')}</Badge>
        <span className="truncate text-xs text-fg-muted font-mono">{run.id.slice(0, 8)}</span>
        {when && (
          <span className="text-xs text-fg-muted hidden sm:inline">
            · {new Date(when).toLocaleString()}
          </span>
        )}
      </div>
      {metaLines}
    </div>
  )
}

// ─── Tab ──────────────────────────────────────────────────────────────────────

interface ViewingState {
  run: EvalRun
  mode: 'report' | 'json'
}

export function EvalRunsTab() {
  const { t } = useTranslation()
  const { data: runs = [], refetch } = useEvalRuns()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [viewing, setViewing] = useState<ViewingState | null>(null)

  // Sort newest-first by created_at
  const sorted = [...runs].sort((a, b) => {
    const ta = a.created_at ? new Date(a.created_at).getTime() : 0
    const tb = b.created_at ? new Date(b.created_at).getTime() : 0
    return tb - ta
  })

  function handleLaunched(_runId: string) {
    setDialogOpen(false)
    refetch()
  }

  function handleViewReport(run: EvalRun, mode: 'report' | 'json') {
    setViewing({ run, mode })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-base font-semibold text-foreground">
          {t('eval.evaluations.title')}
        </h2>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => setDialogOpen(true)}>
            <Plus className="mr-1.5 h-4 w-4" />
            {t('eval.evaluations.new')}
          </Button>
        </div>
      </div>

      {/* Nueva evaluación dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('eval.evaluations.new')}</DialogTitle>
          </DialogHeader>
          <LaunchEvalForm onLaunched={handleLaunched} />
        </DialogContent>
      </Dialog>

      {/* Runs list */}
      {sorted.length === 0 ? (
        <p className="text-sm text-fg-muted py-6 text-center">
          {t('eval.evaluations.empty')}
        </p>
      ) : (
        <div className="space-y-3">
          {sorted.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              onViewReport={handleViewReport}
            />
          ))}
        </div>
      )}

      {/* Single tab-level ReportViewer */}
      <ReportViewer
        reportName={viewing?.run.report_dir ?? null}
        run={viewing?.run}
        mode={viewing?.mode ?? 'report'}
        onClose={() => setViewing(null)}
      />
    </div>
  )
}
