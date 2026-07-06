'use client'

import type { ReactNode } from 'react'
import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/** Collapsible "Advanced" disclosure. Presentational only — children stay mounted
 * in the form tree (their state lives in the parent page); this just toggles
 * visibility. Collapsed by default. */
export function AdvancedSection({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-sm font-medium text-gray-600 hover:text-gray-900"
      >
        <ChevronRight
          className={`h-4 w-4 transition-transform ${open ? 'rotate-90' : ''}`}
        />
        {t('common.advanced')}
      </button>
      {open && <div className="space-y-4">{children}</div>}
    </div>
  )
}
