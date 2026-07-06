'use client'
import { useTranslation } from 'react-i18next'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { Bot, Database, Key, LayoutDashboard, Search, ShieldCheck, Users, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSidebarStore } from '@/lib/sidebarStore'
import { useMe } from '@/lib/queries'

type NavItem = {
  to: string
  i18n: string
  icon: React.ComponentType<{ className?: string }>
  end?: boolean
}

// Visible to every authenticated user.
const BASE_ITEMS: NavItem[] = [
  { to: '/dashboard', i18n: 'nav.home', icon: LayoutDashboard, end: true },
  { to: '/knowledge', i18n: 'nav.knowledge', icon: Database },
  { to: '/chatbots', i18n: 'nav.chatbots', icon: Bot },
  { to: '/settings/credentials', i18n: 'nav.credentials', icon: Key },
]

// Superadmin-only (app-level admin). The backend enforces this too (403).
const ADMIN_ITEMS: NavItem[] = [
  { to: '/inspect', i18n: 'nav.inspect', icon: Search },
  { to: '/admin/users', i18n: 'nav.users', icon: Users },
  { to: '/admin/eval', i18n: 'nav.admin', icon: ShieldCheck },
]

export function Sidebar() {
  const { t } = useTranslation()
  const pathname = usePathname()
  const open = useSidebarStore((s) => s.open)
  const setOpen = useSidebarStore((s) => s.setOpen)
  const { data: me } = useMe()
  const items = me?.is_superadmin ? [...BASE_ITEMS, ...ADMIN_ITEMS] : BASE_ITEMS

  return (
    <>
      {/* Backdrop — only visible when drawer is open on mobile */}
      {open && (
        <button
          type="button"
          aria-label={t('nav.closeMenu')}
          onClick={() => setOpen(false)}
          className="md:hidden fixed inset-0 z-30 bg-black/50"
        />
      )}

      <aside
        className={cn(
          'bg-canvas text-fg border-r border-line flex flex-col w-60 shrink-0 z-40',
          // Desktop: static sidebar.
          'md:static md:translate-x-0 md:h-screen',
          // Mobile: fixed drawer that slides in.
          'fixed inset-y-0 left-0 transition-transform duration-200',
          open ? 'translate-x-0' : '-translate-x-full md:translate-x-0',
        )}
      >
        <div className="flex items-center justify-between px-6 py-5">
          <span className="text-lg font-semibold tracking-tight">RAG Platform</span>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="md:hidden p-1 -mr-1 rounded hover:bg-surface-2"
            aria-label={t('nav.closeMenu')}
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="flex-1 px-3 space-y-1 overflow-y-auto">
          {items.map((item) => {
            const isActive = item.end
              ? pathname === item.to
              : pathname === item.to || pathname.startsWith(item.to + '/')
            return (
              <Link
                key={item.to}
                href={item.to}
                onClick={() => setOpen(false)}
                className={cn(
                  'relative flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-accent-subtle text-accent font-semibold before:absolute before:-left-3 before:top-1.5 before:bottom-1.5 before:w-0.5 before:rounded-r before:bg-accent'
                    : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
                )}
              >
                <item.icon className="h-4 w-4" />
                {t(item.i18n)}
              </Link>
            )
          })}
        </nav>
      </aside>
    </>
  )
}
