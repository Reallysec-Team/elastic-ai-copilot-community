import { createFileRoute } from '@tanstack/react-router'

import { NotifyPage } from '@/pages/NotifyPage'

export const Route = createFileRoute('/_app/notify')({
  component: NotifyPage,
})
