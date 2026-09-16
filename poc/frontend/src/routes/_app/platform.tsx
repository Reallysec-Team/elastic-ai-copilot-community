import { createFileRoute } from '@tanstack/react-router'

import { PlatformOpsPage } from '@/pages/PlatformOpsPage'

export const Route = createFileRoute('/_app/platform')({
  component: PlatformOpsPage,
})
