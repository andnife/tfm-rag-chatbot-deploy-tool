export type RunPhase = 'idle' | 'generating' | 'scoring' | 'done' | 'failed' | 'cancelled'

export interface RunProgress {
  pct: number
  phase: RunPhase
}


/**
 * Two-phase progress for an eval run.
 *
 * An eval run has two sequential phases: (1) generating an answer per case,
 * then (2) scoring the whole batch with RAGAS in one shot. The trace only
 * advances during generation (one row per answered case), so a naive
 * `answered / total` hits 100% the moment generation finishes and then sits
 * there — looking finished/stuck — for the entire scoring phase.
 *
 * We map generation to 0–90% of the bar and hold at 95% during scoring, only
 * reaching 100% when the run is actually done.
 */
export function computeRunProgress(
  answered: number,
  total: number,
  status: string,
  scoringFrac?: number,
): RunProgress {
  if (status === 'done') return { pct: 100, phase: 'done' }
  // Terminal-but-not-done: the run stopped (crashed or was cancelled) without
  // ever reaching scoring. Freeze the bar at wherever generation got to
  // instead of falling into the generating/scoring branches below, which
  // would otherwise show a "scoring 95%" bar for a run that isn't running.
  if (status === 'failed' || status === 'cancelled') {
    return { pct: total > 0 ? (answered / total) * 100 : 0, phase: status }
  }
  if (total <= 0) return { pct: 0, phase: 'idle' }
  if (answered < total) return { pct: (answered / total) * 90, phase: 'generating' }
  // All cases generated, run not done → RAGAS scoring phase. If we have a live
  // scoring fraction (judge calls done / estimated), map it into the 90-100%
  // band, clamped to 99% so an imperfect estimate never fakes completion;
  // otherwise hold at 95%.
  if (scoringFrac != null) {
    const frac = Math.min(1, Math.max(0, scoringFrac))
    return { pct: Math.min(99, 90 + 10 * frac), phase: 'scoring' }
  }
  return { pct: 95, phase: 'scoring' }
}
