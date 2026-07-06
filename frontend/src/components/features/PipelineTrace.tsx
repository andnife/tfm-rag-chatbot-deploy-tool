import { useTranslation } from 'react-i18next'
import type { RoutingTraceView } from '@/types/api'

const ROUTE_LABEL: Record<string, string> = {
  normal: 'normal', docs: 'docs', sql: 'sql', both: 'docs + sql',
}

const STEP_COLORS: Record<string, string> = {
  info: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200',
  default: 'bg-surface text-fg-muted',
  success: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-200',
  warning: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-200',
  danger: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200',
}

export function PipelineTrace({ trace }: { trace: RoutingTraceView }) {
  const { t } = useTranslation()
  if (!trace || !trace.route) return null

  const steps: Array<{ label: string; sublabel?: string; variant: keyof typeof STEP_COLORS }> = []

  steps.push({
    label: t('eval.report.pipeline.route'),
    sublabel: ROUTE_LABEL[trace.route] ?? trace.route,
    variant: 'info',
  })

  trace.attempts.forEach((a) => {
    if (a.sql) {
      steps.push({
        label: t('eval.report.pipeline.sql'),
        sublabel: `${a.row_count ?? 0} ${t('eval.report.pipeline.rows')}`,
        variant: 'default',
      })
    } else if (a.num_chunks != null) {
      steps.push({
        label: t('eval.report.pipeline.retrieve'),
        sublabel: `${a.num_chunks} chunks`,
        variant: 'default',
      })
    }
  })

  trace.verdicts.forEach((v) => {
    if (v.sufficient) {
      steps.push({ label: t('eval.report.pipeline.gradeSufficient'), variant: 'success' })
    } else if (v.reformulated_query) {
      steps.push({ label: t('eval.report.pipeline.reformulate'), variant: 'warning' })
    } else if (v.abstain_reason) {
      steps.push({ label: t('eval.report.pipeline.abstain'), variant: 'danger' })
    } else {
      steps.push({ label: t('eval.report.pipeline.gradeInsufficient'), variant: 'warning' })
    }
  })

  if (!trace.verdicts.some((v) => v.abstain_reason)) {
    steps.push({ label: t('eval.report.pipeline.synthesize'), variant: 'success' })
  }

  return (
    <div className="rounded-md border border-border bg-muted/40 p-3 space-y-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t('eval.report.pipeline.title')}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {steps.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span className={`inline-flex flex-col items-center rounded px-2 py-1 text-xs font-medium leading-tight ${STEP_COLORS[s.variant]}`}>
              <span>{s.label}</span>
              {s.sublabel && (
                <span className="font-normal opacity-80">{s.sublabel}</span>
              )}
            </span>
            {i < steps.length - 1 && (
              <span className="text-muted-foreground text-sm select-none">→</span>
            )}
          </span>
        ))}
      </div>
      {/* Per-attempt detail */}
      {trace.attempts.length > 0 && (
        <div className="space-y-2">
          {trace.attempts.map((a, i) => (
            <div key={i} className="rounded border border-border bg-surface p-2 text-xs space-y-1">
              <div className="flex items-center gap-2 text-fg-muted">
                <span className="font-medium text-foreground">
                  #{a.index} · {a.tool}
                </span>
                <span>{Math.round(a.latency_ms)} ms</span>
                {a.num_chunks != null && <span>· {a.num_chunks} chunks</span>}
                {a.row_count != null && <span>· {a.row_count} {t('eval.report.pipeline.rows')}</span>}
              </div>
              {a.query && (
                <div>
                  <span className="text-fg-muted">{t('eval.report.pipeline.query')}: </span>
                  <span>{a.query}</span>
                </div>
              )}
              {a.sql && (
                <div className="space-y-1">
                  <div className="text-fg-muted">{t('eval.report.pipeline.sqlQuery')}:</div>
                  <pre className="overflow-x-auto rounded bg-muted/50 p-2 font-mono text-[11px]">{a.sql}</pre>
                </div>
              )}
              {a.result_preview && (
                <div className="space-y-1">
                  <div className="text-fg-muted">{t('eval.report.pipeline.sqlResult')}:</div>
                  <pre className="overflow-x-auto rounded bg-muted/50 p-2 font-mono text-[11px]">{a.result_preview}</pre>
                </div>
              )}
            </div>
          ))}
          {trace.verdicts.map((v, i) => (
            (v.fixed_sql || v.reformulated_query || v.abstain_reason) ? (
              <div key={`v${i}`} className="text-xs text-fg-muted space-y-0.5">
                {v.fixed_sql && (
                  <div><span className="font-medium">{t('eval.report.pipeline.fixedSql')}:</span> <span className="font-mono">{v.fixed_sql}</span></div>
                )}
                {v.reformulated_query && (
                  <div><span className="font-medium">{t('eval.report.pipeline.reformulated')}:</span> {v.reformulated_query}</div>
                )}
                {v.abstain_reason && (
                  <div><span className="font-medium">{t('eval.report.pipeline.abstainReason')}:</span> {v.abstain_reason}</div>
                )}
              </div>
            ) : null
          ))}
        </div>
      )}
      {trace.rationale && (
        <p className="text-xs text-muted-foreground italic leading-relaxed">{trace.rationale}</p>
      )}
    </div>
  )
}
