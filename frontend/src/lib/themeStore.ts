import { create } from 'zustand'

const KEY = 'tfm_rag_theme'

type Theme = 'light' | 'dark'

function readInitial(): Theme {
  if (typeof window === 'undefined') return 'light'
  const stored = localStorage.getItem(KEY) as Theme | null
  if (stored === 'dark' || stored === 'light') return stored
  // Default to light. Don't auto-follow OS preference — many UI surfaces
  // (Tailwind primitives like Card / Dialog) don't have dark variants
  // yet, so the user opts in explicitly via the topbar toggle.
  return 'light'
}

function apply(theme: Theme) {
  const root = document.documentElement
  if (theme === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
}

interface ThemeState {
  theme: Theme
  setTheme: (t: Theme) => void
  toggleTheme: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: readInitial(),
  setTheme: (t) => {
    localStorage.setItem(KEY, t)
    apply(t)
    set({ theme: t })
  },
  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    get().setTheme(next)
  },
}))

// Apply theme as early as possible — when this module loads.
if (typeof window !== 'undefined') {
  apply(useThemeStore.getState().theme)
}
