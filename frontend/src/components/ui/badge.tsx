import { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium',
  {
    variants: {
      variant: {
        default: 'border-line bg-surface-2 text-fg-muted',
        success: 'border-success/30 bg-success-subtle text-success',
        warning: 'border-warning/30 bg-warning-subtle text-warning',
        danger: 'border-accent-border bg-accent-subtle text-accent',
        destructive: 'border-accent-border bg-accent-subtle text-accent',
        info: 'border-info/30 bg-info-subtle text-info',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
