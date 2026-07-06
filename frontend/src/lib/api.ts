interface ParsedError {
  code: string
  message?: string
  detail?: unknown
}

/**
 * Normalise the many error envelopes the backend can emit into one shape:
 *  - FastAPI HTTPException:        { detail: "..." }
 *  - FastAPI validation (422):     { detail: [{ loc, msg, type }, ...] }
 *  - domain handler / middleware:  { error: { code, message, detail } }
 *  - flat:                         { code, message, detail }
 * Without this, toasts fell back to res.statusText ("Conflict"/"Bad Gateway")
 * because none of those shapes has a top-level `message`.
 */
function parseErrorBody(raw: unknown): ParsedError {
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, unknown>
    if (o.error && typeof o.error === 'object') {
      const e = o.error as Record<string, unknown>
      return {
        code: (e.code as string) ?? 'ERROR',
        message: e.message as string | undefined,
        detail: e.detail,
      }
    }
    if (typeof o.detail === 'string') {
      return { code: (o.code as string) ?? 'ERROR', message: o.detail, detail: o.detail }
    }
    if (Array.isArray(o.detail)) {
      const msg = o.detail
        .map((d) => (d && typeof d === 'object' ? (d as Record<string, unknown>).msg : null))
        .filter(Boolean)
        .join('; ')
      return { code: 'VALIDATION_ERROR', message: msg || 'Datos inválidos', detail: o.detail }
    }
    if (o.message || o.code) {
      return {
        code: (o.code as string) ?? 'ERROR',
        message: o.message as string | undefined,
        detail: o.detail,
      }
    }
  }
  return { code: 'ERROR' }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiFetch<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = new Headers(opts.headers)
  if (opts.body && !(opts.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const res = await fetch(`/api${path}`, { ...opts, headers, credentials: 'include' })

  if (res.status === 401) {
    let parsed: ParsedError = { code: 'UNAUTHENTICATED' }
    try { parsed = parseErrorBody(await res.json()) } catch { /* sin cuerpo */ }
    if (typeof window !== 'undefined') {
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
        throw new ApiError(401, parsed.code ?? 'UNAUTHENTICATED', 'Sesión caducada', parsed.detail)
      }
    }
    throw new ApiError(401, parsed.code ?? 'UNAUTHENTICATED', parsed.message ?? 'Credenciales incorrectas', parsed.detail)
  }

  if (!res.ok) {
    let parsed: ParsedError = { code: 'ERROR' }
    try { parsed = parseErrorBody(await res.json()) } catch { /* sin cuerpo */ }
    throw new ApiError(res.status, parsed.code, parsed.message ?? res.statusText ?? 'Error desconocido', parsed.detail)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export function apiJson<T>(path: string, method: 'POST' | 'PATCH' | 'PUT' | 'DELETE', body?: unknown): Promise<T> {
  return apiFetch<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}
