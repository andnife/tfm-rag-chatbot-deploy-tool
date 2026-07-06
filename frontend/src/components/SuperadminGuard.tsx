'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useMe } from '@/lib/queries'

/**
 * Client-side gate for superadmin-only pages (Inspect, Eval, Users).
 * Redirects non-superadmins to the dashboard. This is UX only — the backend
 * (`require_superadmin`, 403) is the actual security boundary.
 */
export function SuperadminGuard({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading } = useMe()
  const router = useRouter()

  useEffect(() => {
    if (!isLoading && me && !me.is_superadmin) router.replace('/dashboard')
  }, [isLoading, me, router])

  if (isLoading || !me?.is_superadmin) return null
  return <>{children}</>
}
