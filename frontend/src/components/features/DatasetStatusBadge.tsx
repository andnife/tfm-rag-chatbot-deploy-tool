import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import type { DatasetStatus } from '@/types/api'

const VARIANT_MAP: Record<DatasetStatus, 'default' | 'info' | 'success' | 'danger'> = {
  draft: 'default',
  processing: 'info',
  ready: 'success',
  failed: 'danger',
}

interface Props {
  status: DatasetStatus
}

export function DatasetStatusBadge({ status }: Props) {
  const { t } = useTranslation()
  return (
    <Badge variant={VARIANT_MAP[status]}>
      {t(`eval.datasets.status.${status}`)}
    </Badge>
  )
}
