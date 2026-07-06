import { ApiError } from '@/lib/api'
import type { UploadDocumentOut } from '@/types/api'

/**
 * Upload a document via XMLHttpRequest so we get real upload-byte progress
 * (`fetch()` doesn't expose `onUploadProgress`). `onProgress` is called with a
 * fraction 0..1 of bytes sent — the dialog maps it to the 0–25 % "uploading"
 * band of the unified ingestion bar. Mirrors apiFetch's credentials + error
 * envelope so callers keep throwing ApiError.
 */
export function uploadDocumentXhr(
  kbId: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<UploadDocumentOut> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const fd = new FormData()
    fd.append('file', file)
    xhr.open('POST', `/api/knowledge-bases/${kbId}/sources/documents`)
    xhr.withCredentials = true
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadDocumentOut)
        } catch {
          reject(new ApiError(xhr.status, 'PARSE', 'Respuesta no válida'))
        }
      } else {
        let msg = xhr.statusText || 'Error al subir'
        try {
          const b = JSON.parse(xhr.responseText) as { detail?: string; message?: string }
          msg = b.detail ?? b.message ?? msg
        } catch {
          /* sin cuerpo JSON */
        }
        reject(new ApiError(xhr.status, 'UPLOAD_ERROR', msg))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'NETWORK', 'Error de red al subir'))
    xhr.send(fd)
  })
}
