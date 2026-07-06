import { Badge } from '@/components/ui/badge'
import type { IngestStatus } from '@/types/api'

const map: Record<IngestStatus, { label: string; variant: 'default' | 'success' | 'warning' | 'danger' | 'info' }> = {
  not_started: { label: 'Sin iniciar', variant: 'default' },
  queued: { label: 'En cola', variant: 'warning' },
  running: { label: 'En curso', variant: 'info' },
  done: { label: 'OK', variant: 'success' },
  failed: { label: 'Fallido', variant: 'danger' },
}

export function IngestionStatusBadge({ status }: { status: IngestStatus | string | undefined }) {
  const entry = status ? map[status as IngestStatus] : undefined
  return <Badge variant={entry?.variant ?? 'default'}>{entry?.label ?? status ?? '—'}</Badge>
}
