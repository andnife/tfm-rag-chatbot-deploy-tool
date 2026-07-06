import { useState } from 'react'
import { ChevronDown, ChevronUp, Coins } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PipelineTrace } from './PipelineTrace'
import { SCENARIO_METRICS, metricLabel } from '@/lib/evalMetrics'
import type { EvalReportJson, EvalRun } from '@/types/api'

export function RunReportDetail({
  scenario, report, baseline, run, metrics: metricsProp,
}: { scenario: string; report: EvalReportJson; baseline?: EvalReportJson; run?: EvalRun; metrics?: string[] }) {
  const { t } = useTranslation()
  const metrics = metricsProp ?? SCENARIO_METRICS[scenario] ?? Object.keys(report.summary.metrics)
  const m = report.summary.metrics
  const std = report.summary.metrics_std ?? {}
  const b = baseline?.summary.metrics ?? {}
  const primaryMetric = metrics[0]
  const [sortKey, setSortKey] = useState<'scoreAsc' | 'scoreDesc' | 'scenario'>('scoreAsc')
  const [scenarioFilter, setScenarioFilter] = useState<string>('__all__')

  const scenarios = Array.from(new Set(report.cases.map((c) => c.scenario)))
  const visibleCases = report.cases
    .filter((c) => scenarioFilter === '__all__' || c.scenario === scenarioFilter)
    .slice()
    .sort((a, z) => {
      if (sortKey === 'scenario') return a.scenario.localeCompare(z.scenario)
      const av = a.scores?.[primaryMetric] ?? Number.POSITIVE_INFINITY
      const zv = z.scores?.[primaryMetric] ?? Number.POSITIVE_INFINITY
      return sortKey === 'scoreAsc' ? av - zv : zv - av
    })

  const hasTokenData = run != null && (
    run.tokens_gen_in != null ||
    run.tokens_gen_out != null ||
    run.tokens_judge_in != null ||
    run.tokens_judge_out != null
  )

  const metaRows: Array<{ label: string; value: string }> = [
    { label: t('eval.report.chatbot'), value: report.chatbot_name ?? '—' },
    {
      label: t('eval.report.dataset'),
      value: report.dataset_path ?? run?.dataset_name ?? '—',
    },
    { label: t('eval.generatorModel'), value: report.generator_model ?? '—' },
    { label: t('eval.judgeModel'), value: report.ragas_judge_model ?? '—' },
  ]
  if (report.scenario_filter) {
    metaRows.push({ label: t('eval.report.scenarioFilter'), value: report.scenario_filter })
  }
  if (report.run_started_at) {
    metaRows.push({
      label: t('eval.report.runStarted'),
      value: new Date(report.run_started_at).toLocaleString(),
    })
  }

  return (
    <div className="space-y-6">
      {/* Metadata header */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{t('eval.report.metadataTitle')}</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
            {metaRows.map((row) => (
              <div key={row.label} className="space-y-0.5">
                <dt className="text-xs text-muted-foreground">{row.label}</dt>
                <dd className="font-medium text-foreground break-words">{row.value}</dd>
              </div>
            ))}
          </dl>
        </CardContent>
      </Card>

      {/* Scorecard */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {metrics.map((k) => {
          const delta = m[k] != null && b[k] != null ? m[k] - b[k] : null
          return (
            <div key={k} className="rounded-lg border border-border bg-surface-2 p-4 text-center space-y-1">
              <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{metricLabel(k)}</div>
              <div className="text-3xl font-bold text-primary">
                {m[k] != null ? m[k].toFixed(2) : '—'}
              </div>
              {std[k] != null && (
                <div className="text-xs text-muted-foreground">± {std[k].toFixed(2)}</div>
              )}
              {delta != null && (
                <div className={`text-xs font-medium ${delta >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                  {delta >= 0 ? '▲ +' : '▼ '}{delta.toFixed(2)} {t('eval.results.vsBaseline')}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Run stats summary */}
      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        <span>
          <span className="font-medium text-foreground">{report.summary.num_cases}</span> {t('eval.report.cases')}
        </span>
        <span>
          <span className="font-medium text-foreground">{report.summary.num_scored}</span> {t('eval.report.scored')}
        </span>
        {report.summary.num_errors > 0 && (
          <span className="text-red-600 dark:text-red-400">
            <span className="font-medium">{report.summary.num_errors}</span> {t('eval.report.errors')}
          </span>
        )}
      </div>

      {/* Token / cost block */}
      {hasTokenData && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Coins className="h-4 w-4 text-muted-foreground" />
              {t('eval.report.tokenCostTitle')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {run!.tokens_gen_in != null && (
                <TokenStat label={t('eval.launch.tokensGenIn')} value={run!.tokens_gen_in.toLocaleString()} />
              )}
              {run!.tokens_gen_out != null && (
                <TokenStat label={t('eval.launch.tokensGenOut')} value={run!.tokens_gen_out.toLocaleString()} />
              )}
              {run!.tokens_judge_in != null && (
                <TokenStat label={t('eval.launch.tokensJudgeIn')} value={run!.tokens_judge_in.toLocaleString()} />
              )}
              {run!.tokens_judge_out != null && (
                <TokenStat label={t('eval.launch.tokensJudgeOut')} value={run!.tokens_judge_out.toLocaleString()} />
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* All cases */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            {t('eval.report.allCasesTitle', { count: visibleCases.length })}
          </h3>
          <div className="flex items-center gap-2 text-xs">
            <select
              className="rounded border border-border bg-surface px-2 py-1"
              value={scenarioFilter}
              onChange={(e) => setScenarioFilter(e.target.value)}
            >
              <option value="__all__">{t('eval.report.filterAllScenarios')}</option>
              {scenarios.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              className="rounded border border-border bg-surface px-2 py-1"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as typeof sortKey)}
            >
              <option value="scoreAsc">{t('eval.report.sortScoreAsc')}</option>
              <option value="scoreDesc">{t('eval.report.sortScoreDesc')}</option>
              <option value="scenario">{t('eval.report.sortScenario')}</option>
            </select>
          </div>
        </div>
        <div className="space-y-2">
          {visibleCases.map((c, i) => <CaseDetail key={i} c={c} metric={primaryMetric} />)}
        </div>
      </div>
    </div>
  )
}

function TokenStat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="rounded-md border border-border p-3 text-center space-y-0.5">
      <div className="text-xs text-muted-foreground leading-tight">{label}</div>
      <div className={`text-base font-semibold ${highlight ? 'text-primary' : 'text-foreground'}`}>{value}</div>
    </div>
  )
}

function CaseDetail({ c, metric }: { c: EvalReportJson['cases'][number]; metric: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const score = c.scores?.[metric]
  return (
    <div className="rounded-lg border border-border">
      <button
        className="flex items-center gap-3 w-full text-left p-4"
        onClick={() => setOpen((v) => !v)}
      >
        <Badge variant={score != null && score < 0.5 ? 'danger' : 'warning'} className="shrink-0 text-xs">
          {score != null ? score.toFixed(2) : '—'}
        </Badge>
        <span className="text-sm font-medium flex-1 text-left leading-snug">{c.question}</span>
        <span className="text-xs text-muted-foreground shrink-0">{c.scenario}</span>
        {open ? <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />}
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-dashed border-border pt-3">
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('eval.report.groundTruth')}</div>
            <div className="text-sm text-foreground leading-relaxed">{c.ground_truth}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('eval.report.predictedAnswer')}</div>
            <div className="text-sm text-foreground leading-relaxed">{c.predicted_answer ?? '—'}</div>
          </div>
          {c.retrieved_contexts.length > 0 && (
            <div className="space-y-1">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t('eval.report.retrievedContexts', { count: c.retrieved_contexts.length })}
              </div>
              <div className="space-y-1">
                {c.retrieved_contexts.map((ctx, j) => (
                  <pre key={j} className="overflow-x-auto rounded bg-muted/40 p-2 text-xs whitespace-pre-wrap">{ctx}</pre>
                ))}
              </div>
            </div>
          )}
          {c.routing_trace && (
            <div className="mt-2">
              <PipelineTrace trace={c.routing_trace} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
