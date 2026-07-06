import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { FileDropzone } from './FileDropzone'
import { IngestionStatusBadge } from './IngestionStatusBadge'
import { useIngestionJob, useUploadDocument } from '@/lib/queries'
import { useIngestionStore } from '@/lib/ingestionStore'
import { displayProgress, stageLabelKey, type BarStage, type JobStatus } from '@/lib/ingestionProgress'
import { ApiError } from '@/lib/api'

interface Props { kbId: string }

export function UploadDocumentDialog({ kbId }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [uploadFraction, setUploadFraction] = useState(0)
  const upload = useUploadDocument(kbId)
  const job = useIngestionJob(jobId)
  const trackJob = useIngestionStore((s) => s.track)

  const track = (src: { job_id: string; source_id: string }, filename: string) =>
    trackJob({
      jobId: src.job_id, kbId, sourceId: src.source_id, filename,
      status: 'queued', progress: 0, error: null,
    })

  const onFiles = (files: File[]) => {
    if (files.length === 0) return
    // Single file: keep the detailed inline progress view.
    if (files.length === 1) {
      const file = files[0]
      setUploadFraction(0)
      upload.mutate(
        { file, onProgress: setUploadFraction },
        {
          onSuccess: (src) => { setJobId(src.job_id); track(src, file.name); toast.success(t('upload.success')) },
          onError: (err) => toast.error(err instanceof ApiError ? err.message : t('upload.error')),
        },
      )
      return
    }
    // Multiple files: launch one independent ingestion job per file; each is
    // tracked in the global IngestionJobsPanel. Close the dialog.
    files.forEach((file) => {
      upload.mutate(
        { file },
        {
          onSuccess: (src) => track(src, file.name),
          onError: (err) => toast.error(`${file.name}: ${err instanceof ApiError ? err.message : t('upload.error')}`),
        },
      )
    })
    toast.success(t('upload.successMultiple', { count: files.length }))
    close()
  }

  const close = () => { setOpen(false); setJobId(null); setUploadFraction(0) }

  const uploading = upload.isPending && !jobId
  const status = (job.data?.status ?? null) as JobStatus | null
  let stage: BarStage | null = null
  let fraction = 0
  if (uploading) {
    stage = 'uploading'
    fraction = uploadFraction
  } else if (job.data) {
    stage = job.data.stage
    fraction = job.data.items_total ? (job.data.items_done ?? 0) / job.data.items_total : 0
  }
  // Handoff window: job created but first poll not back yet → hold at upload band end.
  const pct = jobId && !job.data
    ? 25
    : displayProgress(status, stage, fraction, job.data?.progress ?? 0)
  const showProgress = uploading || Boolean(jobId)
  const showCounter = stage === 'embedding' && job.data?.items_total
  const stageLabel = status === 'done' ? t('ingestion.done') : t(stageLabelKey(stage))

  // Auto-close shortly after a successful ingestion (the job keeps showing in
  // the global IngestionJobsPanel). On failure we keep it open to show the error.
  useEffect(() => {
    if (status !== 'done') return
    const tmr = setTimeout(() => { setOpen(false); setJobId(null); setUploadFraction(0) }, 1500)
    return () => clearTimeout(tmr)
  }, [status])

  return (
    <Dialog open={open} onOpenChange={(o) => o ? setOpen(true) : close()}>
      <DialogTrigger asChild><Button>{t('upload.button')}</Button></DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('upload.title')}</DialogTitle></DialogHeader>
        {!showProgress && <FileDropzone onFiles={onFiles} />}
        {showProgress && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm">{stageLabel}</span>
              {job.data && <IngestionStatusBadge status={job.data.status} />}
            </div>
            <div className="w-full bg-gray-100 rounded-full h-2 overflow-hidden">
              <div
                className="bg-primary-600 h-2 rounded-full transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-xs text-gray-500 text-right">
              {showCounter
                ? t('ingestion.chunks', { done: job.data?.items_done ?? 0, total: job.data?.items_total })
                : `${pct}%`}
            </p>
            {job.data?.error && (
              <p className="text-sm text-danger">{job.data.error}</p>
            )}
            {(job.data?.status === 'done' || job.data?.status === 'failed') && (
              <div className="flex justify-end"><Button onClick={close}>{t('common.close')}</Button></div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
