import { createFileRoute } from '@tanstack/react-router'

import { TriagePage } from '@/pages/TriagePage'

export const Route = createFileRoute('/_app/triage')({
  component: TriagePage,
})
