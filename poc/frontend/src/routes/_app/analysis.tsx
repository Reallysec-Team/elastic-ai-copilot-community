import { createFileRoute } from '@tanstack/react-router'

import { AnalysisRecords } from '@/pages/AnalysisRecords'

export const Route = createFileRoute('/_app/analysis')({
  component: AnalysisRecords,
})
