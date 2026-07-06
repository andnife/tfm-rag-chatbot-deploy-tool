import { describe, it, expect } from 'vitest'
import { computeRunProgress } from '@/lib/evalProgress'

describe('computeRunProgress', () => {
  it('reports the generation phase scaled to 0-90% while cases are answered', () => {
    expect(computeRunProgress(2, 5, 'running')).toEqual({ pct: 36, phase: 'generating' })
  })

  it('holds below 100% in a distinct "scoring" phase once all cases are answered but the run is not done', () => {
    // The bug: it used to jump to 100% here (answered === total) while RAGAS
    // scoring was still running, so the bar looked finished/stuck.
    expect(computeRunProgress(5, 5, 'running')).toEqual({ pct: 95, phase: 'scoring' })
  })

  it('maps the live scoring fraction into the 90-100% band while scoring', () => {
    expect(computeRunProgress(5, 5, 'running', 0)).toEqual({ pct: 90, phase: 'scoring' })
    expect(computeRunProgress(5, 5, 'running', 0.6)).toEqual({ pct: 96, phase: 'scoring' })
  })

  it('clamps scoring to 99% (never fakes completion if the estimate is off)', () => {
    expect(computeRunProgress(5, 5, 'running', 1)).toEqual({ pct: 99, phase: 'scoring' })
    expect(computeRunProgress(5, 5, 'running', 2.5)).toEqual({ pct: 99, phase: 'scoring' })
  })

  it('reaches 100% only when the run is done', () => {
    expect(computeRunProgress(5, 5, 'done')).toEqual({ pct: 100, phase: 'done' })
    expect(computeRunProgress(5, 5, 'done', 0.4)).toEqual({ pct: 100, phase: 'done' })
  })

  it('is idle at 0% before any total is known', () => {
    expect(computeRunProgress(0, 0, 'queued')).toEqual({ pct: 0, phase: 'idle' })
  })

  it('reports a terminal "failed" state at wherever generation stopped, never a scoring bar', () => {
    // The bug: a failed run with all cases answered used to fall into the
    // scoring branch and show a "scoring 95%" bar even though nothing is
    // running anymore.
    expect(computeRunProgress(3, 5, 'failed')).toEqual({ pct: 60, phase: 'failed' })
    expect(computeRunProgress(5, 5, 'failed')).toEqual({ pct: 100, phase: 'failed' })
  })

  it('reports a terminal "cancelled" state at wherever generation stopped, never a scoring bar', () => {
    expect(computeRunProgress(3, 5, 'cancelled')).toEqual({ pct: 60, phase: 'cancelled' })
    expect(computeRunProgress(5, 5, 'cancelled')).toEqual({ pct: 100, phase: 'cancelled' })
  })
})
