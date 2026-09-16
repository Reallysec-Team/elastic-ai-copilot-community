import { createFileRoute } from '@tanstack/react-router'

import { ChatPage } from '@/pages/ChatPage'

export const Route = createFileRoute('/_app/')({
  component: ChatPage,
})
