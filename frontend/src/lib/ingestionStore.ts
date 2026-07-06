import { create } from 'zustand'

import type { IngestionStage } from '@/types/api'

export interface TrackedJob {
  jobId: string
  kbId: string
  sourceId: string
  filename: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'pending' | 'not_started'
  progress: number
  stage?: IngestionStage | 'uploading' | null
  itemsDone?: number | null
  itemsTotal?: number | null
  uploadFraction?: number
  error: string | null
  startedAt: number
}

interface IngestionStore {
  jobs: Record<string, TrackedJob>
  open: boolean
  track: (job: Omit<TrackedJob, 'startedAt'>) => void
  update: (jobId: string, patch: Partial<TrackedJob>) => void
  remove: (jobId: string) => void
  setOpen: (open: boolean) => void
  clear: () => void
}

export const useIngestionStore = create<IngestionStore>((set) => ({
  jobs: {},
  open: false,
  track: (job) =>
    set((s) => ({
      jobs: { ...s.jobs, [job.jobId]: { ...job, startedAt: Date.now() } },
      open: true,
    })),
  update: (jobId, patch) =>
    set((s) => {
      const existing = s.jobs[jobId]
      if (!existing) return s
      return { jobs: { ...s.jobs, [jobId]: { ...existing, ...patch } } }
    }),
  remove: (jobId) =>
    set((s) => {
      const next = { ...s.jobs }
      delete next[jobId]
      return { jobs: next }
    }),
  setOpen: (open) => set({ open }),
  clear: () => set({ jobs: {} }),
}))
