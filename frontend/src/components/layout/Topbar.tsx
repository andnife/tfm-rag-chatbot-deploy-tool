'use client'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { LogOut, Menu, Moon, Sun, User, Languages } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import { logout } from '@/lib/auth'
import { useMe } from '@/lib/queries'
import { useThemeStore } from '@/lib/themeStore'
import { useSidebarStore } from '@/lib/sidebarStore'
import { setLang, type Lang } from '@/lib/i18n'

export function Topbar({ title }: { title: string }) {
  const { t, i18n } = useTranslation()
  const { data: me } = useMe()
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const toggleSidebar = useSidebarStore((s) => s.toggle)
  // The theme is only known on the client (localStorage). Render the toggle
  // icon (Sun has a <circle>, Moon doesn't) ONLY after mount so the server
  // render and the first client render match — otherwise React throws a
  // hydration mismatch on the <svg>.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  return (
    <header className="h-16 bg-canvas border-b border-line flex items-center justify-between px-3 sm:px-6 gap-2">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleSidebar}
          className="md:hidden"
          aria-label={t('nav.openMenu')}
        >
          <Menu className="h-5 w-5" />
        </Button>
        <h1 className="text-base sm:text-lg font-semibold text-fg truncate">
          {title}
        </h1>
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggleTheme}
          title={theme === 'dark' ? t('theme.light') : t('theme.dark')}
          suppressHydrationWarning
        >
          {mounted
            ? (theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />)
            : <span className="h-5 w-5" />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" title={t('nav.language')}>
              <Languages className="h-5 w-5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {(['es', 'en'] as Lang[]).map((l) => (
              <DropdownMenuItem
                key={l}
                onClick={() => setLang(l)}
                className={i18n.language === l ? 'bg-accent-subtle text-accent font-semibold' : ''}
              >
                {t(`lang.${l}`)}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t('nav.userMenu')}>
              <User className="h-5 w-5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {me && <div className="px-2 py-1.5 text-xs text-fg-muted">{me.email}</div>}
            <DropdownMenuItem onClick={logout}>
              <LogOut className="h-4 w-4 mr-2" /> {t('nav.logout')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
