import { createFileRoute } from '@tanstack/react-router'

import { ReportsPage } from '@/pages/ReportsPage'

export const Route = createFileRoute('/_app/reports')({
  component: ReportsPage,
})
