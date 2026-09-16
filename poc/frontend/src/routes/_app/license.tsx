import { createFileRoute } from '@tanstack/react-router'

import { LicensePage } from '@/pages/LicensePage'

export const Route = createFileRoute('/_app/license')({
  component: LicensePage,
})
