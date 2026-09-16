import { createFileRoute } from '@tanstack/react-router'

import { DetectionRulePage } from '@/pages/DetectionRulePage'

export const Route = createFileRoute('/_app/detection-rules')({
  component: DetectionRulePage,
})
