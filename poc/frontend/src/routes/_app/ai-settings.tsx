import { createFileRoute } from '@tanstack/react-router'

import AiSettingsPage from '@/pages/AiSettingsPage'

export const Route = createFileRoute('/_app/ai-settings')({
  component: AiSettingsPage,
})
