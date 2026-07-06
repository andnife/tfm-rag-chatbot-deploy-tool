'use client'
import { IngestionJobsPanel } from '@/components/features/IngestionJobsPanel'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <IngestionJobsPanel />
    </>
  )
}
