import * as LabelPrimitive from '@radix-ui/react-label'
import { forwardRef, ComponentPropsWithoutRef, ElementRef } from 'react'
import { cn } from '@/lib/utils'

export const Label = forwardRef<
  ElementRef<typeof LabelPrimitive.Root>,
  ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn('text-sm font-medium text-fg-muted leading-none peer-disabled:opacity-70', className)}
    {...props}
  />
))
Label.displayName = 'Label'
