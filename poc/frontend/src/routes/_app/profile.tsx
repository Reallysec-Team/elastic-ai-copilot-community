import { createFileRoute } from '@tanstack/react-router'

import { AccountPage } from '@/pages/AccountPage'

export const Route = createFileRoute('/_app/profile')({
  component: () => <AccountPage tab="profile" />,
})
