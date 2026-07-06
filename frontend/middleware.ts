import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PUBLIC_PREFIXES = ['/login', '/register', '/widget', '/_next', '/favicon']
const COOKIE_NAME = 'tfm_rag_token'

// Two-layer gating:
//  - `config.matcher` skips middleware entirely for high-volume static assets
//    (_next/static, _next/image, favicon, api) — a performance optimization.
//  - PUBLIC_PREFIXES then lets the remaining unauthenticated-public paths through:
//    auth pages, the embeddable /widget, and any other /_next/* paths the matcher
//    still routes here (e.g. RSC data fetches under /_next/data).
// The cookie-presence check is a UX redirect gate only; real auth is enforced
// by the backend on every /api request (the tfm_rag_token cookie is httpOnly).
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl
  if (PUBLIC_PREFIXES.some((p) => pathname.startsWith(p))) return NextResponse.next()
  const hasCookie = req.cookies.has(COOKIE_NAME)
  if (!hasCookie) {
    const url = req.nextUrl.clone()
    url.pathname = '/login'
    return NextResponse.redirect(url)
  }
  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
}
