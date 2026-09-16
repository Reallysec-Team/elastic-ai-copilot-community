import { createFileRoute } from '@tanstack/react-router'

import { PosturePage } from '@/pages/PosturePage'

export const Route = createFileRoute('/_app/posture')({
  component: PosturePage,
})
