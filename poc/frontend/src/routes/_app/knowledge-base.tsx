import { createFileRoute } from '@tanstack/react-router'

import { KbPage } from '@/pages/KbPage'

export const Route = createFileRoute('/_app/knowledge-base')({
  component: KbPage,
})
