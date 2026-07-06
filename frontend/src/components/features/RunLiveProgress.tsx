'use client'

import { useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useEvalRun, useEvalRunTrace, useEvalRunLive } from '@/lib/queries'
import { computeRunProgress } from '@/lib/evalProgress'

// ---- Helpers -----------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const variantMap: Record<string, 'default' | 'info' | 'success' | 'danger' | 'warning'> = {
    queued: 'default',
    running: 'info',
    done: 'success',
    failed: 'danger',
    cancelled: 'warning',
  }
  const { t } = useTranslation()
  const labelMap: Record<string, string> = {
    queued:    t('eval.statusQueued'),
    running:   t('eval.statusRunning'),
    done:      t('eval.statusDone'),
    failed:    t('eval.statusFailed'),
    cancelled: t('eval.statusCancelled'),
  }
  return (
    <Badge variant={variantMap[status] ?? 'default'}>
      {labelMap[status] ?? status}
    </Badge>
  )
}

function fmtEta(seconds: number): string {
  return seconds > 60 ? `${Math.round(seconds / 60)}min` : `${Math.round(seconds)}s`
}

function ProgressBar({ value }: { value: number }) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
      <div
        className="h-full rounded-full bg-primary transition-all duration-500"
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}

// ---- Main component ----------------------------------------------------------------

interface Props {
  runId: string
}

