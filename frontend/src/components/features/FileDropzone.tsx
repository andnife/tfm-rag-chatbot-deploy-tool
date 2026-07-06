import { DragEvent, useState } from 'react'
import { UploadCloud } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

// All formats the backend can ingest (keep in sync with SUPPORTED_MIME_TYPES /
// _EXT_TO_MIME on the backend). Extensions drive the file-picker filter.
export const SUPPORTED_ACCEPT = '.pdf,.txt,.md,.markdown,.csv,.docx'

interface Props {
  onFiles: (files: File[]) => void
  accept?: string
  maxSizeMb?: number
  multiple?: boolean
}

export function FileDropzone({
  onFiles,
  accept = SUPPORTED_ACCEPT,
  maxSizeMb = 50,
  multiple = true,
}: Props) {
  const { t } = useTranslation()
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validateAndEmit = (files: File[]) => {
    setError(null)
    if (files.length === 0) return
    const tooBig = files.filter((f) => f.size > maxSizeMb * 1024 * 1024)
    const ok = files.filter((f) => f.size <= maxSizeMb * 1024 * 1024)
    if (tooBig.length > 0) {
      setError(t('upload.fileTooLarge', { maxSizeMb }))
    }
    if (ok.length > 0) onFiles(ok)
  }

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault(); setDragging(false)
    const files = Array.from(e.dataTransfer.files ?? [])
    validateAndEmit(multiple ? files : files.slice(0, 1))
  }

  return (
    <div>
      <div
        className={cn(
          'border-2 border-dashed rounded-lg p-10 text-center transition-colors cursor-pointer',
          dragging ? 'border-primary-500 bg-primary-50' : 'border-gray-300 bg-gray-50 hover:bg-gray-100',
        )}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => document.getElementById('file-input')?.click()}
      >
        <UploadCloud className="h-10 w-10 mx-auto text-gray-400" />
        <p className="mt-2 text-sm">{t('upload.dragText')}</p>
        <p className="text-xs text-gray-500 mt-1">{t('upload.formatHint', { accept, maxSizeMb })}</p>
        <input
          id="file-input" type="file" accept={accept} multiple={multiple} className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            validateAndEmit(files)
            e.target.value = ''  // allow re-selecting the same file(s)
          }}
        />
      </div>
      {error && <p className="text-xs text-danger mt-2">{error}</p>}
    </div>
  )
}
