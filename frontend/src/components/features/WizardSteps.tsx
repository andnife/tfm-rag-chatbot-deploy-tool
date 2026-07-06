import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props { steps: string[]; current: number }

export function WizardSteps({ steps, current }: Props) {
  return (
    <ol className="flex items-center gap-2 sm:gap-4 mb-6 overflow-x-auto -mx-1 px-1 pb-1">
      {steps.map((label, i) => (
        <li key={label} className="flex items-center gap-2 shrink-0">
          <div
            className={cn(
              'w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0',
              i < current ? 'bg-primary-600 text-white' :
              i === current ? 'bg-accent-subtle text-accent ring-2 ring-primary-500' :
              'bg-surface text-fg-muted',
            )}
          >
            {i < current ? <Check className="h-4 w-4" /> : i + 1}
          </div>
          <span
            className={cn(
              'text-xs sm:text-sm whitespace-nowrap',
              i <= current ? 'text-fg' : 'text-fg-muted',
            )}
          >
            {label}
          </span>
          {i < steps.length - 1 && (
            <span className="hidden sm:inline-block w-8 h-px bg-line" />
          )}
        </li>
      ))}
    </ol>
  )
}