export function RunLiveProgress({ runId }: Props) {
  const { t } = useTranslation()

  // Self-terminating poll: starts active=true, stops once run reaches a terminal
  // state. activeRef carries the value across renders so the hook call always
  // receives the latest computed isActive without hoisting issues.
  const activeRef = useRef(true)
  const runQuery = useEvalRun(runId, activeRef.current)
  const run = runQuery.data

  const isActive = !run || run.status === 'queued' || run.status === 'running'
  activeRef.current = isActive

  const traceQuery = useEvalRunTrace(runId, isActive)
  const traceRows = traceQuery.data ?? []

  // Live scoring state (written during the RAGAS scoring phase). Drives the bar
  // once generation is done, since scoring emits no trace rows.
  const live = useEvalRunLive(runId, isActive).data
  const scoringFrac =
    live?.phase === 'scoring' && live.scoring_total
      ? (live.scoring_done ?? 0) / live.scoring_total
      : undefined

  // Latest trace row carries the live stats
  const latestRow = traceRows.length > 0 ? traceRows[traceRows.length - 1] : null

  // Two-phase progress: generation advances the trace (one row per answered
  // case) and maps to 0-90%; RAGAS scoring emits no rows, so we hold at 95%
  // with a distinct "scoring" phase until the run is done — otherwise the bar
  // hits 100% the moment generation ends and looks stuck through scoring.
  const total = latestRow?.total ?? 0
  const answered = traceRows.filter((r) => r.predicted_answer !== null || r.error !== null).length
  const { pct: progressPct, phase } = computeRunProgress(
    answered, total, run?.status ?? 'queued', scoringFrac,
  )

  // A single ETA for the whole run, shown in one place: the scoring-phase
  // estimate while scoring, otherwise the latest generation-row estimate.
  const etaSeconds =
    phase === 'scoring' ? (live?.eta_seconds ?? null) : (latestRow?.eta_seconds ?? null)

  if (runQuery.isLoading) {
    return (
      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('common.loading')}
      </div>
    )
  }

  if (!run) return null

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{t('eval.launch.runTitle')}</CardTitle>
          <div className="flex items-center gap-2">
            <StatusBadge status={run.status} />
            {isActive && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('eval.launch.ranAgainst', {
            chatbot: run.chatbot_name ?? run.chatbot_id.slice(0, 8),
            dataset: run.dataset_name ?? '—',
          })}
        </p>
        <p className="text-xs text-muted-foreground">
          {t('eval.generatorModel')}: {run.generator_model ?? '—'} · {t('eval.judgeModel')}: {run.judge_model ?? '—'}
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress bar */}
        <div className="space-y-1">
          <ProgressBar value={progressPct} />
          <p className="text-xs text-muted-foreground">
            {phase === 'scoring'
              // The total is a rough estimate (faithfulness fans out one judge
              // call per claim), so it can be exceeded — show the live count
              // only, never a misleading "1031/880" fraction.
              ? `${t('eval.launch.scoring')}`
                + (live?.scoring_done != null ? ` (${live.scoring_done})` : '')
              : total > 0
                ? t('eval.launch.progressOf', { answered, total })
                : `${progressPct.toFixed(0)}%`}
          </p>
        </div>

        {/* Live stats from latest trace row */}
        {latestRow && isActive && (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
            {etaSeconds != null && (
              <div>
                <span className="text-xs text-muted-foreground">{t('eval.launch.eta')}</span>
                <p className="font-medium">{fmtEta(etaSeconds)}</p>
              </div>
            )}
            {(latestRow.cumulative_prompt_tokens != null || latestRow.cumulative_completion_tokens != null) && (
              <div>
                <span className="text-xs text-muted-foreground">{t('eval.launch.cumulativeTokens')}</span>
                <p className="font-medium">
                  {(
                    (latestRow.cumulative_prompt_tokens ?? 0) +
                    (latestRow.cumulative_completion_tokens ?? 0)
                  ).toLocaleString()}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Recent answered questions */}
        {traceRows.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">
              {t('eval.launch.recentQuestions')}
            </p>
            <ul className="space-y-1">
              {traceRows
                .slice(-5)
                .reverse()
                .map((row) => (
                  <li
                    key={row.idx}
                    className="flex items-start gap-2 rounded-md bg-muted/40 px-3 py-1.5 text-xs"
                  >
                    <span className="shrink-0 text-muted-foreground">#{row.idx + 1}</span>
                    <span className="truncate">{row.question}</span>
                    {row.judged_correct === true && (
                      <Badge variant="success" className="ml-auto shrink-0">✓</Badge>
                    )}
                    {row.judged_correct === false && (
                      <Badge variant="danger" className="ml-auto shrink-0">✗</Badge>
                    )}
                    {row.error && (
                      <Badge variant="danger" className="ml-auto shrink-0">err</Badge>
                    )}
                  </li>
                ))}
            </ul>
          </div>
        )}

        {/* Final summary on done */}
        {run.status === 'done' && (
          <div className="rounded-md border border-success/30 bg-success-subtle p-4 space-y-3">
            <p className="text-sm font-semibold text-success">{t('eval.launch.runComplete')}</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
              {run.tokens_gen_in != null && (
                <div>
                  <span className="text-xs text-muted-foreground">{t('eval.launch.tokensGenIn')}</span>
                  <p className="font-medium">{run.tokens_gen_in.toLocaleString()}</p>
                </div>
              )}
              {run.tokens_gen_out != null && (
                <div>
                  <span className="text-xs text-muted-foreground">{t('eval.launch.tokensGenOut')}</span>
                  <p className="font-medium">{run.tokens_gen_out.toLocaleString()}</p>
                </div>
              )}
              {run.tokens_judge_in != null && (
                <div>
                  <span className="text-xs text-muted-foreground">{t('eval.launch.tokensJudgeIn')}</span>
                  <p className="font-medium">{run.tokens_judge_in.toLocaleString()}</p>
                </div>
              )}
              {run.tokens_judge_out != null && (
                <div>
                  <span className="text-xs text-muted-foreground">{t('eval.launch.tokensJudgeOut')}</span>
                  <p className="font-medium">{run.tokens_judge_out.toLocaleString()}</p>
                </div>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{t('eval.launch.viewResultsHint')}</p>
          </div>
        )}

        {/* Error state */}
        {run.status === 'failed' && run.error && (
          <div className="rounded-md border border-accent-border bg-accent-subtle px-3 py-2 text-xs text-accent">
            {run.error}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
