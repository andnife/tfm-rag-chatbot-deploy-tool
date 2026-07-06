// Single source of truth for the ingestion progress bar weights.
// The whole 0–100 bar is split across the lifecycle phases, weighted by how
// long each typically takes. Tune the bands here — the backend only reports
// which phase it's in (`stage`) plus a chunk/batch counter; the frontend owns
// the math. The "uploading" band is driven by XHR bytes (the backend has no
// job yet during upload); embedding/indexing fractions come from items_done.

export type BarStage =
  | 'uploading'
  | 'extracting'
  | 'chunking'
  | 'embedding'
  | 'indexing'

const WEIGHTS: Record<BarStage, [number, number]> = {
  uploading: [0, 25],
  extracting: [25, 35],
  chunking: [35, 42],
  embedding: [42, 90],
  indexing: [90, 100],
}

/** Position (0–100) of the unified bar for a stage + intra-phase fraction. */
export function barPosition(stage: BarStage | null, fraction: number): number {
  if (!stage) return 0
  const [lo, hi] = WEIGHTS[stage]
  const f = Math.min(1, Math.max(0, fraction))
  return Math.round(lo + (hi - lo) * f)
}

/** i18n key for the stage label shown under the bar. */
export function stageLabelKey(stage: BarStage | null): string {
  return stage ? `ingestion.stage.${stage}` : 'ingestion.stage.processing'
}

export type JobStatus =
  | 'not_started'
  | 'queued'
  | 'pending'
  | 'running'
  | 'done'
  | 'failed'

/**
 * Bar position (0–100) that respects the terminal state. The backend's final
 * progress tick is `on_progress(100)` with NO stage, so `barPosition(null, …)`
 * would otherwise collapse the bar to 0% on completion. Rules:
 * - `done`  → 100 (always full when finished).
 * - running → never 100 (capped at 99 so we never show "100% + en curso").
 * - if the stage is missing mid-run, fall back to the backend `progress` int.
 */
export function displayProgress(
  status: JobStatus | null,
  stage: BarStage | null,
  fraction: number,
  backendProgress: number,
): number {
  if (status === 'done') return 100
  const base = stage ? barPosition(stage, fraction) : backendProgress
  const clamped = Math.max(0, Math.min(100, base))
  if (status === 'failed') return clamped
  return Math.min(99, clamped)
}
