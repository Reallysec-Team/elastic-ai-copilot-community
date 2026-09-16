import { createFileRoute } from '@tanstack/react-router'

import { BaselinePage } from '@/pages/BaselinePage'

export const Route = createFileRoute('/_app/baseline')({
  component: BaselinePage,
})
